from flask import Blueprint, flash, g, redirect, render_template, request

from .. import forms
from ..audit import audit
from ..auth import login_required
from ..db import execute, insert, one, rows
from ..tenancy import active_drivers, active_trucks, company_required, role_required

bp = Blueprint("fuel", __name__)

FUEL_TYPES = ["diesel", "def", "reefer", "gas"]


@bp.get("/fuel")
@login_required
@company_required
def index():
    truck_id = forms.integer(request.args.get("truck_id"))
    params = [g.company["id"]]
    clause = ""
    if truck_id:
        clause = " and f.truck_id = %s"
        params.append(truck_id)
    entries = rows(
        f"""select f.*, t.unit_number, d.name as driver_name
            from fuel_transactions f
            join trucks t on t.id = f.truck_id
            left join drivers d on d.id = f.driver_id
            where f.company_id = %s{clause}
            order by f.purchased_at desc limit 200""",
        tuple(params),
    )
    totals = one(
        f"""select coalesce(sum(total), 0) as total, coalesce(sum(gallons), 0) as gallons, count(*) as entries
            from fuel_transactions f
            where f.company_id = %s{clause}
              and f.purchased_at >= date_trunc('month', now())""",
        tuple(params),
    )
    return render_template("fuel/list.html", title="Fuel", active="/fuel", entries=entries,
                           totals=totals, trucks=active_trucks(), truck_id=truck_id)


@bp.get("/fuel/new")
@login_required
@role_required("admin")
def new():
    return render_template("fuel/form.html", title="Log fuel", active="/fuel",
                           trucks=active_trucks(), drivers=active_drivers(), fuel_types=FUEL_TYPES,
                           truck_id=forms.integer(request.args.get("truck_id")))


@bp.post("/fuel")
@login_required
@role_required("admin")
def create():
    truck_id = forms.integer(request.form.get("truck_id"))
    truck = one("select * from trucks where id = %s and company_id = %s", (truck_id, g.company["id"]))
    if not truck:
        flash("Pick a truck.", "bad")
        return redirect("/fuel/new")
    gallons = forms.decimal(request.form.get("gallons"))
    total = forms.decimal(request.form.get("total"))
    price = forms.decimal(request.form.get("price_per_gallon"))
    if gallons is None or gallons <= 0:
        flash("Enter the gallons purchased.", "bad")
        return redirect("/fuel/new")
    if total is None and price is not None:
        total = round(gallons * price, 2)
    if price is None and total is not None and gallons:
        price = round(total / gallons, 4)
    if total is None:
        flash("Enter either a total or a price per gallon.", "bad")
        return redirect("/fuel/new")
    purchased_at = forms.moment(request.form.get("purchased_at"))
    odometer = forms.integer(request.form.get("odometer"))
    entry = insert(
        """insert into fuel_transactions (company_id, truck_id, driver_id, purchased_at, gallons, price_per_gallon,
             total, odometer, location, state, fuel_type, card_last4, invoice_no, source, created_by)
           values (%s, %s, %s, coalesce(%s, now()), %s, %s, %s, %s, %s, %s, %s, %s, %s, 'manual', %s)
           returning *""",
        (
            g.company["id"], truck_id, forms.integer(request.form.get("driver_id")), purchased_at,
            gallons, price, total, odometer,
            forms.text(request.form.get("location"), 160), forms.text(request.form.get("state"), 4),
            forms.pick(request.form.get("fuel_type"), FUEL_TYPES, "diesel"),
            forms.text(request.form.get("card_last4"), 4), forms.text(request.form.get("invoice_no"), 40),
            g.session["user_id"],
        ),
    )
    if odometer:
        execute(
            "insert into odometer_readings (company_id, truck_id, miles, source, created_by) values (%s, %s, %s, 'fuel', %s)",
            (g.company["id"], truck_id, odometer, g.session["user_id"]),
        )
        if odometer >= (truck["odometer"] or 0):
            execute("update trucks set odometer = %s, odometer_at = now() where id = %s", (odometer, truck_id))
    audit("fuel.created", "fuel_transaction", entry["id"], {"unit": truck["unit_number"], "total": float(total)})
    flash(f"Fuel logged for unit {truck['unit_number']}.", "ok")
    return redirect("/fuel")
