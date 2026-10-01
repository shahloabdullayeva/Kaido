import json
import math
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from . import google_places
from .db import cursor, execute, one, rows
from .logs import get

log = get("shops")

class OverpassBusy(Exception):
    pass


OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
NEARBY_CACHE_DEGREES = 0.07
FALLBACK_CACHE_DEGREES = 0.35
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "Kaido/1.0 fleet maintenance (+https://kaido.shahlo.blog)"
CACHE_DAYS = 7
GEOCODE_DAYS = 90
# Google's terms allow only brief caching of Places content (coordinates up to 30 days).
GOOGLE_CACHE_HOURS = 1
GOOGLE_GEOCODE_DAYS = 30
GOOGLE_QUERIES = ("semi truck repair shop", "truck stop")
EARTH_MILES = 3958.7613

QUERY = """[out:json][timeout:50];
(
  nwr["shop"="truck_repair"](around:{radius},{lat},{lon});
  nwr["amenity"="truck_stop"](around:{radius},{lat},{lon});
  nwr["shop"="car_repair"](around:{radius},{lat},{lon});
  nwr["shop"="tyres"](around:{radius},{lat},{lon});
  nwr["amenity"="fuel"]["hgv"="yes"](around:{radius},{lat},{lon});
);
out center tags;"""

TRUCK_BRANDS = ("ta truck", "ta travel", "petro", "love", "pilot", "flying j",
                "speedco", "tires? plus truck", "boss shop", "sapp bros",
                "roady", "travelcenters", "freightliner", "kenworth", "peterbilt",
                "volvo truck", "mack truck", "international truck", "ryder",
                "penske", "fleetpride", "bruckner", "rush truck", "wingfoot",
                "southern tire mart", "best one", "goodyear commercial")

DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
DAY_INDEX = {name: i for i, name in enumerate(DAYS)}
TIME_RANGE = re.compile(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$")

US_ZONES = [
    (-67.5, "America/Halifax"),
    (-82.5, "America/New_York"),
    (-97.5, "America/Chicago"),
    (-112.5, "America/Denver"),
    (-180.0, "America/Los_Angeles"),
]

BRAND_HINTS = {
    "ta truck": "TA Truck Service", "petro": "Petro Stopping Center",
    "love": "Love's Truck Care", "pilot": "Pilot", "flying j": "Flying J",
    "speedco": "Speedco", "fleetpride": "FleetPride", "rush truck": "Rush Truck Centers",
}


def zone_for(longitude):
    for edge, name in US_ZONES:
        if longitude >= edge:
            return ZoneInfo(name)
    return ZoneInfo("America/Chicago")


def haversine(lat1, lon1, lat2, lon2):
    radians = [math.radians(float(v)) for v in (lat1, lon1, lat2, lon2)]
    dlat = radians[2] - radians[0]
    dlon = radians[3] - radians[1]
    a = math.sin(dlat / 2) ** 2 + math.cos(radians[0]) * math.cos(radians[2]) * math.sin(dlon / 2) ** 2
    return EARTH_MILES * 2 * math.asin(math.sqrt(a))


def _expand_days(token):
    token = token.strip()
    if not token:
        return []
    if "-" in token:
        start, _, end = token.partition("-")
        first, last = DAY_INDEX.get(start.strip()), DAY_INDEX.get(end.strip())
        if first is None or last is None:
            return []
        if first <= last:
            return list(range(first, last + 1))
        return list(range(first, 7)) + list(range(0, last + 1))
    index = DAY_INDEX.get(token)
    return [index] if index is not None else []


def _parse_rule(rule):
    rule = rule.strip()
    if not rule:
        return None
    lowered = rule.lower()
    if lowered in ("24/7", "24x7", "mo-su 00:00-24:00"):
        return {"days": list(range(7)), "spans": [(0, 1440)], "closed": False}
    parts = rule.split()
    if not parts:
        return None
    if len(parts) == 1 and TIME_RANGE.match(parts[0]):
        days, times = list(range(7)), parts[0]
    else:
        day_token, times = parts[0], " ".join(parts[1:])
        days = []
        for chunk in day_token.split(","):
            days.extend(_expand_days(chunk))
        if not days:
            return None
    times = times.strip()
    if times.lower() in ("off", "closed"):
        return {"days": days, "spans": [], "closed": True}
    if times.lower() in ("24/7", "00:00-24:00"):
        return {"days": days, "spans": [(0, 1440)], "closed": False}
    spans = []
    for chunk in times.split(","):
        found = TIME_RANGE.match(chunk.strip())
        if not found:
            continue
        start = int(found.group(1)) * 60 + int(found.group(2))
        end = int(found.group(3)) * 60 + int(found.group(4))
        spans.append((start, end if end > start else end + 1440))
    if not spans:
        return None
    return {"days": days, "spans": spans, "closed": False}


def parse_hours(raw, now):
    if not raw:
        return "unknown", "hours not listed"
    cleaned = re.sub(r"\bPH\b[^;]*;?", "", raw).strip().strip(";")
    if cleaned.lower().replace(" ", "") in ("24/7", "24x7"):
        return "open", "open 24/7"
    rules = [_parse_rule(part) for part in cleaned.split(";")]
    rules = [rule for rule in rules if rule]
    if not rules:
        return "unknown", f"hours listed as “{raw[:40]}”"
    minute = now.hour * 60 + now.minute
    today = now.weekday()
    yesterday = (today - 1) % 7
    for rule in rules:
        if rule["closed"]:
            continue
        for start, end in rule["spans"]:
            if today in rule["days"] and start <= minute < min(end, 1440):
                return "open", f"open until {_hhmm(end % 1440)}"
            if end > 1440 and yesterday in rule["days"] and minute < end - 1440:
                return "open", f"open until {_hhmm(end - 1440)}"
    for ahead in range(0, 8):
        day = (today + ahead) % 7
        for rule in rules:
            if rule["closed"] or day not in rule["days"]:
                continue
            for start, _end in sorted(rule["spans"]):
                if ahead == 0 and start <= minute:
                    continue
                when = "today" if ahead == 0 else ("tomorrow" if ahead == 1 else DAYS[day])
                return "closed", f"closed, opens {when} {_hhmm(start)}"
    return "closed", "closed"


def _hhmm(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


SPACING = {"nominatim": 1.1, "overpass": 2.0}


def _polite(service):
    gap = SPACING[service]
    with cursor() as cur:
        cur.execute("insert into osm_calls (service) values (%s) on conflict do nothing", (service,))
        cur.execute("select extract(epoch from now() - last_at) as since from osm_calls where service = %s for update",
                    (service,))
        since = float(cur.fetchone()["since"])
        if since < gap:
            time.sleep(gap - since)
        cur.execute("update osm_calls set last_at = clock_timestamp() where service = %s", (service,))


def _cell(latitude, longitude):
    return f"{round(float(latitude), 2):.2f},{round(float(longitude), 2):.2f}"


def _fetch(latitude, longitude, radius_m):
    body = QUERY.format(radius=radius_m, lat=float(latitude), lon=float(longitude))
    for number, url in enumerate(OVERPASS_URLS):
        if number == 0:
            _polite("overpass")
        try:
            response = requests.post(url, data={"data": body}, headers={"User-Agent": USER_AGENT},
                                     timeout=(6, 30 if number == 0 else 12))
        except requests.RequestException as err:
            log.warning("overpass %s failed: %s", url, err)
            continue
        if response.status_code != 200:
            log.warning("overpass %s answered %s", url, response.status_code)
            continue
        try:
            return response.json().get("elements") or []
        except ValueError:
            log.warning("overpass %s sent something that was not JSON", url)
    raise OverpassBusy("OpenStreetMap's free lookup service is busy right now")


def _nearest_lookup(latitude, longitude, radius_m, degrees, days):
    row = one(
        """select payload from shop_lookups
           where radius_m >= %s and (%s::int is null or fetched_at > now() - make_interval(days => %s::int))
             and abs(split_part(cell, ',', 1)::numeric - %s) <= %s
             and abs(split_part(cell, ',', 2)::numeric - %s) <= %s
           order by abs(split_part(cell, ',', 1)::numeric - %s) + abs(split_part(cell, ',', 2)::numeric - %s), fetched_at desc
           limit 1""",
        (radius_m, days, days, float(latitude), degrees, float(longitude), degrees, float(latitude), float(longitude)),
    )
    return row["payload"] if row else None


def raw_elements(latitude, longitude, radius_m):
    cell = _cell(latitude, longitude)
    fresh = one(
        "select payload from shop_lookups where cell = %s and radius_m = %s and fetched_at > now() - make_interval(days => %s)",
        (cell, radius_m, CACHE_DAYS),
    )
    if fresh:
        return fresh["payload"], True
    near = _nearest_lookup(latitude, longitude, radius_m, NEARBY_CACHE_DEGREES, CACHE_DAYS)
    if near:
        return near, True
    try:
        elements = _fetch(latitude, longitude, radius_m)
    except (OverpassBusy, requests.RequestException):
        stale = one("select payload from shop_lookups where cell = %s and radius_m = %s", (cell, radius_m))
        if stale:
            return stale["payload"], True
        wider = _nearest_lookup(latitude, longitude, radius_m, FALLBACK_CACHE_DEGREES, None)
        if wider:
            return wider, True
        raise
    execute(
        """insert into shop_lookups (cell, radius_m, payload, fetched_at) values (%s, %s, %s, now())
           on conflict (cell, radius_m) do update set payload = excluded.payload, fetched_at = now()""",
        (cell, radius_m, json.dumps(elements)),
    )
    return elements, False


def geocode(text):
    cleaned = " ".join((text or "").split())[:160]
    if not cleaned:
        return None
    if google_places.usable():
        try:
            return _google_geocode(cleaned)
        except google_places.GoogleError as err:
            log.warning("Google geocoding failed for %r, using OpenStreetMap: %s", cleaned, err)
    return _nominatim_geocode(cleaned)


def _google_geocode(cleaned):
    key = "google:" + cleaned.lower()
    row = one(
        "select lat, lon, label from geocodes where query = %s and fetched_at > now() - make_interval(days => %s)",
        (key, GOOGLE_GEOCODE_DAYS),
    )
    if row:
        return {"latitude": float(row["lat"]), "longitude": float(row["lon"]), "label": row["label"]}
    place = google_places.geocode(cleaned)
    if place:
        execute(
            """insert into geocodes (query, lat, lon, label, fetched_at) values (%s, %s, %s, %s, now())
               on conflict (query) do update set lat = excluded.lat, lon = excluded.lon,
                 label = excluded.label, fetched_at = now()""",
            (key, place["latitude"], place["longitude"], place["label"]),
        )
    return place


def _nominatim_geocode(cleaned):
    key = cleaned.lower()
    row = one(
        "select lat, lon, label from geocodes where query = %s and fetched_at > now() - make_interval(days => %s)",
        (key, GEOCODE_DAYS),
    )
    if row:
        return {"latitude": float(row["lat"]), "longitude": float(row["lon"]), "label": row["label"]}
    _polite("nominatim")
    response = requests.get(
        NOMINATIM_URL,
        params={"q": cleaned, "format": "jsonv2", "limit": 1, "countrycodes": "us,ca,mx"},
        headers={"User-Agent": USER_AGENT},
        timeout=25,
    )
    response.raise_for_status()
    found = response.json() or []
    if not found:
        return None
    best = found[0]
    place = {
        "latitude": float(best["lat"]),
        "longitude": float(best["lon"]),
        "label": best.get("display_name") or cleaned,
    }
    execute(
        """insert into geocodes (query, lat, lon, label, fetched_at) values (%s, %s, %s, %s, now())
           on conflict (query) do update set lat = excluded.lat, lon = excluded.lon,
             label = excluded.label, fetched_at = now()""",
        (key, place["latitude"], place["longitude"], place["label"]),
    )
    return place


def reverse(latitude, longitude):
    key = f"reverse:{float(latitude):.5f},{float(longitude):.5f}"
    row = one("select label from geocodes where query = %s and fetched_at > now() - make_interval(days => %s)",
              (key, GEOCODE_DAYS))
    if row:
        return row["label"] or None
    _polite("nominatim")
    response = requests.get(
        NOMINATIM_REVERSE_URL,
        params={"lat": float(latitude), "lon": float(longitude), "format": "jsonv2", "zoom": 18, "addressdetails": 1},
        headers={"User-Agent": USER_AGENT},
        timeout=25,
    )
    response.raise_for_status()
    found = response.json() or {}
    parts = found.get("address") or {}
    street = " ".join(part for part in [parts.get("house_number"), parts.get("road")] if part)
    town = parts.get("city") or parts.get("town") or parts.get("village") or parts.get("hamlet") or parts.get("county")
    state = parts.get("state")
    postcode = parts.get("postcode")
    label = ", ".join(part for part in [street, town, " ".join(p for p in [state, postcode] if p)] if part)
    execute(
        """insert into geocodes (query, lat, lon, label, fetched_at) values (%s, %s, %s, %s, now())
           on conflict (query) do update set label = excluded.label, fetched_at = now()""",
        (key, float(latitude), float(longitude), label),
    )
    return label or None


def dial(phone):
    first = (phone or "").split(";")[0].strip()
    digits = "".join(ch for ch in first if ch.isdigit() or ch == "+")
    return digits or None


def maps_link(shop):
    from urllib.parse import quote
    if shop.get("address"):
        query = f"{shop['name']}, {shop['address']}"
    else:
        query = f"{shop['latitude']},{shop['longitude']}"
    return "https://www.google.com/maps/search/?api=1&query=" + quote(query)


def _brand(name):
    lowered = (name or "").lower()
    for key, label in BRAND_HINTS.items():
        if key in lowered:
            return label
    return None


def _truck_fit(tags, name):
    lowered = (name or "").lower()
    if tags.get("hgv") == "no":
        return "no"
    if tags.get("shop") == "truck_repair" or tags.get("amenity") == "truck_stop":
        return "yes"
    if tags.get("hgv") == "yes" or tags.get("hgv:repair") == "yes":
        return "yes"
    if any(re.search(word, lowered) for word in TRUCK_BRANDS):
        return "yes"
    if any(word in lowered for word in ("truck", "diesel", "semi", "fleet", "trailer")):
        return "yes"
    return "unconfirmed"


def nearby(latitude, longitude, radius_miles=50, limit=8, min_confirmed=3):
    """Shops around a point: from Google when it is set up and under today's cap, else OpenStreetMap."""
    if google_places.usable():
        try:
            return _nearby_google(latitude, longitude, radius_miles, limit)
        except google_places.GoogleError as err:
            log.warning("Google shop search failed, using OpenStreetMap: %s", err)
    return _nearby_osm(latitude, longitude, radius_miles, limit, min_confirmed)


def _nearby_osm(latitude, longitude, radius_miles, limit, min_confirmed):
    shops, meta = _collect(latitude, longitude, radius_miles, limit)
    confirmed = [s for s in shops if s["truck_fit"] == "yes"]
    if len(confirmed) < min_confirmed and radius_miles < 100:
        try:
            wider, wider_meta = _collect(latitude, longitude, 100, limit)
        except (OverpassBusy, requests.RequestException) as err:
            log.warning("Overpass failed widening to 100 mi: %s", err)
            return shops[:limit], meta
        if len(wider) > len(shops):
            shops, meta = wider, wider_meta
    return shops[:limit], meta


def _google_places(latitude, longitude, radius_m):
    cell = "g:" + _cell(latitude, longitude)
    fresh = one(
        "select payload from shop_lookups where cell = %s and radius_m = %s and fetched_at > now() - make_interval(hours => %s)",
        (cell, radius_m, GOOGLE_CACHE_HOURS),
    )
    if fresh:
        return fresh["payload"], True
    places, seen = [], set()
    for query in GOOGLE_QUERIES:
        for place in google_places.search_shops(query, latitude, longitude, radius_m):
            if place.get("id") in seen:
                continue
            seen.add(place.get("id"))
            place["_query"] = query
            places.append(place)
    execute(
        """insert into shop_lookups (cell, radius_m, payload, fetched_at) values (%s, %s, %s, now())
           on conflict (cell, radius_m) do update set payload = excluded.payload, fetched_at = now()""",
        (cell, radius_m, json.dumps(places)),
    )
    return places, False


def from_google(place, latitude, longitude, now):
    where = place.get("location") or {}
    lat, lon = where.get("latitude"), where.get("longitude")
    name = (place.get("displayName") or {}).get("text")
    if lat is None or lon is None or not name:
        return None
    if place.get("businessStatus") in ("CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY"):
        return None
    types = set(place.get("types") or [])
    kind = "truck_stop" if "truck_stop" in types else place.get("primaryType") or "shop"
    fit = "yes" if "truck_stop" in types else _truck_fit({}, name)
    state, hours_text = google_places.open_state(place.get("regularOpeningHours"), now)
    hours = place.get("regularOpeningHours") or {}
    return {
        "name": name,
        "brand": _brand(name),
        "truck_fit": fit,
        "kind": kind,
        "latitude": lat,
        "longitude": lon,
        "miles": round(haversine(latitude, longitude, lat, lon), 1),
        "address": _short_address(place.get("formattedAddress")),
        "phone": place.get("nationalPhoneNumber") or place.get("internationalPhoneNumber"),
        "website": place.get("websiteUri"),
        "opening_hours": None,
        "hours_lines": hours.get("weekdayDescriptions") or [],
        "open_state": state,
        "hours_text": hours_text,
        "rating": place.get("rating"),
        "ratings": place.get("userRatingCount"),
        "maps": place.get("googleMapsUri"),
        "place_id": place.get("id"),
        "source": "google",
    }


def _short_address(text):
    if not text:
        return None
    return re.sub(r",\s*(USA|United States|Canada|Mexico)$", "", text)


def _nearby_google(latitude, longitude, radius_miles, limit):
    radius_m = int(radius_miles * 1609.344)
    places, from_cache = _google_places(latitude, longitude, radius_m)
    zone = zone_for(float(longitude))
    now = datetime.now(zone)
    shops = [shop for shop in (from_google(place, latitude, longitude, now) for place in places) if shop]
    shops = [shop for shop in shops if shop["miles"] <= radius_miles * 1.05]
    shops.sort(key=lambda s: (s["truck_fit"] != "yes", s["open_state"] == "closed", s["miles"]))
    return shops[:limit], {"local_time": now, "zone": str(zone), "cached": from_cache, "found": len(shops),
                           "radius_miles": radius_miles, "source": "google"}


# ---------------------------------------------------------------- saved shops

def saved_near(company_id, latitude, longitude, radius_miles):
    found = []
    for row in rows("""select s.*, u.name as added_by_name from saved_shops s
                       left join users u on u.id = s.added_by where s.company_id = %s""", (company_id,)):
        miles = haversine(latitude, longitude, row["latitude"], row["longitude"])
        if miles <= radius_miles:
            found.append(dict(row, miles=round(miles, 1)))
    return sorted(found, key=lambda row: row["miles"])


def _words(text):
    return {word for word in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(word) > 2}


def _same_place(saved, shop):
    apart = haversine(saved["latitude"], saved["longitude"], shop["latitude"], shop["longitude"])
    if saved.get("place_id") and saved["place_id"] == shop.get("place_id"):
        return apart < 1
    if apart > 0.2:
        return False
    return apart < 0.03 or bool(_words(saved["name"]) & _words(shop["name"]))


def _google_details(saved, latitude, longitude, now):
    """Live phone and hours for a saved shop the area search did not return."""
    cell = "gd:" + (saved.get("place_id") or f"{saved['latitude']},{saved['longitude']}")
    cached = one("select payload from shop_lookups where cell = %s and radius_m = 0 "
                 "and fetched_at > now() - make_interval(hours => %s)", (cell, GOOGLE_CACHE_HOURS))
    if cached:
        place = cached["payload"]
    else:
        place = google_places.shop_details(saved["name"], saved["latitude"], saved["longitude"]) or {}
        execute(
            """insert into shop_lookups (cell, radius_m, payload, fetched_at) values (%s, 0, %s, now())
               on conflict (cell, radius_m) do update set payload = excluded.payload, fetched_at = now()""",
            (cell, json.dumps(place)),
        )
    shop = from_google(place, latitude, longitude, now) if place else None
    return shop if shop and _same_place(saved, shop) else None


def with_saved(shops, saved, latitude, longitude, now, details_budget=3):
    """Saved shops first, each carrying whatever live detail the search found for the same place."""
    merged, rest = [], list(shops)
    for row in saved:
        match = next((shop for shop in rest if _same_place(row, shop)), None)
        if match:
            rest.remove(match)
        elif details_budget > 0 and google_places.usable():
            details_budget -= 1
            try:
                match = _google_details(row, latitude, longitude, now)
            except google_places.GoogleError as err:
                log.warning("Google details for saved shop %s failed: %s", row["id"], err)
        live = match or {}
        state, hours_text = (live.get("open_state"), live.get("hours_text")) if match else ("unknown", "hours not checked")
        merged.append({
            **live,
            "name": row["name"],
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
            "miles": row["miles"],
            "address": row["address"] or live.get("address"),
            "phone": row["phone"] or live.get("phone"),
            "website": row["website"] or live.get("website"),
            "maps": row["maps_url"] or live.get("maps"),
            "truck_fit": "yes",
            "kind": live.get("kind") or "truck_repair",
            "open_state": state or "unknown",
            "hours_text": hours_text or "hours not listed",
            "hours_lines": live.get("hours_lines") or [],
            "opening_hours": live.get("opening_hours"),
            "saved": {"id": row["id"], "note": row["note"], "by": row.get("added_by_name")},
        })
    return merged + rest


def _collect(latitude, longitude, radius_miles, limit):
    radius_m = int(radius_miles * 1609.344)
    elements, from_cache = raw_elements(latitude, longitude, radius_m)
    zone = zone_for(float(longitude))
    now = datetime.now(zone)
    shops = []
    for element in elements:
        tags = element.get("tags") or {}
        name = tags.get("name") or tags.get("operator") or tags.get("brand")
        if not name:
            continue
        centre = element.get("center") or element
        lat, lon = centre.get("lat"), centre.get("lon")
        if lat is None or lon is None:
            continue
        state, hours_text = parse_hours(tags.get("opening_hours"), now)
        address = ", ".join(part for part in [
            " ".join(part for part in [tags.get("addr:housenumber"), tags.get("addr:street")] if part),
            tags.get("addr:city"), tags.get("addr:state"),
        ] if part)
        fit = _truck_fit(tags, name)
        if fit == "no":
            continue
        shops.append({
            "name": name,
            "brand": _brand(name),
            "truck_fit": fit,
            "kind": tags.get("shop") or tags.get("amenity"),
            "latitude": lat,
            "longitude": lon,
            "miles": round(haversine(latitude, longitude, lat, lon), 1),
            "address": address or None,
            "phone": (tags.get("phone") or tags.get("contact:phone") or "").split(";")[0].strip() or None,
            "website": tags.get("website") or tags.get("contact:website"),
            "opening_hours": tags.get("opening_hours"),
            "open_state": state,
            "hours_text": hours_text,
        })
    shops.sort(key=lambda s: (s["truck_fit"] != "yes", s["open_state"] == "closed", s["miles"]))
    return shops, {"local_time": now, "zone": str(zone), "cached": from_cache,
                   "found": len(shops), "radius_miles": radius_miles, "source": "osm"}
