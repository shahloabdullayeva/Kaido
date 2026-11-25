import json
import time
from datetime import datetime, timezone

import requests

from .db import execute, one, rows
from .logs import get

log = get("weather")
ALERTS_URL = "https://api.weather.gov/alerts/active"
HEADERS = {"User-Agent": "Kaido fleet maintenance (kaidofleet.com)", "Accept": "application/geo+json"}
ZONE_DAYS = 30
EVENTS = {
    "Winter Storm Warning", "Winter Storm Watch", "Winter Weather Advisory", "Blizzard Warning", "Ice Storm Warning",
    "Lake Effect Snow Warning", "Snow Squall Warning", "Freezing Rain Advisory", "High Wind Warning", "High Wind Watch",
    "Wind Advisory", "Extreme Wind Warning", "Dust Storm Warning", "Blowing Dust Advisory", "Flood Warning", "Flood Watch",
    "Flash Flood Warning", "Flash Flood Watch", "Flood Advisory", "Dense Fog Advisory", "Freezing Fog Advisory",
    "Extreme Cold Warning", "Extreme Cold Watch", "Cold Weather Advisory", "Wind Chill Warning", "Wind Chill Advisory",
    "Hard Freeze Warning", "Tornado Warning", "Severe Thunderstorm Warning",
}
SEVERE = {"Blizzard Warning", "Ice Storm Warning", "Winter Storm Warning", "Extreme Wind Warning", "Flash Flood Warning",
          "Tornado Warning", "Snow Squall Warning", "Dust Storm Warning", "Extreme Cold Warning", "High Wind Warning"}


def bbox_of(geometry):
    xs, ys = [], []

    def walk(item):
        if isinstance(item[0], (int, float)):
            xs.append(item[0])
            ys.append(item[1])
        else:
            for sub in item:
                walk(sub)
    for polygon in polygons(geometry):
        walk(polygon)
    return [float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))] if xs else None


def polygons(geometry):
    if not geometry:
        return []
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"]]
    if geometry["type"] == "MultiPolygon":
        return geometry["coordinates"]
    if geometry["type"] == "GeometryCollection":
        return [p for g in geometry.get("geometries", []) for p in polygons(g)]
    return []


def in_ring(lon, lat, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def contains(geometry, lon, lat):
    for polygon in polygons(geometry):
        if polygon and in_ring(lon, lat, polygon[0]) and not any(in_ring(lon, lat, hole) for hole in polygon[1:]):
            return True
    return False


def zone(zone_url):
    zone_id = zone_url.rstrip("/").split("/")[-1]
    row = one("select * from weather_zones where zone_id = %s and fetched_at > now() - make_interval(days => %s)",
              (zone_id, ZONE_DAYS))
    if row:
        return row
    try:
        response = requests.get(zone_url, headers=HEADERS, timeout=20)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as err:
        log.warning("zone %s failed: %s", zone_id, err)
        return one("select * from weather_zones where zone_id = %s", (zone_id,))
    time.sleep(0.15)
    geometry = data.get("geometry")
    props = data.get("properties") or {}
    box = bbox_of(geometry) if geometry else None
    execute(
        """insert into weather_zones (zone_id, name, state, geometry, bbox, fetched_at) values (%s, %s, %s, %s, %s, now())
           on conflict (zone_id) do update set name = excluded.name, state = excluded.state, geometry = excluded.geometry,
             bbox = excluded.bbox, fetched_at = now()""",
        (zone_id, props.get("name"), props.get("state"), json.dumps(geometry) if geometry else None, box),
    )
    return one("select * from weather_zones where zone_id = %s", (zone_id,))


def merged(zone_rows):
    parts = []
    for row in zone_rows:
        if row and row["geometry"]:
            parts.extend(polygons(row["geometry"]))
    return {"type": "MultiPolygon", "coordinates": parts} if parts else None


def refresh():
    response = requests.get(ALERTS_URL, params={"status": "actual", "message_type": "alert,update"}, headers=HEADERS, timeout=30)
    response.raise_for_status()
    seen = []
    for feature in response.json().get("features") or []:
        props = feature.get("properties") or {}
        if props.get("event") not in EVENTS:
            continue
        geometry = feature.get("geometry")
        zones = props.get("affectedZones") or []
        zone_rows = [] if geometry else [zone(url) for url in zones[:120]]
        geometry = geometry or merged(zone_rows)
        if not geometry:
            continue
        states = sorted({(z["state"] or "") for z in zone_rows if z and z["state"]}) or sorted(
            {code[:2] for code in (props.get("geocode") or {}).get("UGC", [])})
        alert_id = props.get("id") or feature.get("id")
        execute(
            """insert into weather_alerts (id, event, severity, headline, description, instruction, area, states, onset, expires,
                 ends, zones, geometry, bbox, active, fetched_at)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true, now())
               on conflict (id) do update set headline = excluded.headline, description = excluded.description,
                 instruction = excluded.instruction, expires = excluded.expires, ends = excluded.ends, geometry = excluded.geometry,
                 bbox = excluded.bbox, active = true, fetched_at = now()""",
            (alert_id, props.get("event"), props.get("severity"), props.get("headline"), (props.get("description") or "")[:4000],
             (props.get("instruction") or "")[:2000], (props.get("areaDesc") or "")[:1000], states, props.get("onset"),
             props.get("expires"), props.get("ends"), [z.rstrip("/").split("/")[-1] for z in zones], json.dumps(geometry),
             bbox_of(geometry)),
        )
        seen.append(alert_id)
    execute("update weather_alerts set active = false where active and not (id = any(%s))", (seen,))
    execute("delete from weather_alerts where not active and fetched_at < now() - interval '3 days'")
    return match_trucks(), len(seen)


def match_trucks():
    alerts = rows("select id, geometry, bbox from weather_alerts where active and coalesce(ends, expires, now() + interval '1 day') > now()")
    trucks = rows("select id, company_id, latitude, longitude from trucks where latitude is not null and status <> 'sold'")
    hits = set()
    for alert in alerts:
        box = [float(v) for v in alert["bbox"]] if alert["bbox"] else None
        for truck in trucks:
            lon, lat = float(truck["longitude"]), float(truck["latitude"])
            if box and not (box[0] <= lon <= box[2] and box[1] <= lat <= box[3]):
                continue
            if contains(alert["geometry"], lon, lat):
                hits.add((truck["id"], alert["id"], truck["company_id"]))
    execute("delete from truck_weather where (truck_id, alert_id) not in (select * from unnest(%s::int[], %s::text[]))",
            ([h[0] for h in hits], [h[1] for h in hits]))
    for truck_id, alert_id, company_id in hits:
        execute("""insert into truck_weather (truck_id, alert_id, company_id) values (%s, %s, %s)
                   on conflict do nothing""", (truck_id, alert_id, company_id))
    return len(hits)


def short_area(alert, truck=None):
    states = alert.get("states") or []
    where = (truck or {}).get("location") or ""
    road = ""
    for part in where.split(","):
        part = part.strip()
        if part.startswith(("I-", "I ", "US-", "US ", "Interstate")):
            road = part.replace("Interstate ", "I-")
            break
    return ", ".join(p for p in [road, " ".join(states[:2])] if p)


def for_trucks(company_id):
    out = {}
    for row in rows(
        """select w.truck_id, a.*, t.location from truck_weather w join weather_alerts a on a.id = w.alert_id
           join trucks t on t.id = w.truck_id
           where w.company_id = %s and a.active order by a.event = any(%s) desc, a.expires""",
        (company_id, list(SEVERE)),
    ):
        out.setdefault(row["truck_id"], []).append({
            "event": row["event"], "area": short_area(row, row), "headline": row["headline"],
            "text": (row["description"] or "")[:1200], "instruction": (row["instruction"] or "")[:600],
            "expires": (row["ends"] or row["expires"]).isoformat() if (row["ends"] or row["expires"]) else None,
            "severe": row["event"] in SEVERE,
        })
    return out


def shapes(bounds=None):
    out = []
    for row in rows("""select id, event, headline, area, expires, ends, geometry from weather_alerts
                       where active and coalesce(ends, expires, now() + interval '1 day') > now()"""):
        out.append({"type": "Feature", "geometry": row["geometry"],
                    "properties": {"event": row["event"], "headline": row["headline"], "area": (row["area"] or "")[:300],
                                   "until": (row["ends"] or row["expires"]).isoformat() if (row["ends"] or row["expires"]) else None,
                                   "severe": row["event"] in SEVERE}})
    return {"type": "FeatureCollection", "features": out}
