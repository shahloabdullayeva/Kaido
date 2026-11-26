import re
import time

from . import fuel, sheets, shops
from .db import execute, insert, one, rows
from .logs import get

log = get("efs-network")

SAME_SPOT_MILES = 0.35
BRAND_CITY_MILES = 8
ADDRESS_MILES = 0.6
GENERIC = {"truck", "stop", "travel", "center", "plaza", "fuel", "inc", "llc", "the", "and", "of", "station", "shop",
           "store", "food", "mart", "gas", "diesel", "express", "auto", "service", "services", "co", "corp"}


def words(text):
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2 and w not in GENERIC}


def with_twins(stations):
    ids = set()
    for station in stations:
        ids.add(station["id"])
        located = station.get("located_by") or ""
        if located.startswith("osm:"):
            ids.add(int(located[4:]))
    return ids


def store_number(name):
    found = re.search(r"#\s*(\d+)|\b(\d{3,5})\b", name or "")
    return found and (found.group(1) or found.group(2))


def same_place(entry, station):
    brand = fuel.brand_of(entry["name"])
    if brand and station["brand"] == brand:
        mine, theirs = store_number(entry["name"]), store_number(station["name"])
        return not (mine and theirs and mine != theirs)
    return bool(words(entry["name"]) & words(station["name"]))


def quick_match(entry):
    if entry["latitude"] is not None:
        close = fuel.nearby_stations(entry["latitude"], entry["longitude"], SAME_SPOT_MILES)
        return with_twins(close[:3]) if close else set()
    if not entry["city"] or not entry["state"]:
        return set()
    found = rows(
        """select * from fuel_stations where upper(state) = %s and lower(city) = lower(%s) and latitude is not null""",
        (entry["state"], entry["city"]),
    )
    return with_twins([s for s in found if same_place(entry, s)])


def slow_match(entry):
    found = set()
    if entry["address"] and entry["city"] and entry["state"]:
        place = shops._nominatim_geocode(f"{entry['address']}, {entry['city']}, {entry['state']} {entry['zip'] or ''}")
        time.sleep(1)
        if place:
            close = fuel.nearby_stations(place["latitude"], place["longitude"], ADDRESS_MILES)
            found |= with_twins(close[:3])
            if found:
                execute("update efs_network set latitude = %s, longitude = %s where id = %s",
                        (place["latitude"], place["longitude"], entry["id"]))
    if not found and entry["city"] and entry["state"]:
        place = shops._nominatim_geocode(f"{entry['city']}, {entry['state']}")
        time.sleep(1)
        if place:
            near = fuel.nearby_stations(place["latitude"], place["longitude"], BRAND_CITY_MILES)
            found |= with_twins([s for s in near if same_place(entry, s)][:2])
    return found


def import_file(company_id, filename, data):
    headers, records = sheets.read(filename, data)
    pick = lambda *names: sheets.find(headers, *names)
    name_col = pick("location name", "truck stop name", "site name", "station name", "merchant name", "truck stop",
                    "location", "station", "merchant", "name")
    address_col = pick("address", "street address", "address 1", "address1", "street")
    city_col = pick("city", "location city")
    state_col = pick("state", "st", "state prov", "province")
    zip_col = pick("zip", "zip code", "postal code", "postal")
    lat_col = pick("latitude", "lat")
    lon_col = pick("longitude", "lon", "lng", "long")
    if not name_col or not ((city_col and state_col) or (lat_col and lon_col)):
        raise ValueError("The file needs a location name and either city and state or latitude and longitude columns. "
                         "Columns found: " + ", ".join(h for h in headers if h)[:300])
    entries = []
    for record in records:
        value = lambda col: sheets.value(record, col) if col else None
        name = str(value(name_col) or "").strip()
        if not name:
            continue
        lat, lon = fuel.number(value(lat_col)), fuel.number(value(lon_col))
        if lat is None or lon is None or not (15 < lat < 72 and -170 < lon < -50):
            lat = lon = None
        entries.append({
            "name": name[:160], "address": str(value(address_col) or "").strip()[:200] or None,
            "city": str(value(city_col) or "").strip().title()[:80] or None,
            "state": str(value(state_col) or "").strip().upper()[:2] or None,
            "zip": str(value(zip_col) or "").strip()[:10] or None, "latitude": lat, "longitude": lon,
        })
    if not entries:
        raise ValueError("No locations found in the file.")
    execute("delete from efs_network where company_id = %s", (company_id,))
    located = 0
    for entry in entries:
        ids = quick_match(entry)
        located += 1 if ids else 0
        insert(
            """insert into efs_network (company_id, name, address, city, state, zip, latitude, longitude, station_ids, checked_at)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, case when %s then now() end) returning id""",
            (company_id, entry["name"], entry["address"], entry["city"], entry["state"], entry["zip"],
             entry["latitude"], entry["longitude"], sorted(ids), bool(ids)),
        )
    return {"rows": len(entries), "located": located}


def match_rest(company_id=None, limit=5000):
    todo = rows(
        "select * from efs_network where checked_at is null" + (" and company_id = %s" if company_id else "")
        + " order by id limit %s",
        ((company_id, limit) if company_id else (limit,)),
    )
    located = 0
    for entry in todo:
        try:
            ids = quick_match(entry) or slow_match(entry)
        except Exception as err:
            log.warning("locating EFS row %s failed: %s", entry["id"], err)
            continue
        located += 1 if ids else 0
        execute("update efs_network set station_ids = %s, checked_at = now() where id = %s", (sorted(ids), entry["id"]))
    return {"checked": len(todo), "located": located}


def status(company_id):
    return one(
        """select count(*) as total, count(*) filter (where cardinality(station_ids) > 0) as located,
                  count(*) filter (where checked_at is null) as pending, max(uploaded_at) as uploaded_at
           from efs_network where company_id = %s""",
        (company_id,),
    )


def allowed_ids(company_id):
    listed = one("select array_agg(distinct s) as ids from efs_network, unnest(station_ids) s where company_id = %s",
                 (company_id,))
    used = rows(
        """select distinct s.id, s.located_by from fuel_transactions f join fuel_stations s on s.id = f.station_id
           where f.company_id = %s""",
        (company_id,),
    )
    return set(listed["ids"] or []) | with_twins(used)
