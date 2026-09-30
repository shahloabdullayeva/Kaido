import json
import math
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from .db import cursor, execute, one

class OverpassBusy(Exception):
    pass


OVERPASS_URL = "https://overpass-api.de/api/interpreter"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "Kaido/1.0 fleet maintenance (+https://kaido.shahlo.blog)"
CACHE_DAYS = 7
GEOCODE_DAYS = 90
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


def _fetch(latitude, longitude, radius_m, attempts=3):
    body = QUERY.format(radius=radius_m, lat=float(latitude), lon=float(longitude))
    for attempt in range(1, attempts + 1):
        _polite("overpass")
        response = requests.post(OVERPASS_URL, data={"data": body},
                                 headers={"User-Agent": USER_AGENT}, timeout=60)
        if response.status_code in (429, 504) and attempt < attempts:
            wait = int(response.headers.get("Retry-After") or 0) or attempt * 4
            time.sleep(min(wait, 15))
            continue
        response.raise_for_status()
        return response.json().get("elements") or []
    raise OverpassBusy("OpenStreetMap's free lookup service is busy right now")


def raw_elements(latitude, longitude, radius_m):
    cell = _cell(latitude, longitude)
    fresh = one(
        "select payload from shop_lookups where cell = %s and radius_m = %s and fetched_at > now() - make_interval(days => %s)",
        (cell, radius_m, CACHE_DAYS),
    )
    if fresh:
        return fresh["payload"], True
    try:
        elements = _fetch(latitude, longitude, radius_m)
    except (OverpassBusy, requests.RequestException):
        stale = one("select payload from shop_lookups where cell = %s and radius_m = %s", (cell, radius_m))
        if stale:
            return stale["payload"], True
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
    shops, meta = _collect(latitude, longitude, radius_miles, limit)
    confirmed = [s for s in shops if s["truck_fit"] == "yes"]
    if len(confirmed) < min_confirmed and radius_miles < 100:
        try:
            wider, wider_meta = _collect(latitude, longitude, 100, limit)
        except (OverpassBusy, requests.RequestException):
            return shops[:limit], meta
        if len(wider) > len(shops):
            shops, meta = wider, wider_meta
    return shops[:limit], meta


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
                   "found": len(shops), "radius_miles": radius_miles}
