from flask import Blueprint, flash, g, redirect, render_template, request

from .. import forms
from ..audit import audit
from ..auth import login_required
from ..db import execute, insert, one, rows
from ..tenancy import active_drivers, active_trucks, company_required, role_required

bp = Blueprint("breakdowns", __name__)

STATUSES = ["open", "towing", "in_shop", "resolved"]
SEVERITIES = ["low", "medium", "high"]


@bp.get("/breakdowns")
@login_required
@company_required
def index():
    status = forms.pick(request.args.get("status"), STATUSES + ["all", "open_all"], "open_all")
    params = [g.company["id"]]
    clause = ""
    if status == "open_all":
        clause = " and b.status <> 'resolved'"
    elif status != "all":
        clause = " and b.status = %s"
        params.append(status)
    items = rows(
        f"""select b.*, t.unit_number, d.name as driver_name
            from breakdowns b join trucks t on t.id = b.truck_id
            left join drivers d on d.id = b.driver_id
            where b.company_id = %s{clause}
            order by b.occurred_at desc limit 200""",
        tuple(params),
    )
    return render_template("breakdowns/list.html", title="Breakdowns", active="/breakdowns",
                           items=items, status=status, statuses=STATUSES)


@bp.get("/breakdowns/new")
@login_required
@role_required("dispatcher")
def new():
    return render_template("breakdowns/form.html", title="Report breakdown", active="/breakdowns",
                           trucks=active_trucks(), drivers=active_drivers(), severities=SEVERITIES,
                           truck_id=forms.integer(request.args.get("truck_id")))


@bp.post("/breakdowns")
@login_required
@role_required("dispatcher")
def create():
    truck_id = forms.integer(request.form.get("truck_id"))
    truck = one("select * from trucks where id = %s and company_id = %s", (truck_id, g.company["id"]))
    if not truck:
        flash("Pick a truck.", "bad")
        return redirect("/breakdowns/new")
    description = forms.required(request.form.get("description"), 2000)
    if not description:
        flash("Describe what happened.", "bad")
        return redirect("/breakdowns/new")
    item = insert(
        """insert into breakdowns (company_id, truck_id, driver_id, occurred_at, status, severity,
             location, description, load_number, created_by)
           values (%s, %s, %s, coalesce(%s, now()), 'open', %s, %s, %s, %s, %s) returning *""",
        (
            g.company["id"], truck_id, forms.integer(request.form.get("driver_id")),
            forms.moment(request.form.get("occurred_at")),
            forms.pick(request.form.get("severity"), SEVERITIES, "medium"),
            forms.text(request.form.get("location"), 200), description,
            forms.text(request.form.get("load_number"), 40), g.session["user_id"],
        ),
    )
    if forms.checkbox(request.form.get("take_out_of_service")):
        execute("update trucks set status = 'out_of_service', updated_at = now() where id = %s", (truck_id,))
    audit("breakdown.created", "breakdown", item["id"], {"unit": truck["unit_number"], "severity": item["severity"]})
    flash(f"Breakdown logged for unit {truck['unit_number']}.", "ok")
    return redirect(f"/breakdowns/{item['id']}")


@bp.get("/breakdowns/<int:breakdown_id>")
@login_required
@company_required
def detail(breakdown_id):
    item = one(
        """select b.*, t.unit_number, t.make, t.model, t.year, d.name as driver_name, d.phone as driver_phone
           from breakdowns b join trucks t on t.id = b.truck_id
           left join drivers d on d.id = b.driver_id
           where b.id = %s and b.company_id = %s""",
        (breakdown_id, g.company["id"]),
    )
    if not item:
        return render_template("errors/404.html"), 404
    updates = rows(
        """select u.*, us.name as author from breakdown_updates u
           left join users us on us.id = u.created_by
           where u.breakdown_id = %s order by u.created_at desc""",
        (breakdown_id,),
    )
    return render_template("breakdowns/detail.html", title=f"Breakdown #{item['id']}", active="/breakdowns",
                           item=item, updates=updates, statuses=STATUSES)


@bp.post("/breakdowns/<int:breakdown_id>/update")
@login_required
@role_required("mechanic")
def add_update(breakdown_id):
    item = one("select * from breakdowns where id = %s and company_id = %s", (breakdown_id, g.company["id"]))
    if not item:
        return render_template("errors/404.html"), 404
    note = forms.required(request.form.get("note"), 2000)
    status = forms.pick(request.form.get("status"), STATUSES, None)
    if not note and not status:
        flash("Add a note or change the status.", "bad")
        return redirect(f"/breakdowns/{breakdown_id}")
    execute(
        "insert into breakdown_updates (breakdown_id, company_id, note, status, created_by) values (%s, %s, %s, %s, %s)",
        (breakdown_id, g.company["id"], note or f"Status changed to {status}", status, g.session["user_id"]),
    )
    if status and status != item["status"]:
        if status == "resolved":
            execute("update breakdowns set status = %s, resolved_at = now(), updated_at = now() where id = %s", (status, breakdown_id))
        else:
            execute("update breakdowns set status = %s, updated_at = now() where id = %s", (status, breakdown_id))
        if status == "in_shop":
            execute("update trucks set status = 'shop', updated_at = now() where id = %s", (item["truck_id"],))
    audit("breakdown.updated", "breakdown", breakdown_id, {"status": status})
    flash("Update added.", "ok")
    return redirect(f"/breakdowns/{breakdown_id}")


@bp.post("/breakdowns/<int:breakdown_id>/resolve")
@login_required
@role_required("mechanic")
def resolve(breakdown_id):
    item = one("select * from breakdowns where id = %s and company_id = %s", (breakdown_id, g.company["id"]))
    if not item:
        return render_template("errors/404.html"), 404
    execute(
        """update breakdowns set status = 'resolved', resolved_at = now(), cause = %s, resolution = %s,
             towing_cost = %s, repair_cost = %s, updated_at = now()
           where id = %s and company_id = %s""",
        (
            forms.text(request.form.get("cause"), 500), forms.text(request.form.get("resolution"), 2000),
            forms.decimal(request.form.get("towing_cost")), forms.decimal(request.form.get("repair_cost")),
            breakdown_id, g.company["id"],
        ),
    )
    if forms.checkbox(request.form.get("return_to_service")):
        execute("update trucks set status = 'active', updated_at = now() where id = %s", (item["truck_id"],))
    if forms.checkbox(request.form.get("create_work_order")):
        insert(
            """insert into maintenance_orders (company_id, truck_id, kind, status, performed_on, cost,
                 description, breakdown_id, created_by)
               values (%s, %s, 'repair', 'done', current_date, %s, %s, %s, %s) returning id""",
            (
                g.company["id"], item["truck_id"], forms.decimal(request.form.get("repair_cost")),
                f"Repair from breakdown #{breakdown_id}: {forms.text(request.form.get('resolution'), 500) or item['description']}",
                breakdown_id, g.session["user_id"],
            ),
        )
    audit("breakdown.resolved", "breakdown", breakdown_id, None)
    flash("Breakdown resolved.", "ok")
    return redirect(f"/breakdowns/{breakdown_id}")
