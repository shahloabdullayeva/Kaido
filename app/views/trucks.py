from flask import Blueprint, flash, g, redirect, render_template, request

from .. import forms, sheets
from ..audit import audit
from ..auth import login_required
from ..db import execute, insert, one, rows
from ..queries import fuel_economy, service_status
from ..tenancy import active_drivers, company_required, role_required, scoped_truck

bp = Blueprint("trucks", __name__)

STATUSES = ["active", "shop", "out_of_service", "sold"]
DUTY = ["standard", "severe"]


def form_values(source):
    return {
        "unit_number": forms.required(source.get("unit_number"), 40),
        "vin": forms.text(source.get("vin"), 24),
        "engine": forms.text(source.get("engine"), 80),
        "make": forms.text(source.get("make"), 60),
        "model": forms.text(source.get("model"), 60),
        "year": forms.integer(source.get("year")),
        "plate": forms.text(source.get("plate"), 20),
        "plate_state": forms.text(source.get("plate_state"), 4),
        "status": forms.pick(source.get("status"), STATUSES, "active"),
        "duty_cycle": forms.pick(source.get("duty_cycle"), DUTY, "standard"),
        "odometer": forms.integer(source.get("odometer")) or 0,
        "driver_id": forms.integer(source.get("driver_id")),
        "fuel_card_last4": forms.text(source.get("fuel_card_last4"), 4),
        "oil_interval_miles": forms.integer(source.get("oil_interval_miles")) or 25000,
        "registration_expires": forms.day(source.get("registration_expires")),
        "annual_inspection_on": forms.day(source.get("annual_inspection_on")),
        "insurance_expires": forms.day(source.get("insurance_expires")),
        "notes": forms.text(source.get("notes"), 2000),
    }


@bp.get("/trucks")
@login_required
@company_required
def index():
    status = forms.pick(request.args.get("status"), STATUSES + ["all", "outside"], "all")
    from ..queries import attention_score, trucks_with_service
    fleet = trucks_with_service(g.company["id"])
    for truck in fleet:
        truck["statuses"] = service_status(truck)
        truck["score"] = attention_score(truck)
    if status == "outside":
        fleet = [t for t in fleet if t["is_outside"]]
    else:
        fleet = [t for t in fleet if not t["is_outside"]]
        if status != "all":
            fleet = [t for t in fleet if t["status"] == status]
    return render_template("trucks/list.html", title="Trucks", active="/trucks", fleet=fleet, status=status, statuses=STATUSES)


BASELINE_NOTE = "Last oil change before Kaido, entered as a starting point for reminders"


def baseline_trucks():
    return rows(
        """select t.id, t.unit_number, t.odometer, t.oil_interval_miles, d.name as driver_name,
             (select max(m.odometer) from maintenance_orders m
               where m.truck_id = t.id and m.kind = 'oil' and m.status = 'done') as last_oil_odometer,
             (select max(m.performed_on) from maintenance_orders m
               where m.truck_id = t.id and m.kind = 'oil' and m.status = 'done') as last_oil_on
           from trucks t left join drivers d on d.id = t.driver_id
           where t.company_id = %s and t.status <> 'sold' and not t.is_outside
           order by lower(t.unit_number)""",
        (g.company["id"],),
    )


def save_baseline(truck, miles, performed_on, vendor):
    if miles is None or miles <= 0:
        return "no miles"
    if truck["odometer"] and miles > truck["odometer"] + 1000:
        return f"{miles:,} is more than the truck's odometer ({truck['odometer']:,})"
    duplicate = one(
        "select id from maintenance_orders where truck_id = %s and kind = 'oil' and status = 'done' and odometer = %s",
        (truck["id"], miles),
    )
    if duplicate:
        return "already on record"
    insert(
        """insert into maintenance_orders (company_id, truck_id, driver_id, kind, status, performed_on, odometer,
             vendor, description, created_by)
           values (%s, %s, null, 'oil', 'done', %s, %s, %s, %s, %s) returning id""",
        (g.company["id"], truck["id"], performed_on, miles, vendor, BASELINE_NOTE, g.session["user_id"]),
    )
    return None


@bp.get("/trucks/baselines")
@login_required
@role_required("admin")
def baselines():
    fleet = baseline_trucks()
    missing = sum(1 for truck in fleet if truck["last_oil_odometer"] is None)
    return render_template("trucks/baselines.html", title="Oil baselines", active="/trucks",
                           fleet=fleet, missing=missing, problems=[])


@bp.post("/trucks/baselines")
@login_required
@role_required("admin")
def save_baselines():
    fleet = {truck["id"]: truck for truck in baseline_trucks()}
    saved, problems = 0, []
    upload = request.files.get("sheet")
    if upload and upload.filename:
        try:
            headers, records = sheets.read(upload.filename, upload.read())
        except Exception as err:
            flash(f"Could not read that file: {str(err)[:120]}", "bad")
            return redirect("/trucks/baselines")
        unit_col = sheets.find(headers, "unit", "unit number", "truck", "unit no")
        miles_col = sheets.find(headers, "odometer", "miles", "mileage", "last oil", "oil odometer")
        date_col = sheets.find(headers, "date", "oil date", "last oil date", "performed")
        vendor_col = sheets.find(headers, "shop", "vendor", "where")
        if not unit_col or not miles_col:
            flash("The sheet needs a unit column and a miles (odometer) column.", "bad")
            return redirect("/trucks/baselines")
        by_unit = {sheets.unit_key(truck["unit_number"]): truck for truck in fleet.values()}
        for record in records:
            unit = sheets.value(record, unit_col)
            if unit is None:
                continue
            truck = by_unit.get(sheets.unit_key(unit))
            if not truck:
                problems.append(f"Unit {unit}: not found in this company")
                continue
            miles = sheets.number(sheets.value(record, miles_col))
            moment = sheets.when(sheets.value(record, date_col)) if date_col else None
            problem = save_baseline(truck, int(miles) if miles else None, moment.date() if moment else None,
                                    forms.text(sheets.value(record, vendor_col), 160) if vendor_col else None)
            if problem and problem != "no miles":
                problems.append(f"Unit {truck['unit_number']}: {problem}")
            elif not problem:
                saved += 1
    else:
        for truck_id, truck in fleet.items():
            miles = forms.integer(request.form.get(f"miles_{truck_id}"))
            if miles is None:
                continue
            problem = save_baseline(truck, miles, forms.day(request.form.get(f"date_{truck_id}")),
                                    forms.text(request.form.get(f"vendor_{truck_id}"), 160))
            if problem and problem != "no miles":
                problems.append(f"Unit {truck['unit_number']}: {problem}")
            elif not problem:
                saved += 1
    audit("truck.oil_baselines", "company", g.company["id"], {"saved": saved, "problems": len(problems)})
    if saved:
        flash(f"Saved {saved} oil {'baseline' if saved == 1 else 'baselines'}. Reminders will now count from them.", "ok")
    elif not problems:
        flash("Nothing to save. Fill in at least one truck's miles.", "bad")
    fleet_now = baseline_trucks()
    return render_template("trucks/baselines.html", title="Oil baselines", active="/trucks", fleet=fleet_now,
                           missing=sum(1 for truck in fleet_now if truck["last_oil_odometer"] is None),
                           problems=problems)


@bp.get("/trucks/new")
@login_required
@role_required("admin")
def new():
    return render_template(
        "trucks/form.html", title="Add truck", active="/trucks",
        truck={"status": "active", "duty_cycle": "standard", "oil_interval_miles": 25000, "odometer": 0},
        drivers=active_drivers(), statuses=STATUSES, duty=DUTY, mode="new",
    )


@bp.post("/trucks")
@login_required
@role_required("admin")
def create():
    values = form_values(request.form)
    if not values["unit_number"]:
        flash("A unit number is required.", "bad")
        return redirect("/trucks/new")
    existing = one(
        "select id from trucks where company_id = %s and lower(unit_number) = lower(%s)",
        (g.company["id"], values["unit_number"]),
    )
    if existing:
        flash(f"Unit {values['unit_number']} already exists.", "bad")
        return redirect("/trucks/new")
    truck = insert(
        """insert into trucks (company_id, unit_number, vin, engine, engine_source, make, model, year, plate, plate_state, status,
             duty_cycle, odometer, odometer_at, driver_id, fuel_card_last4, oil_interval_miles,
             registration_expires, annual_inspection_on, insurance_expires, notes)
           values (%(company_id)s, %(unit_number)s, %(vin)s, %(engine)s, case when %(engine)s::text is null then null else 'manual' end, %(make)s, %(model)s, %(year)s, %(plate)s, %(plate_state)s,
             %(status)s, %(duty_cycle)s, %(odometer)s, now(), %(driver_id)s, %(fuel_card_last4)s, %(oil_interval_miles)s,
             %(registration_expires)s, %(annual_inspection_on)s, %(insurance_expires)s, %(notes)s)
           returning *""",
        {**values, "company_id": g.company["id"]},
    )
    if values["odometer"]:
        execute(
            """insert into odometer_readings (company_id, truck_id, miles, source, created_by)
               values (%s, %s, %s, 'manual', %s)""",
            (g.company["id"], truck["id"], values["odometer"], g.session["user_id"]),
        )
    audit("truck.created", "truck", truck["id"], {"unit": truck["unit_number"]})
    flash(f"Unit {truck['unit_number']} added.", "ok")
    return redirect(f"/trucks/{truck['id']}")


@bp.get("/trucks/<int:truck_id>")
@login_required
@company_required
def detail(truck_id):
    truck = scoped_truck(truck_id)
    if not truck:
        return render_template("errors/404.html"), 404
    truck["driver_name"] = None
    if truck["driver_id"]:
        driver = one("select name from drivers where id = %s", (truck["driver_id"],))
        truck["driver_name"] = driver["name"] if driver else None
    history = rows(
        "select * from maintenance_orders where truck_id = %s order by coalesce(performed_on, scheduled_for) desc nulls last, id desc limit 20",
        (truck_id,),
    )
    last_oil = one(
        """select max(odometer) as odometer, max(performed_on) as performed_on
           from maintenance_orders where truck_id = %s and kind = 'oil' and status = 'done'""",
        (truck_id,),
    )
    enriched = dict(truck)
    enriched["last_oil_odometer"] = last_oil["odometer"] if last_oil else None
    fuel = rows("select * from fuel_transactions where truck_id = %s order by purchased_at desc limit 10", (truck_id,))
    faults = rows("select * from fault_events where truck_id = %s order by last_seen_at desc limit 10", (truck_id,))
    breakdowns = rows("select * from breakdowns where truck_id = %s order by occurred_at desc limit 10", (truck_id,))
    link = one("select * from vehicle_links where truck_id = %s", (truck_id,))
    return render_template(
        "trucks/detail.html", title=f"Unit {truck['unit_number']}", active="/trucks",
        truck=truck, statuses=service_status(enriched), history=history, fuel=fuel,
        faults=faults, breakdowns=breakdowns, economy=fuel_economy(truck_id), link=link,
        last_oil=last_oil,
    )


@bp.get("/trucks/<int:truck_id>/edit")
@login_required
@role_required("admin")
def edit(truck_id):
    truck = scoped_truck(truck_id)
    if not truck:
        return render_template("errors/404.html"), 404
    return render_template(
        "trucks/form.html", title=f"Edit unit {truck['unit_number']}", active="/trucks",
        truck=truck, drivers=active_drivers(), statuses=STATUSES, duty=DUTY, mode="edit",
    )


@bp.post("/trucks/<int:truck_id>")
@login_required
@role_required("admin")
def update(truck_id):
    truck = scoped_truck(truck_id)
    if not truck:
        return render_template("errors/404.html"), 404
    values = form_values(request.form)
    execute(
        """update trucks set unit_number = %(unit_number)s, vin = %(vin)s,
             engine = %(engine)s,
             engine_source = case when %(engine)s::text is null then null
                                  when %(engine)s::text is not distinct from engine then engine_source else 'manual' end,
             engine_checked_at = case when vin is distinct from %(vin)s::text then null else engine_checked_at end,
             make = %(make)s, model = %(model)s,
             year = %(year)s, plate = %(plate)s, plate_state = %(plate_state)s, status = %(status)s,
             duty_cycle = %(duty_cycle)s, driver_id = %(driver_id)s, fuel_card_last4 = %(fuel_card_last4)s,
             oil_interval_miles = %(oil_interval_miles)s, registration_expires = %(registration_expires)s,
             annual_inspection_on = %(annual_inspection_on)s, insurance_expires = %(insurance_expires)s,
             notes = %(notes)s, updated_at = now()
           where id = %(id)s and company_id = %(company_id)s""",
        {**values, "id": truck_id, "company_id": g.company["id"]},
    )
    audit("truck.updated", "truck", truck_id, {"unit": values["unit_number"]})
    flash("Truck updated.", "ok")
    return redirect(f"/trucks/{truck_id}")


@bp.post("/trucks/<int:truck_id>/odometer")
@login_required
@role_required("admin")
def odometer(truck_id):
    truck = scoped_truck(truck_id)
    if not truck:
        return render_template("errors/404.html"), 404
    miles = forms.integer(request.form.get("miles"))
    if not miles or miles < 0:
        flash("Enter a valid odometer reading.", "bad")
        return redirect(f"/trucks/{truck_id}")
    execute(
        "insert into odometer_readings (company_id, truck_id, miles, source, created_by) values (%s, %s, %s, 'manual', %s)",
        (g.company["id"], truck_id, miles, g.session["user_id"]),
    )
    if miles >= (truck["odometer"] or 0):
        execute("update trucks set odometer = %s, odometer_at = now(), updated_at = now() where id = %s", (miles, truck_id))
    audit("truck.odometer", "truck", truck_id, {"miles": miles})
    flash("Odometer recorded.", "ok")
    return redirect(f"/trucks/{truck_id}")
