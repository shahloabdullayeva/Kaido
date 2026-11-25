from datetime import datetime, time, timezone

from flask import Blueprint, g, redirect, render_template, request

from .. import forms
from ..auth import login_required
from ..audit import audit
from ..db import execute, one, rows
from ..fuel_guard import LABELS as FUEL_LABELS
from ..health import base_kind, title_of
from ..reminders import zone_for
from ..safety import INSTANT, NAMES, counted_sql
from ..tenancy import carrier_groups, company_required, role_required

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


STATUSES = ["open", "acknowledged", "cleared"]


def health_status(row):
    if row["cleared_at"]:
        return "cleared"
    return "acknowledged" if row["acknowledged_at"] else "open"


def collect(company, kind, period):
    company_id = company["id"]
    items = []
    if kind in ("all", "health", "engine", "hours", "service", "mpg"):
        for row in rows(
            f"""select a.*, t.unit_number, d.name as driver_name, coalesce(a.driver_id, t.driver_id) as who_id
                from health_alerts a join trucks t on t.id = a.truck_id
                left join drivers d on d.id = coalesce(a.driver_id, t.driver_id)
                where a.company_id = %s{period_clause(period, 'a.opened_at')}
                order by a.opened_at desc limit 3000""",
            (company_id,),
        ):
            group = health_group(row["kind"])
            if kind != "all" and group != kind:
                continue
            items.append({"ref": f"h{row['id']}", "at": row["opened_at"], "group": group, "type": row["kind"],
                          "title": title_of(row["kind"]), "detail": row["detail"], "truck_id": row["truck_id"],
                          "unit": row["unit_number"], "driver": row["driver_name"], "driver_id": row["who_id"],
                          "status": health_status(row), "link": f"/faults/{row['fault_id']}" if row["fault_id"] else None})
    if kind in ("all", "safety"):
        for row in rows(
            f"""select e.*, t.unit_number, d.name as driver_name from safety_events e
                left join trucks t on t.id = e.truck_id left join drivers d on d.id = e.driver_id
                where e.company_id = %s and e.kind = any(%s) and {counted_sql(company)}{period_clause(period, 'e.happened_at')}
                order by e.happened_at desc limit 3000""",
            (company_id, list(INSTANT)),
        ):
            items.append({"ref": f"s{row['id']}", "at": row["happened_at"], "group": "safety", "type": row["kind"],
                          "title": NAMES.get(row["kind"]) or row["label"], "detail": safety_detail(row),
                          "truck_id": row["truck_id"], "unit": row["unit_number"], "driver": row["driver_name"],
                          "driver_id": row["driver_id"], "status": row["status"], "link": None})
    if kind in ("all", "fuel"):
        for row in rows(
            f"""select a.*, t.unit_number, d.name as driver_name from fuel_alerts a left join trucks t on t.id = a.truck_id
                left join drivers d on d.id = a.driver_id
                where a.company_id = %s{period_clause(period, 'a.happened_at')}
                order by a.happened_at desc limit 1000""",
            (company_id,),
        ):
            state = "open" if row["status"] == "open" else "cleared"
            if state == "open" and row["acknowledged_at"]:
                state = "acknowledged"
            items.append({"ref": f"f{row['id']}", "at": row["happened_at"], "group": "fuel", "type": row["kind"],
                          "title": FUEL_LABELS.get(row["kind"], row["kind"]), "detail": row["summary"],
                          "truck_id": row["truck_id"], "unit": row["unit_number"], "driver": row["driver_name"],
                          "driver_id": row["driver_id"], "status": state, "link": "/fuel/alerts"})
    if kind in ("all", "documents"):
        from .. import documents
        for doc in documents.listing(company_id):
            if doc["left"] is None or doc["left"] > documents.SOON_DAYS:
                continue
            items.append({"ref": None, "at": datetime.combine(doc["expires_on"], time(12), timezone.utc), "group": "documents",
                          "type": doc["kind"], "title": doc["label"], "detail": doc["status"], "truck_id": doc.get("truck_id"),
                          "unit": doc.get("truck_unit"), "driver": doc.get("driver_name"), "driver_id": doc.get("driver_id"),
                          "status": "open", "link": f"/documents/{doc['id']}"})
    return items


def grouped(items, tz_name):
    zone = zone_for(tz_name)
    rows_out = {}
    for item in items:
        key = (item["group"], item["type"], item["truck_id"] or item["unit"], item["at"].astimezone(zone).date())
        row = rows_out.get(key)
        if not row:
            row = rows_out[key] = dict(item, count=0, refs=[], first=item["at"], statuses=set(), details=[])
        row["count"] += 1
        if item["ref"]:
            row["refs"].append(item["ref"])
        row["statuses"].add(item["status"])
        row["first"] = min(row["first"], item["at"])
        if item["at"] > row["at"]:
            row.update(at=item["at"], detail=item["detail"])
    out = []
    for row in rows_out.values():
        statuses = row.pop("statuses")
        row["status"] = "open" if "open" in statuses else ("acknowledged" if "acknowledged" in statuses else "cleared")
        out.append(row)
    out.sort(key=lambda r: r["at"], reverse=True)
    return out


@bp.get("/alerts")
@login_required
@company_required
def index():
    return render_alerts()


@bp.get("/hours")
@login_required
@company_required
def hours():
    return render_alerts("hours")


def render_alerts(forced=None):
    kind = forced or forms.pick(request.args.get("kind"), ["all", *GROUPS], "all")
    status = forms.pick(request.args.get("status"), ["open", "all", *STATUSES], "open")
    period = forms.pick(request.args.get("period"), list(PERIODS), "all")
    company_id = g.company["id"]
    items = collect(g.company, kind, period)
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
    if status == "open":
        items = [i for i in items if i["status"] in ("open", "acknowledged")]
    elif status != "all":
        items = [i for i in items if i["status"] == status]
    table = grouped(items, g.company.get("timezone"))
    counts = {}
    for row in table:
        counts[row["group"]] = counts.get(row["group"], 0) + 1
    return render_template("alerts/index.html", title="Hours" if forced else "Alerts", active="/trucks" if forced else "/alerts",
                           hours_view=bool(forced), items=table[:400], total=len(table),
                           raw_total=len(items), kind=kind, status=status, period=period, groups=GROUPS, counts=counts,
                           carrier_groups=groups, carrier=carrier, statuses=STATUSES)


@bp.post("/alerts/act")
@login_required
@role_required("admin")
def act():
    action = forms.pick(request.form.get("action"), ["acknowledge", "clear", "reopen"], None)
    refs = [ref for ref in (request.form.get("refs") or "").split(",") if ref[:1] in ("h", "s", "f") and ref[1:].isdigit()]
    company_id, user_id = g.company["id"], g.session["user_id"]
    ids = {"h": [], "s": [], "f": []}
    for ref in refs[:2000]:
        ids[ref[0]].append(int(ref[1:]))
    if action == "acknowledge":
        execute("update health_alerts set acknowledged_at = now(), acknowledged_by = %s where company_id = %s and id = any(%s) and acknowledged_at is null",
                (user_id, company_id, ids["h"]))
        execute("update safety_events set status = 'acknowledged', acknowledged_at = now(), acknowledged_by = %s where company_id = %s and id = any(%s) and status = 'open'",
                (user_id, company_id, ids["s"]))
        execute("update fuel_alerts set acknowledged_at = now(), acknowledged_by = %s where company_id = %s and id = any(%s) and acknowledged_at is null",
                (user_id, company_id, ids["f"]))
    elif action == "clear":
        execute("update health_alerts set cleared_at = now(), cleared_by = %s where company_id = %s and id = any(%s) and cleared_at is null",
                (user_id, company_id, ids["h"]))
        execute("update safety_events set status = 'cleared', cleared_at = now(), cleared_by = %s where company_id = %s and id = any(%s)",
                (user_id, company_id, ids["s"]))
        execute("update fuel_alerts set status = 'ok' where company_id = %s and id = any(%s) and status = 'open'",
                (company_id, ids["f"]))
    elif action == "reopen":
        execute("update safety_events set status = 'open', cleared_at = null, acknowledged_at = null where company_id = %s and id = any(%s)",
                (company_id, ids["s"]))
        execute("update health_alerts set acknowledged_at = null where company_id = %s and id = any(%s)", (company_id, ids["h"]))
    if action:
        audit(f"alerts.{action}", "alert", None, {"count": len(refs)})
    return redirect(request.form.get("back") or "/alerts")


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
    clause += " and " + counted_sql(g.company)
    drivers = rows(
        f"""select coalesce(d.name, 'Unit ' || t.unit_number, 'Unknown') as name, d.id as driver_id,
              count(*) as total, {cases}
            from safety_events e left join drivers d on d.id = e.driver_id left join trucks t on t.id = e.truck_id
            where e.company_id = %s{clause}
            group by 1, 2 order by total desc limit 100""",
        (company_id,),
    )
    events = rows(
        f"""select e.*, t.unit_number, d.name as driver_name from safety_events e
            left join trucks t on t.id = e.truck_id left join drivers d on d.id = e.driver_id
            where e.company_id = %s{clause}
            order by e.happened_at desc limit 300""",
        (company_id,),
    )
    for event in events:
        event["title"] = NAMES.get(event["kind"]) or event["label"] or event["kind"]
        event["detail"] = safety_detail(event)
        event["serious"] = event["kind"] in INSTANT
    return render_template("alerts/safety.html", title="Safety", active="/trucks", drivers=drivers, events=events,
                           groups=SAFETY_GROUPS, group=group, period=period,
                           carrier_groups=groups, carrier=carrier,
                           hidden=one(f"""select count(*) as n from safety_events e where e.company_id = %s
                                         and e.kind like 'speeding:%%' and not {counted_sql(g.company)}""", (company_id,))["n"])


@bp.post("/safety/threshold")
@login_required
@role_required("admin")
def threshold():
    over = forms.integer(request.form.get("over"))
    seconds = forms.integer(request.form.get("seconds"))
    over = min(max(over if over is not None else 10, 0), 40)
    seconds = min(max(seconds if seconds is not None else 30, 0), 600)
    execute("update companies set speeding_min_over = %s, speeding_min_seconds = %s where id = %s", (over, seconds, g.company["id"]))
    audit("company.speeding_threshold", "company", g.company["id"], {"over": over, "seconds": seconds})
    return redirect("/safety")
