import json
import math
import re
import time
from datetime import datetime, timedelta, timezone

import requests

from . import shops
from .db import execute, insert, one, rows
from .logs import get

log = get("fuel")

EARTH_MILES = 3958.7613
ROAD_FACTOR = 1.18
PRICE_FRESH_DAYS = 7
PRICE_OLD_DAYS = 90
COMPARE_DAYS = 3
COMPARE_MILES = 30
ROUTE_MILES = 3
MIN_MISSED_PPU = 0.03
NEEDS = {
    "parking": "🅿️ truck parking",
    "showers": "🚿 showers",
    "scale": "⚖️ scale",
    "def": "💧 DEF at pump",
    "food": "🍔 food",
    "repair": "🔧 repair",
}

BRANDS = [
    ("Pilot", re.compile(r"\bpilot\b", re.I)),
    ("Flying J", re.compile(r"flying\s*j", re.I)),
    ("Love's", re.compile(r"\blove'?s\b", re.I)),
    ("TA", re.compile(r"^ta\b|\bta (express|travel|truck|petro)|travel ?centers? of america", re.I)),
    ("Petro", re.compile(r"\bpetro\b(?! ?(canada|leum|lium))", re.I)),
    ("Maverik", re.compile(r"maverik", re.I)),
    ("Casey's", re.compile(r"casey'?s", re.I)),
    ("Kwik Trip", re.compile(r"kwik (trip|star)", re.I)),
    ("Sapp Bros", re.compile(r"sapp bro", re.I)),
    ("Road Ranger", re.compile(r"road ?ranger", re.I)),
    ("Ambest", re.compile(r"\bambest\b", re.I)),
    ("Bosselman", re.compile(r"bosselman|boss shop", re.I)),
    ("Town Pump", re.compile(r"town pump", re.I)),
    ("Speedway", re.compile(r"speedway", re.I)),
    ("Sheetz", re.compile(r"sheetz", re.I)),
    ("Buc-ee's", re.compile(r"buc-?ee", re.I)),
    ("Roady's", re.compile(r"roady'?s", re.I)),
    ("Little America", re.compile(r"little america", re.I)),
    ("One9", re.compile(r"\bone ?9\b", re.I)),
    ("Iowa 80", re.compile(r"iowa 80", re.I)),
]
TRUCK_STOP_BRANDS = {"Pilot", "Flying J", "Love's", "TA", "Petro", "Sapp Bros", "Road Ranger", "Ambest",
                     "Bosselman", "Roady's", "Little America", "One9", "Iowa 80", "Town Pump", "Maverik"}
BRAND_TYPICAL = {
    "Pilot": {"parking": True, "showers": True, "scale": True, "def": True, "food": True},
    "Flying J": {"parking": True, "showers": True, "scale": True, "def": True, "food": True},
    "Love's": {"parking": True, "showers": True, "scale": True, "def": True, "food": True, "repair": True},
    "TA": {"parking": True, "showers": True, "scale": True, "def": True, "food": True, "repair": True},
    "Petro": {"parking": True, "showers": True, "scale": True, "def": True, "food": True, "repair": True},
    "Sapp Bros": {"parking": True, "showers": True, "scale": True, "def": True, "food": True},
    "Little America": {"parking": True, "showers": True, "def": True, "food": True},
    "Iowa 80": {"parking": True, "showers": True, "scale": True, "def": True, "food": True, "repair": True},
}
US_STATES = ["AL", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "ID", "IL", "IN", "IA", "KS", "KY", "LA",
             "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND",
             "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"]
DIRECTORY_QUERY = """[out:json][timeout:180];
area["ISO3166-2"="US-{state}"]->.s;
(
  nwr["amenity"="fuel"]["brand"~"{brands}",i](area.s);
  nwr["amenity"="fuel"]["name"~"{brands}",i](area.s);
  nwr["amenity"="fuel"]["hgv"="yes"](area.s);
  nwr["amenity"="fuel"]["fuel:HGV_diesel"="yes"](area.s);
);
out center tags;"""
DIRECTORY_BRANDS = ("Pilot|Flying J|Love's|TravelCenters|^TA |TA Express|Petro Stopping|Petro Travel|Maverik|Sapp Bros|"
                    "Road Ranger|AMBEST|Bosselman|Roady|Town Pump|Little America|Iowa 80|One9|Truck Stop|Travel Center|Travel Plaza")


def haversine(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = (math.radians(float(v)) for v in (lat1, lon1, lat2, lon2))
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_MILES * math.asin(math.sqrt(a))


def bearing(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = (math.radians(float(v)) for v in (lat1, lon1, lat2, lon2))
    x = math.sin(lon2 - lon1) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def angle_between(a, b):
    return abs((a - b + 180) % 360 - 180)


def brand_of(*texts):
    text = " ".join(t for t in texts if t)
    for name, pattern in BRANDS:
        if pattern.search(text):
            return name
    return None


def unit_label(unit):
    unit = " ".join((unit or "").split())
    first = unit.split(" ")[0] if unit else ""
    return first if any(ch.isdigit() for ch in first) else unit


def person(name):
    name = " ".join((name or "").split())
    return name.title() if name.isupper() or name.islower() else name


def clean(text):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())).strip()


def maps_link(station):
    if station.get("latitude") is None:
        query = ", ".join(p for p in [station.get("name"), station.get("city"), station.get("state")] if p)
        return "https://www.google.com/maps/search/?api=1&query=" + requests.utils.quote(query)
    return f"https://www.google.com/maps/dir/?api=1&destination={float(station['latitude']):.6f},{float(station['longitude']):.6f}"


def amenities_from_tags(tags, brand):
    found = dict(BRAND_TYPICAL.get(brand, {}))
    typical = set(found)
    if tags.get("hgv") == "yes" or tags.get("fuel:HGV_diesel") == "yes":
        found.setdefault("parking", None)
    if tags.get("shower") in ("yes", "hot") or tags.get("shower:hgv") == "yes":
        found["showers"] = True
    elif tags.get("shower") == "no":
        found["showers"] = False
    if tags.get("fuel:adblue") == "yes":
        found["def"] = True
    if tags.get("parking:hgv") == "no" or tags.get("hgv") == "no":
        found["parking"] = False
    elif tags.get("capacity:hgv") or tags.get("parking:hgv") == "yes":
        found["parking"] = True
    if tags.get("hgv") == "no":
        found["diesel_trucks"] = False
    found = {k: v for k, v in found.items() if v is not None}
    found["typical"] = sorted(typical & set(found))
    if tags.get("capacity:hgv"):
        found["spaces"] = tags["capacity:hgv"]
    if tags.get("opening_hours"):
        found["hours"] = tags["opening_hours"][:60]
    return found


def save_osm_station(element, state):
    tags = element.get("tags") or {}
    lat = element.get("lat") or (element.get("center") or {}).get("lat")
    lon = element.get("lon") or (element.get("center") or {}).get("lon")
    if lat is None or lon is None or tags.get("hgv") == "no":
        return None
    brand = brand_of(tags.get("brand"), tags.get("name"), tags.get("operator"))
    name = tags.get("name") or tags.get("brand") or "Fuel station"
    if tags.get("ref") and tags["ref"] not in name:
        name = f"{name} #{tags['ref']}"
    street = " ".join(p for p in [tags.get("addr:housenumber"), tags.get("addr:street")] if p) or None
    return insert(
        """insert into fuel_stations (key, osm_id, name, brand, latitude, longitude, address, city, state, amenities,
             located_by, source, updated_at)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'osm', 'osm', now())
           on conflict (key) do update set name = excluded.name, brand = excluded.brand, latitude = excluded.latitude,
             longitude = excluded.longitude, address = coalesce(excluded.address, fuel_stations.address),
             city = coalesce(excluded.city, fuel_stations.city), state = excluded.state,
             amenities = excluded.amenities, updated_at = now()
           returning id""",
        (f"osm:{element['type']}/{element['id']}", f"{element['type']}/{element['id']}", name[:120], brand,
         lat, lon, street, tags.get("addr:city"), (tags.get("addr:state") or state)[:2].upper(),
         json.dumps(amenities_from_tags(tags, brand))),
    )


def load_state(state, attempts=4):
    body = DIRECTORY_QUERY.replace("{state}", state).replace("{brands}", DIRECTORY_BRANDS)
    wait = 20
    for attempt in range(attempts):
        for url in shops.OVERPASS_URLS:
            try:
                response = requests.post(url, data={"data": body}, headers={"User-Agent": shops.USER_AGENT}, timeout=200)
                if response.status_code == 200:
                    elements = response.json().get("elements") or []
                    return sum(1 for e in elements if save_osm_station(e, state))
                log.info("overpass %s answered %s for %s", url, response.status_code, state)
            except (requests.RequestException, ValueError) as err:
                log.info("overpass %s failed for %s: %s", url, state, err)
            time.sleep(5)
        time.sleep(wait)
        wait *= 2
    return None


def load_directory(states=None, pause=8):
    done = {}
    for state in states or US_STATES:
        done[state] = load_state(state)
        print(f"{state}: {done[state] if done[state] is not None else 'failed'}", flush=True)
        time.sleep(pause)
    return done


def nearby_stations(latitude, longitude, miles):
    box_lat = miles / 69.0
    box_lon = miles / max(1.0, 69.0 * math.cos(math.radians(float(latitude))))
    found = rows(
        """select * from fuel_stations where latitude between %s and %s and longitude between %s and %s""",
        (float(latitude) - box_lat, float(latitude) + box_lat, float(longitude) - box_lon, float(longitude) + box_lon),
    )
    for station in found:
        station["miles"] = haversine(latitude, longitude, station["latitude"], station["longitude"])
    return sorted([s for s in found if s["miles"] <= miles], key=lambda s: s["miles"])


def raw_of(entry):
    raw = entry.get("raw")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = {}
    return raw or {}


def number(value):
    try:
        return float(str(value).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def split_price(entry):
    raw = raw_of(entry)
    gallons = float(entry["gallons"] or 0)
    net = round(float(entry["total"]) / gallons, 4) if gallons else None
    retail = number(raw.get("unit price") or raw.get("retail ppu") or raw.get("ppu"))
    discount_net = number(raw.get("disc ppu"))
    if discount_net and abs(discount_net - (net or 0)) < 0.05:
        net = discount_net
    if retail is None:
        return (float(entry["price_per_gallon"]) if entry.get("price_per_gallon") else net), net, None
    discount = round(retail - net, 4) if retail and net else None
    if discount is not None and discount < 0:
        discount = 0.0
    return retail, net, discount


def station_parts(entry):
    raw = raw_of(entry)
    name = raw.get("location name") or (entry.get("location") or "").split(",")[0]
    city = raw.get("city") or ((entry.get("location") or "").split(",")[1].strip() if "," in (entry.get("location") or "") else None)
    state = raw.get("state prov") or raw.get("state") or entry.get("state")
    return (name or "").strip(), (city or "").strip().title() or None, (state or "").strip().upper()[:2] or None


def locate_station(name, city, state):
    key = "tx:" + "|".join([clean(name), clean(city), clean(state)])
    existing = one("select * from fuel_stations where key = %s", (key,))
    brand = brand_of(name)
    if existing and existing["latitude"] is not None and not (brand and existing["located_by"] == "city"):
        return existing
    place = None
    if city and state:
        try:
            place = shops._nominatim_geocode(f"{city}, {state}")
        except requests.RequestException as err:
            log.info("geocode %s, %s failed: %s", city, state, err)
    if place and brand:
        twins = [s for s in nearby_stations(place["latitude"], place["longitude"], 20)
                 if s["brand"] == brand and s["source"] == "osm"]
        if twins:
            twin = twins[0]
            execute("update fuel_stations set city = coalesce(city, %s) where id = %s", (city, twin["id"]))
            execute(
                """insert into fuel_stations (key, name, brand, latitude, longitude, city, state, amenities, located_by, source)
                   values (%s, %s, %s, %s, %s, %s, %s, '{}', %s, 'transaction')
                   on conflict (key) do update set latitude = excluded.latitude, longitude = excluded.longitude,
                     located_by = excluded.located_by""",
                (key, name[:120], brand, twin["latitude"], twin["longitude"], city, state, f"osm:{twin['id']}"),
            )
            return twin
    located_by = "city" if place else None
    if place and not brand:
        try:
            exact = shops._nominatim_geocode(f"{name}, {city}, {state}")
        except requests.RequestException:
            exact = None
        if exact and haversine(exact["latitude"], exact["longitude"], place["latitude"], place["longitude"]) < 25:
            place, located_by = exact, "address"
    return insert(
        """insert into fuel_stations (key, name, brand, latitude, longitude, city, state, amenities, located_by, source)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'transaction')
           on conflict (key) do update set latitude = coalesce(excluded.latitude, fuel_stations.latitude),
             longitude = coalesce(excluded.longitude, fuel_stations.longitude),
             located_by = coalesce(excluded.located_by, fuel_stations.located_by), updated_at = now()
           returning *""",
        (key, name[:120] or "Fuel stop", brand, place["latitude"] if place else None,
         place["longitude"] if place else None, city, state, json.dumps(BRAND_TYPICAL.get(brand, {})), located_by),
    )


def resolve_station(station):
    if station and (station.get("located_by") or "").startswith("osm:"):
        twin = one("select * from fuel_stations where id = %s", (int(station["located_by"][4:]),))
        return twin or station
    return station


def enrich(company_id=None, limit=None):
    clause = " and company_id = %s" if company_id else ""
    todo = rows(
        f"""select * from fuel_transactions where (station_id is null or net_ppu is null
              or station_id in (select id from fuel_stations where located_by = 'city' and brand is not null
                                and updated_at < now() - interval '1 day')){clause}
            order by purchased_at desc""" + (f" limit {int(limit)}" if limit else ""),
        (company_id,) if company_id else (),
    )
    names = {}
    done = 0
    for entry in todo:
        retail, net, discount = split_price(entry)
        name, city, state = station_parts(entry)
        station = None
        if name:
            cache_key = (clean(name), clean(city), clean(state))
            if cache_key not in names:
                names[cache_key] = resolve_station(locate_station(name, city, state))
            station = names[cache_key]
        driver_id = entry["driver_id"] or match_driver(entry)
        execute(
            """update fuel_transactions set retail_ppu = %s, net_ppu = %s, discount_ppu = %s, station_id = %s,
                 driver_id = coalesce(driver_id, %s), checked_at = null where id = %s""",
            (retail, net, discount, station["id"] if station else None, driver_id, entry["id"]),
        )
        if station and net:
            execute(
                """insert into fuel_prices (company_id, station_id, fuel_type, retail_ppu, net_ppu, observed_at, source, transaction_id)
                   values (%s, %s, %s, %s, %s, %s, 'transaction', %s)
                   on conflict (company_id, station_id, fuel_type, observed_at, source) do nothing""",
                (entry["company_id"], station["id"], entry["fuel_type"], retail, net, entry["purchased_at"], entry["id"]),
            )
        done += 1
    return done


def match_driver(entry):
    raw_name = raw_of(entry).get("driver name")
    if not raw_name:
        return None
    words = set(re.findall(r"[a-z]+", raw_name.lower()))
    if not words:
        return None
    drivers = rows("select id, name from drivers where company_id = %s and status = 'active'", (entry["company_id"],))
    scored = []
    for driver in drivers:
        theirs = set(re.findall(r"[a-z]+", driver["name"].lower()))
        shared = words & theirs
        if len(shared) >= min(2, len(words)):
            scored.append((2, driver["id"]))
        elif shared and (theirs <= words or words <= theirs) and max(len(w) for w in shared) >= 4:
            scored.append((1, driver["id"]))
    for level in (2, 1):
        found = [driver_id for score, driver_id in scored if score == level]
        if len(found) == 1:
            return found[0]
        if found:
            truck = one("select driver_id from trucks where id = %s", (entry["truck_id"],))
            if truck and truck["driver_id"] in found:
                return truck["driver_id"]
            return None
    return None


def truck_mpg(truck_id, days=60):
    fills = rows(
        """select purchased_at, gallons from fuel_transactions
           where truck_id = %s and fuel_type = 'diesel' and purchased_at > now() - make_interval(days => %s)
           order by purchased_at""",
        (truck_id, days),
    )
    if len(fills) < 3:
        return None
    start, end = fills[0]["purchased_at"], fills[-1]["purchased_at"]
    readings = one(
        """select (select miles from odometer_readings where truck_id = %s and read_at <= %s order by read_at desc limit 1) as a,
                  (select miles from odometer_readings where truck_id = %s and read_at <= %s order by read_at desc limit 1) as b""",
        (truck_id, start, truck_id, end),
    )
    if not readings or not readings["a"] or not readings["b"]:
        return None
    miles = readings["b"] - readings["a"]
    gallons = sum(float(f["gallons"]) for f in fills[1:])
    if miles <= 200 or gallons <= 0:
        return None
    mpg = miles / gallons
    return round(mpg, 2) if 3.5 <= mpg <= 11 else None


def miles_between(truck_id, start, end):
    found = one(
        """select (select miles from odometer_readings where truck_id = %s and read_at <= %s order by read_at desc limit 1) as a,
                  (select miles from odometer_readings where truck_id = %s and read_at <= %s order by read_at desc limit 1) as b""",
        (truck_id, start, truck_id, end),
    )
    if not found or not found["a"] or not found["b"] or found["b"] < found["a"]:
        return None
    return found["b"] - found["a"]


def latest_prices(company_id, station_ids, at=None, before_days=PRICE_OLD_DAYS, after_days=0, fuel_type="diesel"):
    if not station_ids:
        return {}
    at = at or datetime.now(timezone.utc)
    found = rows(
        """select distinct on (station_id) station_id, retail_ppu, net_ppu, observed_at, source
           from fuel_prices
           where company_id = %s and fuel_type = %s and station_id = any(%s)
             and observed_at between %s and %s
           order by station_id, abs(extract(epoch from observed_at - %s)), observed_at desc""",
        (company_id, fuel_type, list(station_ids), at - timedelta(days=before_days), at + timedelta(days=after_days), at),
    )
    return {p["station_id"]: p for p in found}


def route_stations(truck_id, start, end):
    track = rows(
        "select latitude, longitude from truck_positions where truck_id = %s and recorded_at between %s and %s order by recorded_at",
        (truck_id, start, end),
    )
    if len(track) < 3:
        return None
    seen = {}
    for point in track[::max(1, len(track) // 40)]:
        for station in nearby_stations(point["latitude"], point["longitude"], ROUTE_MILES):
            seen.setdefault(station["id"], station)
    return list(seen.values())


def analyse(company_id=None, recheck=False):
    clause = " and f.company_id = %s" if company_id else ""
    params = (company_id,) if company_id else ()
    todo = rows(
        f"""select f.*, s.latitude, s.longitude from fuel_transactions f join fuel_stations s on s.id = f.station_id
            where f.fuel_type = 'diesel' and f.net_ppu is not null and s.latitude is not null
              {'' if recheck else 'and f.checked_at is null'}{clause}""",
        params,
    )
    checked = 0
    for entry in todo:
        when = entry["purchased_at"]
        candidates = route_stations(entry["truck_id"], when - timedelta(hours=10), when)
        if candidates is None:
            candidates = nearby_stations(entry["latitude"], entry["longitude"], COMPARE_MILES)
        else:
            for station in candidates:
                station["miles"] = haversine(entry["latitude"], entry["longitude"], station["latitude"], station["longitude"])
        ids = {s["id"] for s in candidates} - {entry["station_id"]}
        prices = latest_prices(entry["company_id"], ids, when, COMPARE_DAYS, COMPARE_DAYS)
        best = None
        for station in candidates:
            price = prices.get(station["id"])
            if price and (best is None or price["net_ppu"] < best[1]["net_ppu"]):
                best = (station, price)
        missed = None
        if best and float(entry["net_ppu"]) - float(best[1]["net_ppu"]) >= MIN_MISSED_PPU:
            missed = round((float(entry["net_ppu"]) - float(best[1]["net_ppu"])) * float(entry["gallons"]), 2)
        execute(
            """update fuel_transactions set best_station_id = %s, best_net_ppu = %s, best_miles = %s, missed_usd = %s,
                 checked_at = now() where id = %s""",
            (best[0]["id"] if missed else None, best[1]["net_ppu"] if missed else None,
             round(best[0]["miles"], 1) if missed else None, missed or 0, entry["id"]),
        )
        checked += 1
    return checked


def detect_refuels(company_id=None, hours=2):
    clause = " and t.company_id = %s" if company_id else ""
    trucks = rows(
        f"""select t.id, t.company_id from trucks t
            where t.fuel_percent is not null and t.fuel_percent_at > now() - interval '1 day'{clause}""",
        (company_id,) if company_id else (),
    )
    found = []
    for truck in trucks:
        track = rows(
            """select latitude, longitude, fuel_percent, recorded_at from truck_positions
               where truck_id = %s and fuel_percent is not null and recorded_at > now() - make_interval(hours => %s)
               order by recorded_at""",
            (truck["id"], hours),
        )
        for before, after in zip(track, track[1:]):
            if float(after["fuel_percent"]) - float(before["fuel_percent"]) >= 15:
                found.append({"truck_id": truck["id"], "company_id": truck["company_id"], "at": after["recorded_at"],
                              "latitude": after["latitude"], "longitude": after["longitude"],
                              "from": float(before["fuel_percent"]), "to": float(after["fuel_percent"])})
    return found


def import_price_file(company_id, filename, data):
    from . import sheets
    headers, records = sheets.read(filename, data)
    pick = lambda *names: sheets.find(headers, *names)
    name_col = pick("location name", "station name", "truck stop name", "site name", "truck stop", "location", "station",
                    "name", "merchant")
    city_col = pick("city", "location city")
    state_col = pick("state", "st", "state prov")
    retail_col = pick("retail price", "retail", "pump price", "retail ppu", "unit price")
    net_col = pick("your price", "net price", "net", "discounted price", "disc ppu", "cost plus price")
    discount_col = pick("discount", "savings", "disc", "discount amount")
    date_col = pick("date", "effective date", "price date")
    lat_col = pick("latitude", "lat")
    lon_col = pick("longitude", "lon", "lng")
    if not name_col or not (net_col or (retail_col and discount_col)):
        raise ValueError("The file needs a station name column and either a net price or retail + discount columns. "
                         "Columns found: " + ", ".join(h for h in headers if h)[:300])
    added = skipped = 0
    for record in records:
        value = lambda col: sheets.value(record, col) if col else None
        name = value(name_col)
        retail = number(value(retail_col))
        net = number(value(net_col))
        discount = number(value(discount_col))
        if net is None and retail is not None and discount is not None:
            net = round(retail - discount, 4)
        if not name or not net or not 1 < net < 15:
            skipped += 1
            continue
        city = str(value(city_col) or "").title() or None
        state = str(value(state_col) or "").upper()[:2] or None
        lat, lon = number(value(lat_col)), number(value(lon_col))
        twin = None
        if lat and lon:
            close = nearby_stations(lat, lon, 0.25)
            twin = close[0] if close else None
        if twin:
            station = resolve_station(twin)
        elif lat and lon:
            station = insert(
                """insert into fuel_stations (key, name, brand, latitude, longitude, city, state, located_by, source)
                   values (%s, %s, %s, %s, %s, %s, %s, 'file', 'transaction')
                   on conflict (key) do update set latitude = excluded.latitude, longitude = excluded.longitude
                   returning *""",
                ("tx:" + "|".join([clean(str(name)), clean(city), clean(state)]), str(name)[:120],
                 brand_of(str(name)), lat, lon, city, state),
            )
        else:
            station = resolve_station(locate_station(str(name), city, state))
        when = sheets.when(value(date_col)) if date_col else None
        execute(
            """insert into fuel_prices (company_id, station_id, fuel_type, retail_ppu, net_ppu, observed_at, source)
               values (%s, %s, 'diesel', %s, %s, coalesce(%s, now()), 'price_file')
               on conflict (company_id, station_id, fuel_type, observed_at, source) do update
                 set retail_ppu = excluded.retail_ppu, net_ppu = excluded.net_ppu""",
            (company_id, station["id"], retail, net, when),
        )
        added += 1
    return {"added": added, "skipped": skipped}
