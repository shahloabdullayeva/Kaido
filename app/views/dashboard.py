from flask import Blueprint, g, render_template

from .. import hos
from ..auth import login_required
from ..db import rows
from ..filters import ago
from ..queries import attention_score, company_summary, expiring_documents, service_status, trucks_with_service
from ..tenancy import company_required

bp = Blueprint("dashboard", __name__)


def fleet_pins(fleet, hours=None):
    from ..hos import SOURCES
    hours = hours or {}
    pins = []
    for truck in fleet:
        if truck.get("latitude") is None or truck.get("longitude") is None:
            continue
        score = truck.get("score") or 0
        pins.append({
            "id": truck["id"],
            "unit": truck["unit_number"],
            "driver": truck.get("driver_name"),
            "truck": " ".join(str(part) for part in [truck.get("year"), truck.get("make"), truck.get("model")] if part),
            "where": truck.get("location"),
            "when": ago(truck.get("located_at")),
            "source": SOURCES.get(truck.get("location_source") or "", None),
            "duty": hours[truck["driver_id"]]["duty_label"] if truck.get("driver_id") in hours else None,
            "drive_left": hours[truck["driver_id"]]["drive"] if truck.get("driver_id") in hours else None,
            "odometer": f"{truck['odometer']:,} mi" if truck.get("odometer") else None,
            "status": (truck.get("status") or "").replace("_", " "),
            "faults": truck.get("active_faults") or 0,
            "breakdowns": truck.get("open_breakdowns") or 0,
            "tone": "bad" if score >= 3 else ("warn" if score >= 1 else "ok"),
            "lat": float(truck["latitude"]),
            "lon": float(truck["longitude"]),
        })
    return pins


@bp.get("/")
@login_required
@company_required
def index():
    company_id = g.company["id"]
    summary = company_summary(company_id)
    fleet = [truck for truck in trucks_with_service(company_id) if not truck["is_outside"]]
    for truck in fleet:
        truck["statuses"] = service_status(truck)
        truck["score"] = attention_score(truck)
    pins = fleet_pins(fleet, hos.for_drivers(company_id))
    attention = sorted([t for t in fleet if t["score"] > 0], key=lambda t: (-t["score"], t["unit_number"]))[:8]
    breakdowns = rows(
        """select b.*, t.unit_number, d.name as driver_name
           from breakdowns b join trucks t on t.id = b.truck_id
           left join drivers d on d.id = b.driver_id
           where b.company_id = %s and b.status <> 'resolved'
           order by b.occurred_at desc limit 6""",
        (company_id,),
    )
    faults = rows(
        """select f.*, t.unit_number from fault_events f join trucks t on t.id = f.truck_id
           where f.company_id = %s and f.cleared_at is null
           order by f.last_seen_at desc limit 6""",
        (company_id,),
    )
    fuel = rows(
        """select f.*, t.unit_number from fuel_transactions f join trucks t on t.id = f.truck_id
           where f.company_id = %s order by f.purchased_at desc limit 6""",
        (company_id,),
    )
    upcoming = rows(
        """select m.*, t.unit_number from maintenance_orders m join trucks t on t.id = m.truck_id
           where m.company_id = %s and m.status <> 'done'
           order by coalesce(m.scheduled_for, current_date) limit 6""",
        (company_id,),
    )
    return render_template(
        "dashboard.html", title="Dashboard", active="/", summary=summary,
        attention=attention, breakdowns=breakdowns, faults=faults, fuel=fuel, pins=pins,
        upcoming=upcoming, documents=expiring_documents(company_id)[:8], fleet_size=len(fleet),
    )
