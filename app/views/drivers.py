from flask import Blueprint, flash, g, redirect, render_template, request

from .. import forms
from ..audit import audit
from ..auth import login_required
from ..db import execute, insert, one, rows
from ..tenancy import company_required, role_required

bp = Blueprint("drivers", __name__)

STATUSES = ["active", "inactive"]


def form_values(source):
    return {
        "name": forms.required(source.get("name"), 120),
        "phone": forms.text(source.get("phone"), 40),
        "email": forms.text(source.get("email"), 200),
        "telegram_username": forms.text((source.get("telegram_username") or "").lstrip("@"), 60),
        "license_number": forms.text(source.get("license_number"), 40),
        "license_state": forms.text(source.get("license_state"), 4),
        "license_expires": forms.day(source.get("license_expires")),
        "medical_expires": forms.day(source.get("medical_expires")),
        "hired_on": forms.day(source.get("hired_on")),
        "status": forms.pick(source.get("status"), STATUSES, "active"),
        "notes": forms.text(source.get("notes"), 2000),
    }


@bp.get("/drivers")
@login_required
@company_required
def index():
    drivers = rows(
        """select d.*, (select count(*) from trucks t where t.driver_id = d.id) as truck_count,
             (select string_agg(t.unit_number, ', ' order by t.unit_number) from trucks t where t.driver_id = d.id) as units
           from drivers d where d.company_id = %s order by d.status, lower(d.name)""",
        (g.company["id"],),
    )
    return render_template("drivers/list.html", title="Drivers", active="/drivers", drivers=drivers)


@bp.get("/drivers/new")
@login_required
@role_required("dispatcher")
def new():
    return render_template("drivers/form.html", title="Add driver", active="/drivers",
                           driver={"status": "active"}, statuses=STATUSES, mode="new")


@bp.post("/drivers")
@login_required
@role_required("dispatcher")
def create():
    values = form_values(request.form)
    if not values["name"]:
        flash("A name is required.", "bad")
        return redirect("/drivers/new")
    driver = insert(
        """insert into drivers (company_id, name, phone, email, telegram_username, license_number, license_state,
             license_expires, medical_expires, hired_on, status, notes)
           values (%(company_id)s, %(name)s, %(phone)s, %(email)s, %(telegram_username)s, %(license_number)s,
             %(license_state)s, %(license_expires)s, %(medical_expires)s, %(hired_on)s, %(status)s, %(notes)s)
           returning *""",
        {**values, "company_id": g.company["id"]},
    )
    audit("driver.created", "driver", driver["id"], {"name": driver["name"]})
    flash(f"{driver['name']} added.", "ok")
    return redirect("/drivers")


@bp.get("/drivers/<int:driver_id>")
@login_required
@company_required
def detail(driver_id):
    driver = one("select * from drivers where id = %s and company_id = %s", (driver_id, g.company["id"]))
    if not driver:
        return render_template("errors/404.html"), 404
    return render_template("drivers/form.html", title=driver["name"], active="/drivers",
                           driver=driver, statuses=STATUSES, mode="edit")


@bp.post("/drivers/<int:driver_id>")
@login_required
@role_required("dispatcher")
def update(driver_id):
    driver = one("select * from drivers where id = %s and company_id = %s", (driver_id, g.company["id"]))
    if not driver:
        return render_template("errors/404.html"), 404
    values = form_values(request.form)
    execute(
        """update drivers set name = %(name)s, phone = %(phone)s, email = %(email)s,
             telegram_username = %(telegram_username)s, license_number = %(license_number)s,
             license_state = %(license_state)s, license_expires = %(license_expires)s,
             medical_expires = %(medical_expires)s, hired_on = %(hired_on)s, status = %(status)s,
             notes = %(notes)s, updated_at = now()
           where id = %(id)s and company_id = %(company_id)s""",
        {**values, "id": driver_id, "company_id": g.company["id"]},
    )
    audit("driver.updated", "driver", driver_id, {"name": values["name"]})
    flash("Driver updated.", "ok")
    return redirect("/drivers")
