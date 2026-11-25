from datetime import datetime, timedelta, timezone

from .db import rows
from .fuel import haversine

MOVING_MPH = 5
SILENT_HOURS = 6
HOME_MILES = 2
ACCIDENT_HOURS = 72
ACCIDENT_WORDS = ("accident", "crash", "collision", "rollover", "hit ")

COLUMNS = [
    ("en_route", "En route", "ok"),
    ("stopped", "Stopped", "info"),
    ("home", "Home", "muted"),
    ("in_shop", "In shop", "warn"),
    ("broken", "Broken down", "bad"),
    ("accident", "Accident", "bad"),
    ("no_signal", "No signal", "muted"),
    ("inactive", "Inactive", "muted"),
]


def board(company):
    company_id = company["id"]
    trucks = rows(
        """select t.*, d.name as driver_name from trucks t left join drivers d on d.id = t.driver_id
           where t.company_id = %s and not coalesce(t.is_outside, false) order by lower(t.unit_number)""",
        (company_id,),
    )
    cases = {}
    for case in rows("""select *, reported_at as occurred_at from maintenance_orders where company_id = %s and breakdown
                             and status not in ('done', 'cancelled') order by reported_at desc""",
                     (company_id,)):
        cases.setdefault(case["truck_id"], case)
    shop = {r["truck_id"] for r in rows(
        "select distinct truck_id from maintenance_orders where company_id = %s and status in ('in_shop', 'in_progress')", (company_id,))}
    crashes = {r["truck_id"]: r["happened_at"] for r in rows(
        """select truck_id, max(happened_at) as happened_at from safety_events where company_id = %s and kind in ('crash', 'rollover')
             and happened_at > now() - make_interval(hours => %s) group by truck_id""", (company_id, ACCIDENT_HOURS))}
    moved = {r["truck_id"]: r["at"] for r in rows(
        """select truck_id, max(recorded_at) as at from truck_positions where company_id = %s and speed_mph >= %s
             and recorded_at > now() - interval '14 days' group by truck_id""", (company_id, MOVING_MPH))}
    trailers = {}
    for r in rows("select truck_id, unit_number from trailers where company_id = %s and truck_id is not null", (company_id,)):
        trailers.setdefault(r["truck_id"], []).append(r["unit_number"])
    home = (float(company["home_latitude"]), float(company["home_longitude"])) if company.get("home_latitude") else None
    now = datetime.now(timezone.utc)
    columns = {key: [] for key, _, _ in COLUMNS}
    for truck in trucks:
        case = cases.get(truck["id"])
        located = truck["located_at"]
        fresh = located and now - located < timedelta(hours=SILENT_HOURS)
        note = None
        text = " ".join([(case or {}).get("description") or "", (case or {}).get("cause") or ""]).lower() if case else ""
        if truck["status"] in ("sold", "inactive"):
            key = "inactive"
        elif truck["id"] in crashes or (case and any(word in text for word in ACCIDENT_WORDS)):
            key = "accident"
            note = case["description"] if case else "Crash detected by the camera"
        elif truck["status"] in ("shop", "out_of_service") or truck["id"] in shop or (case and case["status"] == "in_shop"):
            key = "in_shop"
            note = case["description"] if case else None
        elif case:
            key = "broken"
            note = case["description"]
        elif not fresh:
            key = "no_signal"
            note = f"Last seen {located.strftime('%d %b %H:%M')} UTC" if located else "Never reported"
        elif float(truck["speed_mph"] or 0) >= MOVING_MPH:
            key = "en_route"
            note = f"{int(float(truck['speed_mph']))} mph"
        elif home and truck["latitude"] is not None and haversine(home[0], home[1], float(truck["latitude"]), float(truck["longitude"])) <= HOME_MILES:
            key = "home"
        else:
            key = "stopped"
        since = moved.get(truck["id"])
        if key in ("stopped", "home") and since:
            hours = (now - since).total_seconds() / 3600
            note = f"Parked {int(hours // 24)} d {int(hours % 24)} h" if hours >= 24 else f"Parked {int(hours)} h {int(hours * 60 % 60)} min"
        columns[key].append({"truck": truck, "note": note, "trailers": trailers.get(truck["id"], [])})
    return [{"key": key, "label": label, "tone": tone, "items": columns[key]} for key, label, tone in COLUMNS]
