from flask import Blueprint, flash, g, redirect, render_template, request

from .. import forms
from ..audit import audit
from ..auth import login_required
from ..db import execute, one, rows
from ..samsara import SamsaraError
from ..security import mask_token
from ..sync import connect, disconnect, get_integration, import_vehicles, sync_company
from ..tenancy import active_trucks, role_required

bp = Blueprint("integrations", __name__)


@bp.get("/integrations")
@login_required
@role_required("admin")
def index():
    company_id = g.company["id"]
    integration = get_integration(company_id)
    links = rows(
        """select v.*, t.unit_number from vehicle_links v
           left join trucks t on t.id = v.truck_id
           where v.company_id = %s order by v.truck_id nulls first, lower(coalesce(v.external_name, v.external_id))""",
        (company_id,),
    )
    runs = rows("select * from sync_runs where company_id = %s order by started_at desc limit 8", (company_id,))
    counts = {
        "linked": sum(1 for link in links if link["truck_id"]),
        "unlinked": sum(1 for link in links if not link["truck_id"]),
        "trucks": one("select count(*) as n from trucks where company_id = %s and status <> 'sold'", (company_id,))["n"],
    }
    return render_template("integrations/index.html", title="Integrations", active="/integrations",
                           integration=integration, links=links, runs=runs, counts=counts,
                           trucks=active_trucks())


@bp.post("/integrations/samsara/connect")
@login_required
@role_required("admin")
def samsara_connect():
    token = forms.text(request.form.get("token"), 200)
    if not token:
        flash("Paste the Samsara API token.", "bad")
        return redirect("/integrations")
    try:
        connect(g.company["id"], token, g.session["user_id"])
    except SamsaraError as err:
        flash(str(err), "bad")
        return redirect("/integrations")
    audit("integration.connected", "integration", "samsara", {"token": mask_token(token)})
    flash("Samsara connected. Run a sync to pull vehicles.", "ok")
    return redirect("/integrations")


@bp.post("/integrations/samsara/disconnect")
@login_required
@role_required("admin")
def samsara_disconnect():
    disconnect(g.company["id"])
    audit("integration.disconnected", "integration", "samsara")
    flash("Samsara disconnected. Stored data stays, syncing stops.", "warn")
    return redirect("/integrations")


@bp.post("/integrations/samsara/sync")
@login_required
@role_required("admin")
def samsara_sync():
    result = sync_company(g.company["id"])
    audit("integration.sync", "integration", "samsara", result)
    if result.get("status") == "error":
        flash(f"Sync failed: {result.get('error')}", "bad")
    else:
        flash(
            f"Synced {result['vehicles']} vehicles · {result['odometer']} odometer updates · "
            f"{result['faults_opened']} new faults · {result['faults_cleared']} cleared"
            + (f" · {result['unlinked']} vehicles not linked to a truck" if result["unlinked"] else ""),
            "ok",
        )
    return redirect("/integrations")


@bp.post("/integrations/samsara/import")
@login_required
@role_required("admin")
def samsara_import():
    try:
        result = import_vehicles(g.company["id"], g.session["user_id"])
    except SamsaraError as err:
        flash(str(err), "bad")
        return redirect("/integrations")
    audit("integration.vehicles_imported", "integration", "samsara", result)
    if result["created"] or result["matched"]:
        flash(
            f"Created {result['created']} trucks from Samsara"
            + (f", matched {result['matched']} to trucks already here" if result["matched"] else "")
            + ". Run a sync to pull their odometer and faults.",
            "ok",
        )
    else:
        flash("Every Samsara vehicle is already linked to a truck.", "info")
    return redirect("/integrations")


@bp.post("/integrations/samsara/vehicles/<int:link_id>")
@login_required
@role_required("admin")
def link_vehicle(link_id):
    truck_id = forms.integer(request.form.get("truck_id"))
    if truck_id:
        truck = one("select id from trucks where id = %s and company_id = %s", (truck_id, g.company["id"]))
        if not truck:
            flash("That truck is not in this company.", "bad")
            return redirect("/integrations")
    execute(
        "update vehicle_links set truck_id = %s where id = %s and company_id = %s",
        (truck_id, link_id, g.company["id"]),
    )
    audit("integration.vehicle_linked", "vehicle_link", link_id, {"truck_id": truck_id})
    flash("Vehicle mapping saved.", "ok")
    return redirect("/integrations")
