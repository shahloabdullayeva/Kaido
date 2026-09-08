from flask import Blueprint, flash, g, redirect, render_template, request

from .. import forms
from ..audit import audit
from ..auth import login_required
from ..db import execute, one, rows
from ..tenancy import company_required, role_required

bp = Blueprint("faults", __name__)


@bp.get("/faults")
@login_required
@company_required
def index():
    scope = forms.pick(request.args.get("scope"), ["active", "all", "cleared"], "active")
    clause = ""
    if scope == "active":
        clause = " and f.cleared_at is null"
    elif scope == "cleared":
        clause = " and f.cleared_at is not null"
    items = rows(
        f"""select f.*, t.unit_number, t.make, t.model, u.name as acknowledged_name
            from fault_events f join trucks t on t.id = f.truck_id
            left join users u on u.id = f.acknowledged_by
            where f.company_id = %s{clause}
            order by f.last_seen_at desc limit 200""",
        (g.company["id"],),
    )
    integration = one(
        "select * from integrations where company_id = %s and provider = 'samsara'", (g.company["id"],)
    )
    return render_template("faults/list.html", title="Faults", active="/faults", items=items,
                           scope=scope, integration=integration)


@bp.post("/faults/<int:fault_id>/acknowledge")
@login_required
@role_required("dispatcher")
def acknowledge(fault_id):
    execute(
        """update fault_events set acknowledged_at = now(), acknowledged_by = %s
           where id = %s and company_id = %s""",
        (g.session["user_id"], fault_id, g.company["id"]),
    )
    audit("fault.acknowledged", "fault_event", fault_id)
    flash("Fault acknowledged.", "ok")
    return redirect(request.form.get("back") or "/faults")


@bp.post("/faults/<int:fault_id>/clear")
@login_required
@role_required("mechanic")
def clear(fault_id):
    execute(
        "update fault_events set cleared_at = now() where id = %s and company_id = %s and cleared_at is null",
        (fault_id, g.company["id"]),
    )
    audit("fault.cleared", "fault_event", fault_id, {"by": "manual"})
    flash("Fault marked cleared.", "ok")
    return redirect(request.form.get("back") or "/faults")
