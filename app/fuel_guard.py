import json
from datetime import datetime, timedelta, timezone
from html import escape

from . import fuel, shops
from .config import config
from .db import execute, one, rows
from .logs import get
from .telegram import send

log = get("fuel-guard")

AWAY_MILES = 15
AWAY_CITY_MILES = 40
MIN_GALLONS = 40
TANK_SHARE = 0.6
TANK_SLACK = 10
OVER_SPACE = 1.15
DOUBLE_HOURS = 2
DROP_POINTS = 12
DROP_GALLONS = 25
MISSING_POINTS = 10
MISSING_GALLONS = 20
CONFIRM_MINUTES = 45
CONFIRM_READINGS = 3
CONFIRM_WINDOW_MINUTES = 180
FILL_JUMP = 10
STUCK_MILES = 50
STUCK_POINTS = 2
ROAD_FACTOR = 1.15
DEFAULT_MPG = 6.5
DROP_GAP_MINUTES = 60
PARKED_MPH = 3
NOTIFY_DAYS = 3
LABELS = {
    "not_in_tank": "Fuel not in the tank",
    "away_from_truck": "Card used away from the truck",
    "over_capacity": "More than the tank holds",
    "double_fill": "Two fills close together",
    "tank_drop": "Tank dropped while parked",
}


def window(entry, station):
    stamp = entry["purchased_at"]
    naive = stamp.astimezone(timezone.utc).replace(tzinfo=None)
    zones = [timezone.utc, shops.zone_for(-90.0)]
    if station and station.get("longitude") is not None:
        zones.append(shops.zone_for(float(station["longitude"])))
    moments = [naive.replace(tzinfo=zone).astimezone(timezone.utc) for zone in zones]
    return min(moments) - timedelta(hours=1), max(moments) + timedelta(hours=1)


def track(truck_id, start, end):
    return rows(
        """select latitude, longitude, fuel_percent, speed_mph, recorded_at from truck_positions
           where truck_id = %s and recorded_at between %s and %s order by recorded_at""",
        (truck_id, start, end),
    )


def station_of(entry):
    if not entry["station_id"]:
        return None
    return fuel.resolve_station(one("select * from fuel_stations where id = %s", (entry["station_id"],)))


def record(entry_or_truck, kind, happened_at, summary, details, severity="warn", transaction_id=None):
    found = one(
        """insert into fuel_alerts (company_id, truck_id, driver_id, transaction_id, kind, severity, happened_at, summary, details)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
           on conflict do nothing returning *""",
        (entry_or_truck["company_id"], entry_or_truck.get("truck_id") or entry_or_truck.get("id"), entry_or_truck.get("driver_id"),
         transaction_id, kind, severity, happened_at, summary, json.dumps(details, default=str)),
    )
    return found


def check_transaction(entry):
    found = []
    truck = one("select * from trucks where id = %s", (entry["truck_id"],))
    tank = float(truck["tank_gallons"] or 200)
    gallons = float(entry["gallons"])
    station = station_of(entry)
    where = entry["location"] or (station["name"] if station else "the station")
    if gallons > tank * 1.05:
        found.append(("over_capacity", "high", f"{gallons:.0f} gal bought, the truck holds {tank:.0f} gal",
                      {"gallons": gallons, "tank": tank}))
    start, end = window(entry, station)
    points = track(entry["truck_id"], start - timedelta(hours=1), end + timedelta(hours=2))
    near = [p for p in points if start <= p["recorded_at"] <= end]
    if station and station.get("latitude") is not None and near:
        limit = AWAY_CITY_MILES if station.get("located_by") in ("city", None) else AWAY_MILES
        closest = min(fuel.haversine(p["latitude"], p["longitude"], station["latitude"], station["longitude"]) for p in near)
        if closest > limit:
            found.append(("away_from_truck", "high",
                          f"Card used at {where}, the truck was at least {closest:.0f} mi away",
                          {"closest_miles": round(closest, 1), "readings": len(near)}))
    levels = [p for p in points if p["fuel_percent"] is not None]
    before = [p for p in levels if p["recorded_at"] <= end]
    if gallons >= MIN_GALLONS and before:
        low = min(before, key=lambda p: float(p["fuel_percent"]))
        after = [p for p in levels if p["recorded_at"] > low["recorded_at"]]
        if after:
            high = max(after, key=lambda p: float(p["fuel_percent"]))
            rise = max(0.0, (float(high["fuel_percent"]) - float(low["fuel_percent"])) / 100 * tank)
            space = (100 - float(low["fuel_percent"])) / 100 * tank
            if rise < gallons * TANK_SHARE - TANK_SLACK:
                found.append(("not_in_tank", "high" if rise < gallons * 0.3 else "warn",
                              f"{gallons:.0f} gal bought at {where}, the tank rose only about {rise:.0f} gal",
                              {"gallons": gallons, "tank_rise": round(rise), "from": float(low["fuel_percent"]),
                               "to": float(high["fuel_percent"])}))
            elif gallons > space * OVER_SPACE + 15 and gallons <= tank * 1.05:
                found.append(("over_capacity", "warn",
                              f"{gallons:.0f} gal bought, the tank only had room for about {space:.0f} gal",
                              {"gallons": gallons, "space": round(space), "from": float(low["fuel_percent"])}))
    twin = one(
        """select id, gallons, purchased_at, location from fuel_transactions
           where truck_id = %s and id <> %s and fuel_type = 'diesel' and gallons >= 20
             and purchased_at between %s and %s order by purchased_at limit 1""",
        (entry["truck_id"], entry["id"], entry["purchased_at"] - timedelta(hours=DOUBLE_HOURS), entry["purchased_at"]),
    )
    if twin and gallons >= 20:
        found.append(("double_fill", "warn",
                      f"Two fills {abs((entry['purchased_at'] - twin['purchased_at']).total_seconds()) / 60:.0f} min apart: "
                      f"{float(twin['gallons']):.0f} gal and {gallons:.0f} gal",
                      {"other_transaction": twin["id"], "other_location": twin["location"]}))
    saved = []
    for kind, severity, summary, details in found:
        details.update({"invoice": entry["invoice_no"], "card": entry["card_last4"], "location": entry["location"]})
        alert = record(entry, kind, entry["purchased_at"], summary, details, severity, entry["id"])
        if alert:
            saved.append(alert)
    execute("update fuel_transactions set fraud_checked_at = now() where id = %s", (entry["id"],))
    return saved


def driven_miles(points):
    return sum(fuel.haversine(a["latitude"], a["longitude"], b["latitude"], b["longitude"])
               for a, b in zip(points, points[1:])) * ROAD_FACTOR


def drop_verdict(before, after, rest, tank, mpg):
    following = [after]
    filled = False
    for point in rest:
        if (point["recorded_at"] - after["recorded_at"]).total_seconds() / 60 > CONFIRM_WINDOW_MINUTES:
            break
        if float(point["fuel_percent"]) - float(following[-1]["fuel_percent"]) >= FILL_JUMP:
            filled = True
            break
        following.append(point)
    span = (following[-1]["recorded_at"] - after["recorded_at"]).total_seconds() / 60
    window_over = rest and (rest[-1]["recorded_at"] - after["recorded_at"]).total_seconds() / 60 >= CONFIRM_WINDOW_MINUTES
    if filled:
        if len(following) < 2:
            return None
    elif len(following) < CONFIRM_READINGS or (span < CONFIRM_MINUTES and not window_over):
        return None
    miles = driven_miles([before] + following)
    levels = [float(p["fuel_percent"]) for p in following]
    if miles >= STUCK_MILES and max(levels) - min(levels) <= STUCK_POINTS:
        return {"verdict": "sensor", "miles": round(miles)}
    expected = float(before["fuel_percent"]) - miles / mpg / tank * 100
    observed = sorted(levels[-3:])[len(levels[-3:]) // 2]
    missing = expected - observed
    return {"verdict": "missing" if missing >= MISSING_POINTS and missing / 100 * tank >= MISSING_GALLONS else "recovered",
            "missing": round(missing, 1), "gallons": round(missing / 100 * tank), "miles": round(miles),
            "expected": round(expected, 1), "observed": observed}


def check_drops():
    saved = []
    trucks = rows("""select id, company_id, driver_id, tank_gallons from trucks
                     where fuel_percent_at > now() - interval '3 hours'""")
    for truck in trucks:
        now = datetime.now(timezone.utc)
        points = [p for p in track(truck["id"], now - timedelta(hours=8), now) if p["fuel_percent"] is not None]
        tank = float(truck["tank_gallons"] or 200)
        mpg = fuel.truck_mpg(truck["id"]) or DEFAULT_MPG
        for index in range(1, len(points)):
            before, after = points[index - 1], points[index]
            gap = (after["recorded_at"] - before["recorded_at"]).total_seconds() / 60
            drop = float(before["fuel_percent"]) - float(after["fuel_percent"])
            parked = float(before["speed_mph"] or 0) <= PARKED_MPH and float(after["speed_mph"] or 0) <= PARKED_MPH
            moved = fuel.haversine(before["latitude"], before["longitude"], after["latitude"], after["longitude"])
            if gap > DROP_GAP_MINUTES or not parked or moved > 0.5 or drop < DROP_POINTS or drop / 100 * tank < DROP_GALLONS:
                continue
            verdict = drop_verdict(before, after, points[index + 1:], tank, mpg)
            if not verdict or verdict["verdict"] != "missing":
                continue
            alert = record({"company_id": truck["company_id"], "truck_id": truck["id"], "driver_id": truck["driver_id"]},
                           "tank_drop", after["recorded_at"],
                           f"Tank fell {before['fuel_percent']:.0f}% to {after['fuel_percent']:.0f}% in {gap:.0f} min while parked; "
                           f"about {verdict['gallons']} gal still missing after {verdict['miles']} mi",
                           {"from": float(before["fuel_percent"]), "to": float(after["fuel_percent"]), "gallons": verdict["gallons"],
                            "missing_points": verdict["missing"], "miles_after": verdict["miles"],
                            "latitude": float(after["latitude"]), "longitude": float(after["longitude"])}, "high")
            if alert:
                saved.append(alert)
    return saved


def notify(alert):
    truck = one("select unit_number from trucks where id = %s", (alert["truck_id"],)) if alert["truck_id"] else None
    company = one("select timezone from companies where id = %s", (alert["company_id"],))
    from .reminders import zone_for
    when = alert["happened_at"].astimezone(zone_for(company["timezone"])).strftime("%a %b %d %H:%M")
    lines = [f"<b>Fuel check: {LABELS[alert['kind']]}</b>",
             f"Unit {escape(fuel.unit_label(truck['unit_number']))} · {when}" if truck else when,
             escape(alert["summary"]),
             f"<a href=\"{config.APP_URL}/fuel/alerts\">Open in Kaido</a>"]
    text = "\n".join(lines)
    from .alert_group import chat_of, office
    if chat_of(alert["company_id"]):
        sent = sum(bool(r.get("ok")) for r in office(alert["company_id"], "fuel", text))
        execute("update fuel_alerts set notified_at = now() where id = %s", (alert["id"],))
        return sent
    sent = 0
    for user in rows(
        """select distinct u.telegram_chat_id from users u join memberships m on m.user_id = u.id
           where m.company_id = %s and m.role = 'admin' and u.telegram_chat_id is not null and u.status = 'active'""",
        (alert["company_id"],),
    ):
        sent += bool(send(user["telegram_chat_id"], text).get("ok"))
    execute("update fuel_alerts set notified_at = now() where id = %s", (alert["id"],))
    return sent


def run():
    alerts = []
    for entry in rows(
        """select * from fuel_transactions where fraud_checked_at is null and fuel_type = 'diesel'
           order by purchased_at limit 500"""
    ):
        alerts += check_transaction(entry)
    alerts += check_drops()
    told = 0
    for alert in alerts:
        recent = alert["happened_at"] > datetime.now(timezone.utc) - timedelta(days=NOTIFY_DAYS)
        if recent:
            told += notify(alert) > 0
        else:
            execute("update fuel_alerts set notified_at = now() where id = %s", (alert["id"],))
    return {"alerts": len(alerts), "notified": told}
