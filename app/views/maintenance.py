import re

from flask import Blueprint, flash, g, redirect, render_template, request

from .. import advisor, forms, shops as shop_search
from ..audit import audit
from ..auth import login_required
from ..config import config
from ..db import execute, insert, one, rows
from ..tenancy import active_trucks, company_required, role_required

bp = Blueprint("maintenance", __name__)

KINDS = ["oil", "pm_a", "pm_b", "repair", "tire", "annual_inspection", "recall"]
KIND_LABELS = {
    "oil": "Oil & filter",
    "pm_a": "PM-A",
    "pm_b": "PM-B",
    "repair": "Repair",
    "tire": "Tires",
    "annual_inspection": "DOT annual inspection",
    "recall": "Recall",
}
STATUSES = ["scheduled", "in_progress", "done"]


@bp.get("/maintenance")
@login_required
@company_required
def index():
    status = forms.pick(request.args.get("status"), STATUSES + ["all", "open"], "open")
    params = [g.company["id"]]
    clause = ""
    if status == "open":
        clause = " and m.status <> 'done'"
    elif status != "all":
        clause = " and m.status = %s"
        params.append(status)
    orders = rows(
        f"""select m.*, t.unit_number, d.name as driver_name from maintenance_orders m
            join trucks t on t.id = m.truck_id
            left join drivers d on d.id = m.driver_id
            where m.company_id = %s{clause}
            order by coalesce(m.performed_on, m.scheduled_for) desc nulls first, m.id desc limit 200""",
        tuple(params),
    )
    spend = one(
        """select coalesce(sum(cost), 0) as month_cost, count(*) as month_orders
           from maintenance_orders where company_id = %s and status = 'done'
             and performed_on >= date_trunc('month', current_date)""",
        (g.company["id"],),
    )
    return render_template("maintenance/list.html", title="Maintenance", active="/maintenance",
                           orders=orders, status=status, statuses=STATUSES, spend=spend, kind_labels=KIND_LABELS)


@bp.get("/maintenance/new")
@login_required
@role_required("admin")
def new():
    return render_template("maintenance/form.html", title="New work order", active="/maintenance",
                           trucks=active_trucks(), kinds=KINDS, kind_labels=KIND_LABELS, statuses=STATUSES,
                           truck_id=forms.integer(request.args.get("truck_id")), order=None)


@bp.post("/maintenance")
@login_required
@role_required("admin")
def create():
    truck_id = forms.integer(request.form.get("truck_id"))
    truck = one("select * from trucks where id = %s and company_id = %s", (truck_id, g.company["id"]))
    if not truck:
        flash("Pick a truck.", "bad")
        return redirect("/maintenance/new")
    description = forms.required(request.form.get("description"), 2000)
    if not description:
        flash("Describe the work.", "bad")
        return redirect("/maintenance/new")
    status = forms.pick(request.form.get("status"), STATUSES, "scheduled")
    kind = forms.pick(request.form.get("kind"), KINDS, "repair")
    performed_on = forms.day(request.form.get("performed_on"))
    odometer = forms.integer(request.form.get("odometer"))
    order = insert(
        """insert into maintenance_orders (company_id, truck_id, driver_id, kind, status, scheduled_for, performed_on,
             odometer, vendor, invoice_no, cost, description, next_due_on, next_due_odometer, created_by)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning *""",
        (
            g.company["id"], truck_id, truck["driver_id"], kind, status,
            forms.day(request.form.get("scheduled_for")), performed_on, odometer,
            forms.text(request.form.get("vendor"), 160), forms.text(request.form.get("invoice_no"), 40),
            forms.decimal(request.form.get("cost")), description,
            forms.day(request.form.get("next_due_on")), forms.integer(request.form.get("next_due_odometer")),
            g.session["user_id"],
        ),
    )
    apply_completion(order, truck)
    audit("maintenance.created", "maintenance_order", order["id"], {"unit": truck["unit_number"], "kind": kind, "status": status})
    flash("Work order saved.", "ok")
    return redirect("/maintenance")


def apply_completion(order, truck):
    if order["status"] != "done":
        return
    if order["odometer"]:
        execute(
            "insert into odometer_readings (company_id, truck_id, miles, source, created_by) values (%s, %s, %s, 'service', %s)",
            (order["company_id"], order["truck_id"], order["odometer"], order["created_by"]),
        )
        if order["odometer"] >= (truck["odometer"] or 0):
            execute("update trucks set odometer = %s, odometer_at = now() where id = %s", (order["odometer"], order["truck_id"]))
    if order["kind"] == "annual_inspection" and order["performed_on"]:
        execute("update trucks set annual_inspection_on = %s, updated_at = now() where id = %s",
                (order["performed_on"], order["truck_id"]))


NOISE_WORDS = {"the", "inc", "llc", "co", "company", "service", "services", "center",
               "centre", "truck", "trucks", "repair", "shop", "stop", "and", "auto", "of"}


def _tokens(name):
    words = re.findall(r"[a-z0-9]+", (name or "").lower())
    return {word for word in words if word not in NOISE_WORDS and len(word) > 1}


def vendor_history(company_id):
    history = rows(
        """select vendor, count(*) as visits, avg(cost) as average, max(performed_on) as last
           from maintenance_orders
           where company_id = %s and kind = 'oil' and status = 'done'
             and vendor is not null and vendor <> '' and cost is not null
           group by vendor""",
        (company_id,),
    )
    return [dict(row, tokens=_tokens(row["vendor"])) for row in history]


def match_history(shop_name, history):
    wanted = _tokens(shop_name)
    if not wanted:
        return None
    best, best_score = None, 0
    for row in history:
        shared = wanted & row["tokens"]
        if not shared:
            continue
        score = len(shared) / max(len(wanted | row["tokens"]), 1)
        if score > best_score:
            best, best_score = row, score
    if best and best_score >= 0.34:
        return {"vendor": best["vendor"], "visits": best["visits"],
                "average": float(best["average"]), "last": best["last"].strftime("%b %Y")}
    return None


def detour_for(miles):
    cost_per_mile = config.DIESEL_PRICE / max(config.TRUCK_MPG, 1)
    round_trip = miles * 2
    hours = round_trip / max(config.ROAD_SPEED_MPH, 1)
    spell = f"{round(hours * 60)} min" if hours < 1 else f"{hours:.1f} h"
    return {"miles": round(round_trip, 1),
            "cost": round(round_trip * cost_per_mile, 2),
            "hours": round(hours, 1),
            "spell": spell}


@bp.get("/maintenance/shops/<int:truck_id>")
@login_required
@role_required("admin")
def shops(truck_id):
    truck = one(
        """select t.*, d.name as driver_name from trucks t
           left join drivers d on d.id = t.driver_id
           where t.id = %s and t.company_id = %s""",
        (truck_id, g.company["id"]),
    )
    if not truck:
        return render_template("errors/404.html"), 404
    if truck["latitude"] is None or truck["longitude"] is None:
        return render_template("maintenance/_shops.html", truck=truck, found=[],
                               problem="No position for this truck yet — Samsara has not reported one.")
    try:
        found, meta = shop_search.nearby(truck["latitude"], truck["longitude"],
                                         radius_miles=config.SHOP_RADIUS_MILES)
    except Exception as err:
        return render_template("maintenance/_shops.html", truck=truck, found=[],
                               problem=f"Could not reach OpenStreetMap just now ({str(err)[:90]}).")
    history = vendor_history(g.company["id"])
    for shop in found:
        shop["history"] = match_history(shop["name"], history)
        shop["detour"] = detour_for(shop["miles"])
    average = one(
        """select avg(cost) as average from maintenance_orders
           where company_id = %s and kind = 'oil' and status = 'done' and cost is not null""",
        (g.company["id"],),
    )
    fleet_average = float(average["average"]) if average and average["average"] else None
    advice = advisor.shop_advice(truck, found, fleet_average)
    notes = {}
    if advice:
        notes = {note.number: note.note for note in advice.notes}
    return render_template("maintenance/_shops.html", truck=truck, found=found, meta=meta,
                           notes=notes, advice=advice, fleet_average=fleet_average,
                           ai_on=advisor.available(), ai_paused=advisor.over_budget(),
                           problem=None)


@bp.get("/maintenance/<int:order_id>")
@login_required
@company_required
def detail(order_id):
    order = one(
        """select m.*, t.unit_number, d.name as driver_name from maintenance_orders m
           join trucks t on t.id = m.truck_id
           left join drivers d on d.id = m.driver_id
           where m.id = %s and m.company_id = %s""",
        (order_id, g.company["id"]),
    )
    if not order:
        return render_template("errors/404.html"), 404
    return render_template("maintenance/form.html", title=f"Work order #{order['id']}", active="/maintenance",
                           trucks=active_trucks(), kinds=KINDS, kind_labels=KIND_LABELS, statuses=STATUSES,
                           order=order, truck_id=order["truck_id"])


@bp.post("/maintenance/<int:order_id>")
@login_required
@role_required("admin")
def update(order_id):
    order = one("select * from maintenance_orders where id = %s and company_id = %s", (order_id, g.company["id"]))
    if not order:
        return render_template("errors/404.html"), 404
    status = forms.pick(request.form.get("status"), STATUSES, order["status"])
    performed_on = forms.day(request.form.get("performed_on"))
    truck = one("select * from trucks where id = %s and company_id = %s", (order["truck_id"], g.company["id"]))
    updated = insert(
        """update maintenance_orders set driver_id = %s, kind = %s, status = %s, scheduled_for = %s, performed_on = %s,
             odometer = %s, vendor = %s, invoice_no = %s, cost = %s, description = %s,
             next_due_on = %s, next_due_odometer = %s, updated_at = now()
           where id = %s and company_id = %s returning *""",
        (
            (truck or {}).get("driver_id"),
            forms.pick(request.form.get("kind"), KINDS, order["kind"]), status,
            forms.day(request.form.get("scheduled_for")), performed_on,
            forms.integer(request.form.get("odometer")), forms.text(request.form.get("vendor"), 160),
            forms.text(request.form.get("invoice_no"), 40), forms.decimal(request.form.get("cost")),
            forms.required(request.form.get("description"), 2000),
            forms.day(request.form.get("next_due_on")), forms.integer(request.form.get("next_due_odometer")),
            order_id, g.company["id"],
        ),
    )
    apply_completion(updated, truck)
    audit("maintenance.updated", "maintenance_order", order_id, {"status": status})
    flash("Work order updated.", "ok")
    return redirect("/maintenance")
