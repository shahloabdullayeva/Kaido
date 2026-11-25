from datetime import datetime, time, timezone

from flask import Blueprint, g, render_template, request

from .. import forms
from ..auth import login_required
from ..db import rows
from ..fuel_guard import LABELS as FUEL_LABELS
from ..health import base_kind, title_of
from ..safety import INSTANT, NAMES
from ..tenancy import carrier_groups, company_required

bp = Blueprint("alerts", __name__)

GROUPS = {
    "health": "Truck health", "engine": "Check engine", "hours": "Hours", "service": "Service",
    "mpg": "MPG", "safety": "Safety", "fuel": "Fuel", "documents": "Documents",
}
HEALTH_GROUP = {"check_engine": "engine", "service_soon": "service", "service_over": "service", "mpg_drop": "mpg"}
PERIODS = {"all": None, "1": 1, "7": 7, "30": 30}
SAFETY_GROUPS = {
    "speeding": ("Speeding", "e.kind like 'speeding:%%'"),
    "harsh": ("Harsh driving", "e.kind in ('braking', 'harshBrake', 'harshTurn', 'harshAccel', 'acceleration')"),
    "phone": ("Phone use", "e.kind = 'mobileUsage'"),
    "seatbelt": ("No seatbelt", "e.kind = 'noSeatbelt'"),
    "distraction": ("Distraction", "e.kind in ('genericDistraction', 'drowsy', 'drowsiness')"),
    "following": ("Following distance", "e.kind in ('followingDistance', 'forwardCollisionWarning')"),
    "crash": ("Crash", "e.kind in ('crash', 'rollover', 'rolloverProtection')"),
    "other": ("Other", "e.kind in ('rollingStop', 'obstructedCamera', 'event')"),
}


def health_group(kind):
    return HEALTH_GROUP.get(base_kind(kind), "hours" if kind.startswith("hos_") else "health")


def period_clause(period, column):
    days = PERIODS[period]
    return f" and {column} > now() - interval '{int(days)} days'" if days else ""


@bp.get("/alerts")
@login_required
@company_required
def index():
    kind = forms.pick(request.args.get("kind"), ["all", *GROUPS], "all")
    status = forms.pick(request.args.get("status"), ["all", "open", "cleared"], "all")
    period = forms.pick(request.args.get("period"), list(PERIODS), "all")
    company_id = g.company["id"]
    items = []
    if kind in ("all", "health", "engine", "hours", "service", "mpg"):
        for row in rows(
            f"""select a.*, t.unit_number, d.name as driver_name, coalesce(a.driver_id, t.driver_id) as driver_id from health_alerts a join trucks t on t.id = a.truck_id
                left join drivers d on d.id = coalesce(a.driver_id, t.driver_id)
                where a.company_id = %s{period_clause(period, 'a.opened_at')}
                order by a.opened_at desc limit 500""",
            (company_id,),
        ):
            group = health_group(row["kind"])
            if kind != "all" and group != kind:
                continue
            items.append({"at": row["opened_at"], "group": group, "title": title_of(row["kind"]), "detail": row["detail"],
                          "truck_id": row["truck_id"], "unit": row["unit_number"], "driver": row["driver_name"],
                          "driver_id": row["driver_id"], "open": row["cleared_at"] is None, "link": f"/faults/{row['fault_id']}" if row["fault_id"] else None})
    if kind in ("all", "safety"):
        for row in rows(
            f"""select e.*, t.unit_number, d.name as driver_name from safety_events e
                left join trucks t on t.id = e.truck_id left join drivers d on d.id = e.driver_id
                where e.company_id = %s and e.kind = any(%s){period_clause(period, 'e.happened_at')}
                order by e.happened_at desc limit 500""",
            (company_id, list(INSTANT)),
        ):
            items.append({"at": row["happened_at"], "group": "safety", "title": NAMES.get(row["kind"]) or row["label"],
                          "detail": safety_detail(row), "truck_id": row["truck_id"], "unit": row["unit_number"],
                          "driver": row["driver_name"], "driver_id": row["driver_id"], "open": None, "link": "/safety"})
    if kind in ("all", "fuel"):
        for row in rows(
            f"""select a.*, t.unit_number, d.name as driver_name from fuel_alerts a left join trucks t on t.id = a.truck_id
                left join drivers d on d.id = a.driver_id
                where a.company_id = %s{period_clause(period, 'a.happened_at')}
                order by a.happened_at desc limit 500""",
            (company_id,),
        ):
            items.append({"at": row["happened_at"], "group": "fuel", "title": FUEL_LABELS.get(row["kind"], row["kind"]),
                          "detail": row["summary"], "truck_id": row["truck_id"], "unit": row["unit_number"],
                          "driver": row["driver_name"], "open": row["status"] == "open", "link": "/fuel/alerts"})
    if kind in ("all", "documents"):
        from .. import documents
        for doc in documents.listing(company_id):
            if doc["left"] is None or doc["left"] > documents.SOON_DAYS:
                continue
            items.append({"at": datetime.combine(doc["expires_on"], time(12), timezone.utc), "group": "documents",
                          "title": doc["label"], "detail": doc["status"], "truck_id": doc.get("truck_id"),
                          "unit": doc.get("truck_unit"), "driver": doc.get("driver_name"), "open": doc["left"] < 0,
                          "link": f"/documents/{doc['id']}"})
    if status != "all":
        items = [i for i in items if (i["open"] is True) == (status == "open")]
    groups = carrier_groups()
    carrier = forms.pick(request.args.get("group"), groups, "")
    if carrier:
        in_group = {r["id"] for r in rows("select id from trucks where company_id = %s and carrier_group = %s", (company_id, carrier))}
        items = [i for i in items if i.get("truck_id") in in_group]
    only_truck = forms.integer(request.args.get("truck_id"))
    only_driver = forms.integer(request.args.get("driver_id"))
    if only_truck:
        items = [i for i in items if i.get("truck_id") == only_truck]
    if only_driver:
        items = [i for i in items if i.get("driver_id") == only_driver]
    items.sort(key=lambda i: i["at"], reverse=True)
    counts = {}
    for item in items:
        counts[item["group"]] = counts.get(item["group"], 0) + 1
    return render_template("alerts/index.html", title="Alerts", active="/alerts", items=items[:500], total=len(items),
                           kind=kind, status=status, period=period, groups=GROUPS, counts=counts,
                           carrier_groups=groups, carrier=carrier)


def safety_detail(row):
    parts = []
    if row["speed_mph"]:
        parts.append(f"{int(row['speed_mph'])} mph in a {int(row['limit_mph'] or 0)} zone")
    if row["place"]:
        parts.append(row["place"])
    return " · ".join(parts) or None


@bp.get("/safety")
@login_required
@company_required
def safety():
    group = forms.pick(request.args.get("kind"), ["all", *SAFETY_GROUPS], "all")
    period = forms.pick(request.args.get("period"), list(PERIODS), "all")
    company_id = g.company["id"]
    clause = period_clause(period, "e.happened_at")
    for key in ("truck_id", "driver_id"):
        value = forms.integer(request.args.get(key))
        if value:
            clause += f" and e.{key} = {int(value)}"
    groups = carrier_groups()
    carrier = forms.pick(request.args.get("group"), groups, "")
    if carrier:
        clause += f" and t.carrier_group = '{carrier.replace(chr(39), chr(39) * 2)}'"
    if group != "all":
        clause += " and " + SAFETY_GROUPS[group][1]
    cases = ", ".join(f"count(*) filter (where {sql}) as {key}" for key, (_, sql) in SAFETY_GROUPS.items())
    drivers = rows(
        f"""select coalesce(d.name, 'Unit ' || t.unit_number, 'Unknown') as name, d.id as driver_id,
              count(*) as total, {cases}
            from safety_events e left join drivers d on d.id = e.driver_id left join trucks t on t.id = e.truck_id
            where e.company_id = %s{clause}
            group by 1, 2 order by total desc limit 100""",
        (company_id,),
    )
    light = "" if group == "speeding" else " and e.kind <> 'speeding:light'"
    events = rows(
        f"""select e.*, t.unit_number, d.name as driver_name from safety_events e
            left join trucks t on t.id = e.truck_id left join drivers d on d.id = e.driver_id
            where e.company_id = %s{clause}{light}
            order by e.happened_at desc limit 300""",
        (company_id,),
    )
    for event in events:
        event["title"] = NAMES.get(event["kind"]) or event["label"] or event["kind"]
        event["detail"] = safety_detail(event)
        event["serious"] = event["kind"] in INSTANT
    return render_template("alerts/safety.html", title="Safety", active="/trucks", drivers=drivers, events=events,
                           groups=SAFETY_GROUPS, group=group, period=period,
                           carrier_groups=groups, carrier=carrier)
