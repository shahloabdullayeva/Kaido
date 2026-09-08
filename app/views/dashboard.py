from flask import Blueprint, g, render_template

from ..auth import login_required
from ..db import rows
from ..queries import attention_score, company_summary, expiring_documents, service_status, trucks_with_service
from ..tenancy import company_required

bp = Blueprint("dashboard", __name__)


@bp.get("/")
@login_required
@company_required
def index():
    company_id = g.company["id"]
    summary = company_summary(company_id)
    fleet = trucks_with_service(company_id)
    for truck in fleet:
        truck["statuses"] = service_status(truck)
        truck["score"] = attention_score(truck)
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
        attention=attention, breakdowns=breakdowns, faults=faults, fuel=fuel,
        upcoming=upcoming, documents=expiring_documents(company_id)[:8], fleet_size=len(fleet),
    )
