from flask import Blueprint, flash, g, redirect, render_template, request

from .. import forms
from ..audit import audit
from ..auth import login_required
from ..db import execute, insert, one, rows
from ..tenancy import company_required, role_required

bp = Blueprint("trailers", __name__)

KINDS = {"dry_van": "Dry van", "reefer": "Reefer", "flatbed": "Flatbed", "step_deck": "Step deck", "tanker": "Tanker",
         "lowboy": "Lowboy", "container": "Container chassis", "other": "Other"}
STATUSES = {"active": "Active", "in_shop": "In shop", "out_of_service": "Out of service", "sold": "Sold"}


def values(source):
    return {
        "unit_number": forms.text(source.get("unit_number"), 40),
        "kind": forms.pick(source.get("kind"), list(KINDS), "dry_van"),
        "vin": (forms.text(source.get("vin"), 17) or "").upper() or None,
        "plate": forms.text(source.get("plate"), 20),
        "plate_state": (forms.text(source.get("plate_state"), 4) or "").upper() or None,
        "year": forms.integer(source.get("year")),
        "make": forms.text(source.get("make"), 60),
        "length_ft": forms.integer(source.get("length_ft")),
        "status": forms.pick(source.get("status"), list(STATUSES), "active"),
        "truck_id": forms.integer(source.get("truck_id")),
        "notes": forms.text(source.get("notes"), 2000),
    }


def trucks(company_id):
    return rows("select id, unit_number from trucks where company_id = %s and status <> 'sold' order by lower(unit_number)",
                (company_id,))


@bp.get("/trailers")
@login_required
@company_required
def index():
    status = forms.pick(request.args.get("status"), ["all", *STATUSES], "all")
    clause = "" if status == "all" else " and r.status = %(status)s"
    found = rows(
        f"""select r.*, t.unit_number as truck_unit, t.location as truck_location,
            from trailers r left join trucks t on t.id = r.truck_id
            where r.company_id = %(company)s{clause} order by r.status = 'sold', lower(r.unit_number)""",
        {"company": g.company["id"], "status": status},
    )
    return render_template("trailers/list.html", title="Trailers", active="/trucks", trailers=found, kinds=KINDS,
                           statuses=STATUSES, status=status)


@bp.get("/trailers/new")
@login_required
@role_required("admin")
def new():
    return render_template("trailers/form.html", title="Add trailer", active="/trucks", trailer={}, kinds=KINDS,
                           statuses=STATUSES, trucks=trucks(g.company["id"]), mode="new")


@bp.post("/trailers")
@login_required
@role_required("admin")
def create():
    data = values(request.form)
    if not data["unit_number"]:
        flash("Trailer number is needed.", "bad")
        return redirect("/trailers/new")
    if one("select 1 from trailers where company_id = %s and lower(unit_number) = lower(%s)", (g.company["id"], data["unit_number"])):
        flash(f"Trailer {data['unit_number']} already exists.", "bad")
        return redirect("/trailers/new")
    data["company_id"] = g.company["id"]
    row = insert(
        """insert into trailers (company_id, unit_number, kind, vin, plate, plate_state, year, make, length_ft, status, truck_id, notes)
           values (%(company_id)s, %(unit_number)s, %(kind)s, %(vin)s, %(plate)s, %(plate_state)s, %(year)s, %(make)s,
                   %(length_ft)s, %(status)s, %(truck_id)s, %(notes)s) returning id""",
        data,
    )
    audit("trailer.create", "trailer", row["id"])
    flash(f"Trailer {data['unit_number']} added.", "ok")
    return redirect(f"/trailers/{row['id']}")


@bp.get("/trailers/<int:trailer_id>")
@login_required
@company_required
def detail(trailer_id):
    trailer = one("""select r.*, t.unit_number as truck_unit, t.location as truck_location, t.located_at as truck_located_at
                     from trailers r left join trucks t on t.id = r.truck_id where r.id = %s and r.company_id = %s""",
                  (trailer_id, g.company["id"]))
    if not trailer:
        return render_template("errors/404.html"), 404
    return render_template("trailers/form.html", title=f"Trailer {trailer['unit_number']}", active="/trucks", trailer=trailer,
                           kinds=KINDS, statuses=STATUSES, trucks=trucks(g.company["id"]), mode="edit")


@bp.post("/trailers/<int:trailer_id>")
@login_required
@role_required("admin")
def update(trailer_id):
    trailer = one("select * from trailers where id = %s and company_id = %s", (trailer_id, g.company["id"]))
    if not trailer:
        return render_template("errors/404.html"), 404
    if request.form.get("delete"):
        execute("delete from trailers where id = %s", (trailer_id,))
        audit("trailer.delete", "trailer", trailer_id)
        flash(f"Trailer {trailer['unit_number']} deleted.", "ok")
        return redirect("/trailers")
    data = values(request.form)
    data["unit_number"] = data["unit_number"] or trailer["unit_number"]
    data["id"] = trailer_id
    execute(
        """update trailers set unit_number = %(unit_number)s, kind = %(kind)s, vin = %(vin)s, plate = %(plate)s,
             plate_state = %(plate_state)s, year = %(year)s, make = %(make)s, length_ft = %(length_ft)s, status = %(status)s,
             truck_id = %(truck_id)s, notes = %(notes)s, updated_at = now() where id = %(id)s""",
        data,
    )
    audit("trailer.update", "trailer", trailer_id)
    flash("Saved.", "ok")
    return redirect(f"/trailers/{trailer_id}")
