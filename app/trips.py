import json
import math
import random
import re
from datetime import datetime, timedelta, timezone
from html import escape
from urllib.parse import quote

import requests

from . import brand_prices, fuel, shops
from .db import execute, insert, one, rows
from .logs import get
from .telegram import answer, call, edit, send

log = get("trips")

OSRM_URL = "https://router.project-osrm.org/route/v1/driving/"
TRUCK_SLOWER = 1.12
TRUCK_TOP_MPH = 65
CORRIDOR_MILES = 3
STEP_GALLONS = 10
STOP_PENALTY = 12.0
MIN_BUY_GALLONS = 50
FUEL_STOP_HOURS = 0.5
DOCK_HOURS = 2.0
DRIVE_LIMIT = 11.0
SHIFT_LIMIT = 14.0
BREAK_AFTER = 8.0
BREAK_HOURS = 0.5
REST_HOURS = 10.0
RESTART_HOURS = 34.0
CYCLE_LIMIT = 70.0
HOS_FRESH_HOURS = 12
AGE_PENALTY_PER_DAY = 0.004
FRESH_COMPANY_DAYS = 7
REST_LOOKBACK_MILES = 45
STOP_LINE = re.compile(r"^\s*(PU|PICK ?UP|SHIPPER|DEL|DELIVERY|DROP|CONSIGNEE|SO|STOP)\s*(\d*)\s*[:\-]\s*(.*)$", re.I)
WINDOW_LINE = re.compile(r"^\s*(FCFS|APPT|APPOINTMENT|WINDOW|OPEN|HOURS)\s*[:\-]?\s*(.+)$", re.I)
DATE = r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})"
TIME = r"(\d{1,2}:\d{2})"
SKIP_REASONS = [
    ("route", "Different route"),
    ("hours", "Not enough hours"),
    ("tank", "Tank info is wrong"),
    ("other", "Other, call me"),
]


def parse_date(text):
    if "-" in text:
        return datetime.strptime(text, "%Y-%m-%d").date()
    month, day, year = text.split("/")
    year = int(year) + (2000 if len(year) == 2 else 0)
    return datetime(year, int(month), int(day)).date()


def parse_window(text):
    dates = re.findall(DATE, text)
    times = re.findall(TIME, text)
    if not dates:
        return None, None
    first = parse_date(dates[0])
    last = parse_date(dates[1]) if len(dates) > 1 else first
    start = f"{first}T{times[0] if times else '00:00'}"
    end = f"{last}T{times[1] if len(times) > 1 else (times[0] if times else '23:59')}"
    return start, end


def parse_load(text):
    load = {"load_number": None, "rate": None, "stops": []}
    found = re.search(r"load\s*(?:id|#|number|no\.?)?\s*[:#]?\s*([A-Z0-9-]{4,})", text, re.I)
    if found:
        load["load_number"] = found.group(1)
    money = re.search(r"\$\s*([\d,]+(?:\.\d{2})?)", text)
    if money:
        load["rate"] = float(money.group(1).replace(",", ""))
    lines = [line.strip() for line in text.splitlines()]
    current = None
    for line in lines:
        if not line:
            continue
        head = STOP_LINE.match(line)
        if head:
            word = head.group(1).lower()
            kind = "pickup" if word.startswith(("pu", "pick", "ship")) else "delivery"
            current = {"kind": kind, "name": head.group(3).strip() or None, "address": None,
                       "window_type": None, "window_start": None, "window_end": None}
            load["stops"].append(current)
            continue
        if current is None:
            continue
        window = WINDOW_LINE.match(line)
        if window:
            current["window_type"] = window.group(1).upper()
            current["window_start"], current["window_end"] = parse_window(window.group(2))
            continue
        if current["address"] is None and re.search(r"\b[A-Z]{2}\s*\d{5}\b|\d", line) and "http" not in line:
            current["address"] = line
    return load


def geocode_address(address):
    tries = [address]
    stripped = re.sub(r"^\s*[\dA-Za-z-]*\d[\dA-Za-z-]*\s+", "", address)
    if stripped != address:
        tries.append(stripped)
    city = re.search(r"([A-Za-z .'-]+),\s*([A-Z]{2})\s*(\d{5})?", address)
    if city:
        tries.append(f"{city.group(1).strip()}, {city.group(2)} {city.group(3) or ''}".strip())
    for attempt in tries:
        try:
            place = shops._nominatim_geocode(attempt)
        except requests.RequestException as err:
            log.info("geocode %r failed: %s", attempt, err)
            place = None
        if place:
            place["exact"] = attempt == address
            return place
    return None


def truck_hours(leg):
    return max(leg["hours"] * TRUCK_SLOWER, leg["miles"] / TRUCK_TOP_MPH)


def osrm(points):
    path = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in points)
    response = requests.get(OSRM_URL + path, params={"overview": "full", "geometries": "geojson"},
                            headers={"User-Agent": shops.USER_AGENT}, timeout=40)
    response.raise_for_status()
    data = response.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        raise ValueError(f"No road route found ({data.get('code')})")
    route = data["routes"][0]
    coords = [(lat, lon) for lon, lat in route["geometry"]["coordinates"]]
    legs = [{"miles": leg["distance"] / 1609.344, "hours": leg["duration"] / 3600} for leg in route["legs"]]
    return coords, legs, route["distance"] / 1609.344


def thin(coords, spacing=0.5):
    kept = [coords[0]]
    miles = [0.0]
    total = 0.0
    last = coords[0]
    for point in coords[1:]:
        step = fuel.haversine(last[0], last[1], point[0], point[1])
        total += step
        last = point
        if total - miles[-1] >= spacing:
            kept.append(point)
            miles.append(total)
    if kept[-1] != coords[-1]:
        kept.append(coords[-1])
        miles.append(total)
    return kept, miles


def corridor(points, miles, width=CORRIDOR_MILES):
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    pad = width / 60.0
    candidates = rows(
        """select * from fuel_stations where latitude between %s and %s and longitude between %s and %s""",
        (min(lats) - pad, max(lats) + pad, min(lons) - pad, max(lons) + pad),
    )
    cell = 0.1
    grid = {}
    for index, (lat, lon) in enumerate(points):
        grid.setdefault((int(lat / cell), int(lon / cell)), []).append(index)
    found = []
    for station in candidates:
        if station["source"] == "transaction" and (station["located_by"] or "").startswith("osm:"):
            continue
        if station["located_by"] == "city":
            continue
        lat, lon = float(station["latitude"]), float(station["longitude"])
        key = (int(lat / cell), int(lon / cell))
        best = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for index in grid.get((key[0] + dx, key[1] + dy), []):
                    distance = fuel.haversine(lat, lon, points[index][0], points[index][1])
                    if best is None or distance < best[0]:
                        best = (distance, index)
        if best and best[0] <= width:
            station["off_route"] = round(best[0], 2)
            station["mile"] = round(miles[best[1]], 1)
            found.append(station)
    return sorted(found, key=lambda s: s["mile"])


def planning_prices(company_id, station_ids):
    if not station_ids:
        return {}
    now = datetime.now(timezone.utc)
    company = fuel.latest_prices(company_id, station_ids)
    website = brand_prices.website_prices(company_id, station_ids)
    chosen = {}
    for station_id in station_ids:
        own = company.get(station_id)
        site = website.get(station_id)
        own_age = (now - own["observed_at"]).days if own else None
        if own and own_age <= FRESH_COMPANY_DAYS:
            pick, age = own, own_age
        elif site:
            pick, age = site, 0
        elif own:
            pick, age = own, own_age
        else:
            continue
        net = float(pick["net_ppu"])
        chosen[station_id] = {
            "net": net, "retail": float(pick["retail_ppu"]) if pick.get("retail_ppu") else None,
            "source": pick["source"], "age_days": age,
            "estimated_discount": pick.get("estimated_discount"),
            "effective": net + AGE_PENALTY_PER_DAY * max(0, age - 1),
        }
    return chosen


def fuel_plan(stations, prices, distance, start_gallons, tank, mpg, reserve_gallons, end_price=0.0):
    steps = int(tank // STEP_GALLONS)
    usable = [s for s in stations if s["id"] in prices]
    nodes = [{"mile": 0.0, "off": 0.0, "price": None}]
    nodes += [{"mile": s["mile"], "off": s["off_route"], "price": prices[s["id"]]["effective"], "station": s} for s in usable]
    nodes.append({"mile": distance, "off": 0.0, "price": None, "end": True})
    reserve = math.ceil(reserve_gallons / STEP_GALLONS)
    start = min(steps, int(start_gallons // STEP_GALLONS))
    best = [dict() for _ in nodes]
    best[0][start] = (0.0, None)
    for i, node in enumerate(nodes):
        if not best[i] or node.get("end"):
            continue
        depart = {}
        for level, (cost, back) in best[i].items():
            if node["price"] is None:
                options = [(level, cost)]
            else:
                least = min(steps, level + MIN_BUY_GALLONS // STEP_GALLONS)
                options = [(level, cost)] + [
                    (target, cost + (target - level) * STEP_GALLONS * node["price"] + STOP_PENALTY)
                    for target in range(least, steps + 1) if target > level
                ]
            for target, total in options:
                if target not in depart or total < depart[target][0]:
                    depart[target] = (total, (level, target))
        for target, (total, choice) in depart.items():
            reach = (target - reserve) * STEP_GALLONS * mpg
            for j in range(i + 1, len(nodes)):
                ahead = nodes[j]
                need = ahead["mile"] - node["mile"] + node["off"] + ahead["off"]
                if need > reach:
                    break
                arrive = target - math.ceil(need / mpg / STEP_GALLONS)
                if arrive < reserve:
                    continue
                if arrive not in best[j] or total < best[j][arrive][0]:
                    best[j][arrive] = (total, (i, choice))
    last = len(nodes) - 1
    if not best[last]:
        return None
    level = min(best[last], key=lambda lv: (best[last][lv][0] - lv * STEP_GALLONS * end_price, -lv))
    stops = []
    arrive_level = level
    j = last
    while best[j][arrive_level][1] is not None:
        i, (before, after) = best[j][arrive_level][1]
        if after > before and nodes[i].get("station"):
            stops.append({"station": nodes[i]["station"], "arrive_gallons": before * STEP_GALLONS,
                          "buy": (after - before) * STEP_GALLONS, "depart_gallons": after * STEP_GALLONS})
        j, arrive_level = i, before
    stops.reverse()
    return {"stops": stops, "arrive_gallons": level * STEP_GALLONS}


END_PRICE_MILES = 120
EXPENSIVE_GAP = 0.25


def end_price(stations, prices, distance):
    near = [prices[s["id"]]["net"] for s in stations if s["id"] in prices and s["mile"] >= distance - END_PRICE_MILES]
    return min(near) if near else 0.0


def make_stop(item, price, tank, offset=0.0):
    station = item["station"]
    return {
        "station_id": station["id"], "name": station["name"], "brand": station["brand"], "city": station["city"],
        "state": station["state"], "latitude": float(station["latitude"]), "longitude": float(station["longitude"]),
        "mile": round(station["mile"] + offset, 1), "off_route": station["off_route"], "gallons": item["buy"],
        "arrive_percent": round(item["arrive_gallons"] / tank * 100), "depart_percent": round(item["depart_gallons"] / tank * 100),
        "price": price["net"], "retail": price["retail"], "source": price["source"], "age_days": price["age_days"],
        "estimated_discount": price["estimated_discount"], "cost": round(item["buy"] * price["net"], 2), "eta": item.get("eta"),
        "amenities": station["amenities"] or {},
    }


def explain_fill_ups(fuel_stops, stations, prices, offset=0.0):
    for index, stop in enumerate(fuel_stops):
        if stop["depart_percent"] < 90:
            continue
        until = fuel_stops[index + 1]["mile"] if index + 1 < len(fuel_stops) else None
        ahead = {}
        for station in stations:
            mile = station["mile"] + offset
            if station["id"] in prices and mile > stop["mile"] and (until is None or mile < until + 300):
                ahead.setdefault(station["state"] or "?", []).append(prices[station["id"]]["net"])
        need = 1 if until is None else 2
        dear = [(sum(v) / len(v), state) for state, v in ahead.items() if state != stop["state"] and len(v) >= need]
        if not dear:
            continue
        average, state = max(dear)
        if average - stop["price"] >= EXPENSIVE_GAP:
            stop["fill_reason"] = f"Fill the tank here: diesel ahead in {state} averages ${average:.2f}, ${average - stop['price']:.2f}/gal more."


class Clock:
    def __init__(self, when, hos):
        self.when = when
        self.drive = hos.get("drive", DRIVE_LIMIT)
        self.shift = hos.get("shift", SHIFT_LIMIT)
        self.since_break = BREAK_AFTER - hos.get("break", BREAK_AFTER)
        self.cycle = hos.get("cycle", CYCLE_LIMIT)
        self.rests = []

    def rest(self, kind, hours, mile):
        start = self.when
        self.when += timedelta(hours=hours)
        self.rests.append({"kind": kind, "mile": round(mile, 1), "start": start.isoformat(), "end": self.when.isoformat(),
                           "hours": hours})
        if kind == "break":
            self.since_break = 0.0
        elif kind == "rest":
            self.drive, self.shift, self.since_break = DRIVE_LIMIT, SHIFT_LIMIT, 0.0
        else:
            self.drive, self.shift, self.since_break, self.cycle = DRIVE_LIMIT, SHIFT_LIMIT, 0.0, CYCLE_LIMIT

    def drive_to(self, miles, speed, mile_at):
        left = miles
        while left > 0.01:
            if self.cycle <= 0.01:
                self.rest("restart", RESTART_HOURS, mile_at(miles - left))
                continue
            if self.drive <= 0.01 or self.shift <= 0.01:
                self.rest("rest", REST_HOURS, mile_at(miles - left))
                continue
            if self.since_break >= BREAK_AFTER - 0.01:
                self.rest("break", BREAK_HOURS, mile_at(miles - left))
                continue
            hours = min(left / speed, self.drive, self.shift, BREAK_AFTER - self.since_break, self.cycle)
            self.when += timedelta(hours=hours)
            self.drive -= hours
            self.shift -= hours
            self.cycle -= hours
            self.since_break += hours
            left -= hours * speed

    def work(self, hours, mile):
        if self.shift < hours or self.cycle < hours:
            self.rest("rest" if self.cycle >= hours else "restart", REST_HOURS if self.cycle >= hours else RESTART_HOURS, mile)
        self.when += timedelta(hours=hours)
        self.shift -= hours
        self.cycle -= hours
        if hours >= BREAK_HOURS:
            self.since_break = 0.0

    def wait_until(self, moment, mile):
        if moment <= self.when:
            return 0.0
        gap = (moment - self.when).total_seconds() / 3600
        if gap >= REST_HOURS:
            self.rest("rest", gap, mile)
        else:
            self.when = moment
            self.shift -= gap
            if gap >= BREAK_HOURS:
                self.since_break = 0.0
        return gap


def local(moment, longitude):
    return moment.astimezone(shops.zone_for(float(longitude)))


def window_moment(text, longitude):
    if not text:
        return None
    return datetime.fromisoformat(text).replace(tzinfo=shops.zone_for(float(longitude)))


def hos_for(truck):
    if not truck.get("driver_id"):
        return {}, None
    found = one(
        """select * from hos_status where driver_id = %s and updated_at > now() - make_interval(hours => %s)
           order by updated_at desc limit 1""",
        (truck["driver_id"], HOS_FRESH_HOURS),
    )
    if not found:
        return {}, None
    hours = lambda value: max(0.0, float(value) / 3600000) if value is not None else None
    clocks = {"drive": hours(found["drive_remaining"]), "shift": hours(found["shift_remaining"]),
              "cycle": hours(found["cycle_remaining"]), "break": hours(found["break_remaining"])}
    return {k: v for k, v in clocks.items() if v is not None}, found["duty_status"]


def point_at(points, miles, mile):
    return points[min(len(points) - 1, _bisect(miles, mile))]


def _bisect(miles, mile):
    low, high = 0, len(miles) - 1
    while low < high:
        middle = (low + high) // 2
        if miles[middle] < mile:
            low = middle + 1
        else:
            high = middle
    return low


def rest_spot(stations, mile):
    near = [s for s in stations if mile - REST_LOOKBACK_MILES <= s["mile"] <= mile + 10
            and (s["amenities"] or {}).get("parking")]
    if not near:
        near = [s for s in stations if mile - REST_LOOKBACK_MILES * 1.5 <= s["mile"] <= mile + 15
                and (s["brand"] in fuel.TRUCK_STOP_BRANDS or (s["amenities"] or {}).get("parking"))]
    if not near:
        return None
    spot = max(near, key=lambda s: (s["mile"] <= mile, int((s["amenities"] or {}).get("spaces") or 0) > 20, s["mile"]))
    return {"name": spot["name"], "brand": spot["brand"], "city": spot["city"], "state": spot["state"],
            "mile": spot["mile"], "latitude": float(spot["latitude"]), "longitude": float(spot["longitude"]),
            "spaces": (spot["amenities"] or {}).get("spaces")}


def build(company_id, truck, load, user_id=None, text=None):
    company = one("select * from companies where id = %s", (company_id,))
    if truck["latitude"] is None:
        raise ValueError("Kaido has no position for this truck yet.")
    if not load["stops"]:
        raise ValueError("No pickup or delivery found in the load text.")
    for stop in load["stops"]:
        place = geocode_address(stop["address"] or stop["name"] or "")
        if not place:
            raise ValueError(f"Could not find {stop['address'] or stop['name']} on the map.")
        stop["latitude"], stop["longitude"], stop["located_exactly"] = place["latitude"], place["longitude"], place["exact"]
    start = (float(truck["latitude"]), float(truck["longitude"]))
    coords, legs, total = osrm([start] + [(s["latitude"], s["longitude"]) for s in load["stops"]])
    points, miles = thin(coords)
    scale = total / miles[-1] if miles[-1] else 1
    miles = [m * scale for m in miles]
    leg_ends = []
    running = 0.0
    for leg in legs:
        running += leg["miles"]
        leg_ends.append(running)
    stations = corridor(points, miles)
    prices = planning_prices(company_id, [s["id"] for s in stations])
    tank = int(truck["tank_gallons"] or 200)
    mpg = fuel.truck_mpg(truck["id"]) or float(company["fuel_default_mpg"] or 6.5)
    percent = float(truck["fuel_percent"]) if truck.get("fuel_percent") is not None else 50.0
    reserve = tank * max(10, int(company["fuel_reserve_percent"] or 10)) / 100
    plan = fuel_plan(stations, prices, total, tank * percent / 100, tank, mpg, reserve, end_price(stations, prices, total))
    if plan is None:
        plan = {"stops": [], "arrive_gallons": None, "impossible": True}
    hos, duty = hos_for(truck)
    clock = Clock(datetime.now(timezone.utc), hos)
    mile_at = lambda base: (lambda done: base + done)
    events = [{"mile": s["station"]["mile"], "kind": "fuel", "ref": s} for s in plan["stops"]]
    events += [{"mile": leg_ends[i], "kind": stop["kind"], "ref": stop} for i, stop in enumerate(load["stops"])]
    events.sort(key=lambda e: (e["mile"], e["kind"] != "fuel"))
    position = 0.0
    leg_index = 0
    for event in events:
        while leg_index < len(legs) - 1 and position >= leg_ends[leg_index] - 0.01:
            leg_index += 1
        leg = legs[leg_index]
        speed = leg["miles"] / max(0.1, truck_hours(leg))
        clock.drive_to(event["mile"] - position, speed, mile_at(position))
        position = event["mile"]
        if event["kind"] == "fuel":
            event["ref"]["eta"] = clock.when.isoformat()
            clock.work(FUEL_STOP_HOURS, position)
            continue
        stop = event["ref"]
        stop["eta"] = clock.when.isoformat()
        opens = window_moment(stop["window_start"], stop["longitude"])
        closes = window_moment(stop["window_end"], stop["longitude"])
        stop["wait_hours"] = round(clock.wait_until(opens, position), 2) if opens else 0.0
        stop["arrive"] = clock.when.isoformat()
        stop["late_hours"] = round((clock.when - closes).total_seconds() / 3600, 1) if closes and clock.when > closes else 0.0
        clock.work(DOCK_HOURS, position)
        stop["depart"] = clock.when.isoformat()
    for rest in clock.rests:
        if rest["kind"] in ("rest", "restart"):
            rest["spot"] = rest_spot(stations, rest["mile"])
        lat, lon = point_at(points, miles, rest["mile"])
        rest["latitude"], rest["longitude"] = lat, lon
    fuel_stops = [make_stop(item, prices[item["station"]["id"]], tank) for item in plan["stops"]]
    explain_fill_ups(fuel_stops, stations, prices)
    bought = sum(stop["gallons"] for stop in fuel_stops)
    cost = sum(stop["cost"] for stop in fuel_stops)
    priced = [prices[s["id"]]["net"] for s in stations if s["id"] in prices]
    average = sum(priced) / len(priced) if priced else None
    baseline = round(bought * average, 2) if average else None
    finish = datetime.fromisoformat(load["stops"][-1]["depart"]) if load["stops"][-1].get("depart") else clock.when
    summary = {
        "miles": round(total, 1), "empty_miles": round(leg_ends[0], 1) if load["stops"][0]["kind"] == "pickup" else 0.0,
        "drive_hours": round(sum(truck_hours(leg) for leg in legs), 1),
        "trip_hours": round((finish - datetime.now(timezone.utc)).total_seconds() / 3600, 1),
        "gallons": bought, "fuel_cost": round(cost, 2), "average_price": round(average, 3) if average else None,
        "baseline_cost": baseline, "savings": round(baseline - cost, 2) if baseline else None,
        "burn_gallons": round(total / mpg), "arrive_percent": round(plan["arrive_gallons"] / tank * 100) if plan.get("arrive_gallons") is not None else None,
        "stations_on_route": len(stations), "priced_on_route": len(priced), "hos_known": bool(hos), "duty_status": duty,
        "impossible": plan.get("impossible", False), "hos": hos,
        "fuel_reading_at": truck["fuel_percent_at"].isoformat() if truck.get("fuel_percent_at") else None,
        "fuel_known": truck.get("fuel_percent") is not None,
        "restart_needed": any(r["kind"] == "restart" for r in clock.rests),
        "late": any(s.get("late_hours") for s in load["stops"]),
    }
    if load.get("rate"):
        summary["rate_per_mile"] = round(load["rate"] / total, 2)
        loaded = total - summary["empty_miles"]
        summary["rate_per_loaded_mile"] = round(load["rate"] / loaded, 2) if loaded else None
        summary["after_fuel"] = round(load["rate"] - summary["burn_gallons"] * (average or 0), 2) if average else None
    every = max(1, len(points) // 1500)
    route = {"points": [[round(lat, 5), round(lon, 5)] for lat, lon in points[::every]],
             "miles": [round(m, 2) for m in miles[::every]], "leg_ends": [round(m, 1) for m in leg_ends]}
    trip = insert(
        """insert into trips (company_id, truck_id, driver_id, load_number, rate, source_text, stops, route, distance_miles,
             empty_miles, drive_hours, start_latitude, start_longitude, start_fuel_percent, tank_gallons, mpg, plan, created_by)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning *""",
        (company_id, truck["id"], truck.get("driver_id"), load.get("load_number"), load.get("rate"), text,
         json.dumps(load["stops"]), json.dumps(route), summary["miles"], summary["empty_miles"], summary["drive_hours"],
         start[0], start[1], percent, tank, mpg,
         json.dumps({"fuel_stops": fuel_stops, "rests": clock.rests, "summary": summary}), user_id),
    )
    return trip


def place_name(item):
    where = ", ".join(p for p in [item.get("city"), item.get("state")] if p)
    return f"{item['name']}" + (f", {where}" if where else "")


def when_text(iso, longitude):
    if not iso:
        return "?"
    moment = local(datetime.fromisoformat(iso), longitude)
    return moment.strftime("%a %b %d %H:%M ") + (moment.tzname() or "")


def maps_route(trip):
    plan = trip["plan"]
    stops = trip["stops"]
    origin = f"{float(trip['start_latitude']):.5f},{float(trip['start_longitude']):.5f}"
    destination = f"{stops[-1]['latitude']:.5f},{stops[-1]['longitude']:.5f}"
    marks = sorted([(s["mile"], f"{s['latitude']:.5f},{s['longitude']:.5f}") for s in plan["fuel_stops"]]
                   + [(m, f"{s['latitude']:.5f},{s['longitude']:.5f}") for m, s in zip(trip["route"]["leg_ends"], stops[:-1])])
    waypoints = "|".join(mark for _, mark in marks[:9])
    url = f"https://www.google.com/maps/dir/?api=1&origin={origin}&destination={destination}&travelmode=driving"
    return url + (f"&waypoints={quote(waypoints, safe=',|')}" if waypoints else "")


def message(trip, truck):
    plan = trip["plan"]
    summary = plan["summary"]
    stops = trip["stops"]
    first, last = stops[0], stops[-1]
    lines = [f"<b>Trip plan{' — Load ' + escape(trip['load_number']) if trip['load_number'] else ''}</b>",
             f"Unit {escape(fuel.unit_label(truck['unit_number']))}" + (f" · {escape(fuel.person(truck['driver_name']))}" if truck.get("driver_name") else ""),
             f"{escape(first.get('address') or first.get('name') or '')} to {escape(last.get('address') or last.get('name') or '')}",
             f"{summary['miles']:,.0f} mi ({summary['empty_miles']:,.0f} mi to pickup) · about {summary['drive_hours']:.0f} h driving",
             tank_line(trip, summary)]
    if trip.get("rate"):
        lines.append(f"Rate ${float(trip['rate']):,.0f} · ${summary.get('rate_per_mile', 0):.2f}/mi all miles")
    hos = summary.get("hos") or {}
    if hos:
        lines.append("Hours now (Horizon): " + ", ".join(
            f"{label} {hos[key]:.1f} h" for key, label in (("drive", "drive"), ("shift", "shift"), ("cycle", "70-hour cycle")) if key in hos))
    if summary.get("restart_needed"):
        lines.append("<b>A 34-hour restart is needed on this trip: the 70-hour cycle runs out on the way.</b>")
    if summary.get("late"):
        lines.append("<b>With these hours the load arrives late. Call the office before you accept.</b>")
    lines.append("")
    for stop in stops:
        label = "Pickup" if stop["kind"] == "pickup" else "Delivery"
        window = ""
        if stop.get("window_start"):
            opens = datetime.fromisoformat(stop["window_start"])
            closes = datetime.fromisoformat(stop["window_end"])
            window = f" ({stop.get('window_type') or 'window'} {opens:%b %d %H:%M} to {closes:%b %d %H:%M})"
        lines.append(f"<b>{label}:</b> {escape(stop.get('name') or '')}{window}")
        state = "on time" if not stop.get("late_hours") else f"LATE by about {stop['late_hours']:.0f} h"
        lines.append(f"   ETA {when_text(stop.get('eta'), stop['longitude'])}, {state}"
                     + (f", wait {stop['wait_hours']:.1f} h for the window" if stop.get("wait_hours") else ""))
    lines.append("")
    if summary.get("impossible"):
        lines.append("<b>Fuel:</b> no safe fuel plan with the prices Kaido knows on this route. Fuel at the first big truck stop and call the office.")
    elif not plan["fuel_stops"]:
        lines.append("<b>Fuel:</b> no stop needed, the tank covers the whole trip.")
    else:
        lines += stop_lines(plan["fuel_stops"][0], "First fuel stop")
        lines.append("Kaido sends the next stop when you get close to it or the tank gets low. One stop at a time.")
    rest = next((r for r in plan["rests"] if r["kind"] in ("rest", "restart")), None)
    if rest:
        lines += [""] + rest_lines(rest, summary.get("hos_known"))
    lines += ["", f"<a href=\"{maps_route(trip)}\">Open the route in Google Maps</a>"]
    return "\n".join(lines)


def tank_line(trip, summary):
    percent = float(trip["start_fuel_percent"])
    gallons = percent / 100 * int(trip["tank_gallons"])
    line = (f"Tank {percent:.0f}% of {trip['tank_gallons']} gal: about {gallons:,.0f} gal, {gallons * float(trip['mpg']):,.0f} mi "
            f"at {float(trip['mpg']):.1f} mpg")
    if not summary.get("fuel_known", True):
        return line + " (Samsara has no tank reading for this truck, 50% assumed)"
    if summary.get("fuel_reading_at"):
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(summary["fuel_reading_at"])).total_seconds() / 3600
        if age >= 2:
            line += f" (tank reading {age:.0f} h old)"
    return line


def stop_lines(stop, title):
    price = f"${stop['price']:.3f}" + (" est." if stop["source"] == "website" else "")
    lines = [f"<b>{title}:</b> {escape(place_name(stop))}, mile {stop['mile']:,.0f}",
             f"   Buy {stop['gallons']:.0f} gal at {price}" + (f" (pump ${stop['retail']:.3f})" if stop.get("retail") and stop["retail"] - stop["price"] > 0.005 else ""),
             f"   Get there about {when_text(stop.get('eta'), stop['longitude'])} with about {stop['arrive_percent']}% in the tank"]
    if stop.get("fill_reason"):
        lines.append(f"   <b>{escape(stop['fill_reason'])}</b>")
    extras = amenity_text(stop.get("amenities") or {})
    lines.append(f"   {extras + ' · ' if extras else ''}<a href=\"{fuel.maps_link(stop)}\">Map</a>")
    return lines


def amenity_text(amenities):
    words = []
    if amenities.get("parking"):
        words.append(f"parking ({amenities['spaces']} spots)" if amenities.get("spaces") else "parking")
    for key, word in (("showers", "showers"), ("scale", "scale"), ("def", "DEF"), ("food", "food"), ("repair", "repair")):
        if amenities.get(key):
            words.append(word)
    return ", ".join(words)


def rest_lines(rest, hos_known):
    spot = rest.get("spot")
    where = f" at {escape(place_name(spot))}" + (f", {spot['spaces']} spots" if spot and spot.get("spaces") else "") if spot else ""
    hours = "34 h restart" if rest["kind"] == "restart" else f"{rest['hours']:.0f} h rest"
    return [f"<b>Next rest:</b> {hours} around mile {rest['mile']:,.0f}{where}, from {when_text(rest['start'], rest['longitude'])}"
            + ("" if hos_known else " (driver hours not known, assumed a fresh 11/14)")]


def keyboard(trip_id):
    return {"inline_keyboard": [[{"text": "Accept plan", "callback_data": f"ta:{trip_id}"},
                                 {"text": "Problem with plan", "callback_data": f"tp:{trip_id}"}]]}


LIVE_MINUTES = 60


def random_active_truck(company_id):
    live = live_trucks(company_id)
    return random.choice(live) if live else None


def nearest_active_truck(company_id, load):
    first = load["stops"][0] if load.get("stops") else None
    place = geocode_address(first["address"] or first["name"] or "") if first else None
    live = live_trucks(company_id)
    if not place or not live:
        return None
    return min(live, key=lambda t: fuel.haversine(place["latitude"], place["longitude"], t["latitude"], t["longitude"]))


def live_trucks(company_id):
    from .fuel_bot import TRUCK_SQL
    return rows(
        TRUCK_SQL + """ where t.company_id = %s and t.status = 'active' and t.driver_id is not null
                         and t.location_source = 'samsara' and t.latitude is not null
                         and t.located_at > now() - make_interval(mins => %s)
                         and t.fuel_percent is not null and t.fuel_percent_at > now() - make_interval(mins => %s)""",
        (company_id, LIVE_MINUTES, LIVE_MINUTES),
    )


def load_truck(truck_id):
    from .fuel_bot import TRUCK_SQL
    return one(TRUCK_SQL + " where t.id = %s", (truck_id,))


def send_to_driver(trip_id):
    trip = one("select * from trips where id = %s", (trip_id,))
    truck = load_truck(trip["truck_id"])
    if not truck or not truck["telegram_chat_id"]:
        return {"ok": False, "reason": "This truck has no Telegram group connected."}
    result = send(truck["telegram_chat_id"], message(trip, truck), reply_markup=keyboard(trip_id))
    if result.get("ok"):
        execute("""update trips set status = 'sent', chat_id = %s, message_id = %s, sent_at = now(), updated_at = now()
                   where id = %s""", (truck["telegram_chat_id"], result.get("message_id"), trip_id))
        stops = one("select plan from trips where id = %s", (trip_id,))["plan"]["fuel_stops"]
        if stops:
            first = stops[0]
            call("sendVenue", {"chat_id": truck["telegram_chat_id"], "latitude": first["latitude"], "longitude": first["longitude"],
                               "title": f"Fuel stop 1: {first['name']}"[:60],
                               "address": f"Mile {first['mile']:,.0f}, buy {first['gallons']:.0f} gal",
                               "reply_to_message_id": result.get("message_id")})
    return result


def handle_callback(query):
    data = query.get("data") or ""
    message_info = query.get("message") or {}
    chat_id = (message_info.get("chat") or {}).get("id")
    message_id = message_info.get("message_id")
    parts = data.split(":")
    try:
        trip_id = int(parts[1])
    except (IndexError, ValueError):
        answer(query["id"])
        return True
    trip = one("select * from trips where id = %s", (trip_id,))
    if not trip or trip["chat_id"] != chat_id:
        answer(query["id"], "This plan is no longer active.")
        return True
    truck = load_truck(trip["truck_id"])
    user = query.get("from") or {}
    who = escape(user.get("first_name") or user.get("username") or "Driver")
    if parts[0] in ("tf", "ts"):
        return stop_callback(query, parts, trip, truck, chat_id, message_id, who)
    if parts[0] == "ta":
        execute("update trips set status = 'accepted', answered_at = now(), updated_at = now() where id = %s", (trip_id,))
        edit(chat_id, message_id, message(trip, truck) + f"\n\n<b>Accepted by {who}.</b>")
        answer(query["id"], "Plan accepted. Drive safe.")
        notify_office(trip, truck, f"accepted by {who}")
        return True
    if parts[0] == "tp":
        buttons = [[{"text": text, "callback_data": f"tr:{trip_id}:{code}"}] for code, text in SKIP_REASONS]
        buttons.append([{"text": "Back", "callback_data": f"tb:{trip_id}"}])
        call("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": buttons}})
        answer(query["id"], "What is wrong with the plan?")
        return True
    if parts[0] == "tb":
        call("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": message_id, "reply_markup": keyboard(trip_id)})
        answer(query["id"])
        return True
    if parts[0] == "tr":
        reason = dict(SKIP_REASONS).get(parts[2] if len(parts) > 2 else "", "Other")
        execute("update trips set status = 'declined', answer_note = %s, answered_at = now(), updated_at = now() where id = %s",
                (reason, trip_id))
        edit(chat_id, message_id, message(trip, truck) + f"\n\n<b>{who}: {escape(reason)}.</b> The office has been told.")
        answer(query["id"], "Sent to the office.")
        notify_office(trip, truck, f"has a problem: {reason} ({who})")
        return True
    answer(query["id"])
    return True


def notify_office(trip, truck, what):
    text = (f"<b>Trip plan{' — Load ' + escape(trip['load_number']) if trip['load_number'] else ''}</b>\n"
            f"Unit {escape(fuel.unit_label(truck['unit_number']))} {escape(what)}.")
    for user in rows(
        """select distinct u.telegram_chat_id from users u join memberships m on m.user_id = u.id
           where m.company_id = %s and m.role = 'admin' and u.telegram_chat_id is not null and u.status = 'active'""",
        (trip["company_id"],),
    ):
        send(user["telegram_chat_id"], text)


NEXT_STOP_MILES = 80
PASSED_MILES = 8
OFF_ROUTE_MILES = 15
FOLLOW_DAYS = 8
FRESH_POSITION_MINUTES = 60
REFUEL_JUMP = 15


def route_of(trip):
    route = trip["route"]
    points = [tuple(p) for p in route["points"]]
    miles = route.get("miles")
    if not miles:
        miles = [0.0]
        for a, b in zip(points, points[1:]):
            miles.append(miles[-1] + fuel.haversine(a[0], a[1], b[0], b[1]))
        scale = float(trip["distance_miles"]) / miles[-1] if miles[-1] else 1
        miles = [m * scale for m in miles]
    return points, miles


def locate(points, miles, latitude, longitude):
    best = min(range(len(points)), key=lambda i: fuel.haversine(latitude, longitude, points[i][0], points[i][1]))
    return miles[best], fuel.haversine(latitude, longitude, points[best][0], points[best][1])


def live_state(trip):
    state = trip["plan"].setdefault("live", {})
    state.setdefault("current", 0)
    state.setdefault("sent", {})
    state.setdefault("skipped", [])
    state.setdefault("replans", 0)
    return state


def save_plan(trip):
    execute("update trips set plan = %s, updated_at = now() where id = %s", (json.dumps(trip["plan"], default=str), trip["id"]))


def average_speed(trip):
    hours = float(trip["drive_hours"] or 0)
    return float(trip["distance_miles"]) / hours if hours else 50.0


def replan(trip, truck, mile, avoid=()):
    points, miles = route_of(trip)
    start = min(len(points) - 2, _bisect(miles, mile))
    ahead_points = points[start:]
    ahead_miles = [m - miles[start] for m in miles[start:]]
    stations = [s for s in corridor(ahead_points, ahead_miles) if s["id"] not in set(avoid)]
    prices = planning_prices(trip["company_id"], [s["id"] for s in stations])
    tank = int(trip["tank_gallons"])
    mpg = float(trip["mpg"])
    company = one("select fuel_reserve_percent from companies where id = %s", (trip["company_id"],))
    reserve = tank * max(10, int(company["fuel_reserve_percent"] or 10)) / 100
    percent = float(truck["fuel_percent"]) if truck.get("fuel_percent") is not None else 30.0
    remaining = float(trip["distance_miles"]) - miles[start]
    plan = fuel_plan(stations, prices, remaining, tank * percent / 100, tank, mpg, reserve, end_price(stations, prices, remaining))
    speed = average_speed(trip)
    now = datetime.now(timezone.utc)
    fresh = []
    for item in (plan or {}).get("stops", []):
        item["eta"] = (now + timedelta(hours=item["station"]["mile"] / speed)).isoformat()
        fresh.append(make_stop(item, prices[item["station"]["id"]], tank, miles[start]))
    explain_fill_ups(fresh, stations, prices, miles[start])
    state = live_state(trip)
    done = trip["plan"]["fuel_stops"][:state["current"]]
    trip["plan"]["fuel_stops"] = done + fresh
    trip["plan"].setdefault("history", []).append({"at": now.isoformat(), "mile": round(miles[start], 1),
                                                   "percent": percent, "avoid": list(avoid), "stops": len(fresh)})
    state["replans"] += 1
    state["sent"] = {k: v for k, v in state["sent"].items() if int(k) < state["current"]}
    save_plan(trip)
    return fresh


def hours_line(hos):
    if not hos:
        return "Hours left: not known from the ELD right now."
    parts = [f"{label} {hos[key]:.1f} h" for key, label in (("drive", "drive"), ("shift", "shift"), ("cycle", "70-hour cycle")) if key in hos]
    return "Hours left on the ELD: " + ", ".join(parts)


def next_stop_message(trip, truck, stop, mile, hos, why):
    speed = average_speed(trip)
    miles_to = max(0.0, stop["mile"] - mile)
    hours_to = miles_to / speed
    mpg = float(trip["mpg"])
    percent = truck.get("fuel_percent")
    lines = [f"<b>Next fuel{' — Load ' + escape(trip['load_number']) if trip['load_number'] else ''}</b> · Unit {escape(fuel.unit_label(truck['unit_number']))}"]
    if why:
        lines.append(escape(why))
    lines += stop_lines(stop, "Fuel at")
    lines.insert(len(lines) - (2 if stop.get("fill_reason") else 1),
                 f"   {miles_to:,.0f} mi ahead, about {hours_to:.1f} h of driving")
    if percent is not None:
        left = max(0.0, float(percent) / 100 * int(trip["tank_gallons"]) * mpg)
        lines.append(f"Tank now {float(percent):.0f}%, about {left:,.0f} mi of fuel.")
    lines.append(hours_line(hos))
    clocks = [hos.get(k) for k in ("drive", "shift") if hos.get(k) is not None]
    if clocks and min(clocks) < hours_to:
        lines.append(f"<b>Your clock runs out in {min(clocks):.1f} h, before this stop. Take your 10 h rest at a truck stop first, Kaido will send the stop after your rest.</b>")
    delivery = trip["stops"][-1]
    if delivery.get("eta"):
        late = f", LATE by about {delivery['late_hours']:.0f} h" if delivery.get("late_hours") else ", on time"
        lines.append(f"Delivery ETA {when_text(delivery['eta'], delivery['longitude'])}{late}")
    return "\n".join(lines)


def stop_keyboard(trip_id, index):
    return {"inline_keyboard": [[{"text": "Fuel there", "callback_data": f"tf:{trip_id}:{index}"},
                                 {"text": "Skip this stop", "callback_data": f"ts:{trip_id}:{index}"}]]}


def send_next(trip, truck, mile, why=""):
    state = live_state(trip)
    stops = trip["plan"]["fuel_stops"]
    if state["current"] >= len(stops):
        return False
    stop = stops[state["current"]]
    hos, _duty = hos_for(truck)
    result = send(trip["chat_id"], next_stop_message(trip, truck, stop, mile, hos, why),
                  reply_markup=stop_keyboard(trip["id"], state["current"]))
    if result.get("ok"):
        state["sent"][str(state["current"])] = {"at": datetime.now(timezone.utc).isoformat(),
                                                "percent": truck.get("fuel_percent") and float(truck["fuel_percent"]),
                                                "message_id": result.get("message_id"), "station_id": stop["station_id"]}
        save_plan(trip)
        call("sendVenue", {"chat_id": trip["chat_id"], "latitude": stop["latitude"], "longitude": stop["longitude"],
                           "title": stop["name"][:60], "address": f"Mile {stop['mile']:,.0f}, buy {stop['gallons']:.0f} gal",
                           "reply_to_message_id": result.get("message_id")})
    return bool(result.get("ok"))


def follow():
    done = []
    active = rows(
        """select * from trips where status in ('sent', 'accepted') and chat_id is not null
             and created_at > now() - make_interval(days => %s) order by id""",
        (FOLLOW_DAYS,),
    )
    for trip in active:
        truck = load_truck(trip["truck_id"])
        if not truck or truck["latitude"] is None or not truck["located_at"]:
            continue
        if truck["located_at"] < datetime.now(timezone.utc) - timedelta(minutes=FRESH_POSITION_MINUTES):
            continue
        points, miles = route_of(trip)
        mile, off = locate(points, miles, float(truck["latitude"]), float(truck["longitude"]))
        if off > OFF_ROUTE_MILES:
            continue
        if mile >= float(trip["distance_miles"]) - 3:
            execute("update trips set status = 'done', updated_at = now() where id = %s", (trip["id"],))
            done.append((trip["id"], "delivered"))
            continue
        state = live_state(trip)
        stops = trip["plan"]["fuel_stops"]
        percent = float(truck["fuel_percent"]) if truck.get("fuel_percent") is not None else None
        alert = float(truck["fuel_alert_percent"] or 35)
        if state["current"] >= len(stops):
            if percent is not None and percent <= alert:
                if replan(trip, truck, mile) and send_next(trip, truck, mile, "The tank is getting low, here is the best stop ahead."):
                    done.append((trip["id"], "low, replanned"))
            continue
        stop = stops[state["current"]]
        sent = state["sent"].get(str(state["current"]))
        if sent:
            if percent is not None and sent.get("percent") is not None and percent >= sent["percent"] + REFUEL_JUMP:
                state["current"] += 1
                save_plan(trip)
                done.append((trip["id"], "fueled"))
            elif mile > stop["mile"] + PASSED_MILES:
                state["skipped"].append(stop["station_id"])
                replan(trip, truck, mile, state["skipped"])
                if send_next(trip, truck, mile, f"You passed {stop['name']} without fueling, so Kaido looked again. Best stop from here:"):
                    done.append((trip["id"], "passed, replanned"))
            continue
        usable = None if percent is None else (percent - 10) / 100 * int(trip["tank_gallons"]) * float(trip["mpg"])
        if usable is not None and usable < stop["mile"] - mile:
            replan(trip, truck, mile, state["skipped"])
            if send_next(trip, truck, mile, "The tank is lower than planned, so Kaido looked again. Best stop from here:"):
                done.append((trip["id"], "short on fuel, replanned"))
            continue
        if stop["mile"] - mile <= NEXT_STOP_MILES or (percent is not None and percent <= alert):
            if send_next(trip, truck, mile):
                done.append((trip["id"], f"sent stop {state['current'] + 1}"))
    return done


def stop_callback(query, parts, trip, truck, chat_id, message_id, who):
    index = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else -1
    state = live_state(trip)
    stops = trip["plan"]["fuel_stops"]
    if index != state["current"] or index >= len(stops):
        answer(query["id"], "That stop is no longer the current one.")
        return True
    stop = stops[index]
    if parts[0] == "tf":
        state["sent"].setdefault(str(index), {})["confirmed"] = datetime.now(timezone.utc).isoformat()
        save_plan(trip)
        call("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": []}})
        send(chat_id, f"{who} will fuel at {escape(place_name(stop))}. Buy about {stop['gallons']:.0f} gal. "
                      "Kaido sends the next stop when it is time.", reply_to_message_id=message_id)
        answer(query["id"], "Saved.")
        return True
    state["skipped"].append(stop["station_id"])
    call("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": []}})
    points, miles = route_of(trip)
    mile = locate(points, miles, float(truck["latitude"]), float(truck["longitude"]))[0] if truck["latitude"] is not None else 0.0
    fresh = replan(trip, truck, mile, state["skipped"])
    answer(query["id"], "Looking for another stop.")
    if fresh:
        send_next(trip, truck, mile, f"{who} skipped {stop['name']}. Next best stop from here:")
    else:
        send(chat_id, f"{who} skipped {escape(stop['name'])}. Kaido found no other priced stop in range, fuel at the next big truck stop.")
    notify_office(trip, truck, f"skipped fuel at {stop['name']}")
    return True
