import re
from datetime import datetime

from flask import Blueprint, flash, g, jsonify, redirect, render_template, request

from .. import advisor, forms, google_places, shops as shop_search, vehicles
from ..work_types import GROUP_LABELS, GROUPS, KIND_LABELS, KINDS, kinds_in
from ..audit import audit
from ..auth import login_required
from ..config import config
from ..db import execute, insert, one, rows
from ..logs import get
from ..tenancy import active_drivers, active_trucks, company_required, role_required

bp = Blueprint("maintenance", __name__)
log = get("maintenance")

STATUSES = ["scheduled", "in_progress", "done"]


def outside_truck(form):
    unit = forms.text(form.get("outside_unit"), 40)
    if not unit:
        return None, "Give the outside truck a unit number or plate."
    carrier = forms.text(form.get("outside_carrier"), 160)
    vin = forms.text(form.get("outside_vin"), 24)
    existing = None
    if vin:
        existing = one("select * from trucks where company_id = %s and is_outside and upper(vin) = upper(%s)",
                       (g.company["id"], vin))
    if not existing:
        existing = one(
            """select * from trucks where company_id = %s and is_outside and lower(unit_number) = lower(%s)
               and coalesce(lower(outside_carrier), '') = coalesce(lower(%s), '')""",
            (g.company["id"], unit, carrier),
        )
    if existing:
        return existing, None
    label = unit
    clash = one("select id from trucks where company_id = %s and lower(unit_number) = lower(%s)", (g.company["id"], label))
    if clash:
        label = f"{unit} ({carrier or 'outside'})"
        if one("select id from trucks where company_id = %s and lower(unit_number) = lower(%s)", (g.company["id"], label)):
            label = f"{unit} ({carrier or 'outside'} {vin or ''})".strip()
    truck = insert(
        """insert into trucks (company_id, unit_number, vin, make, plate, odometer, odometer_at, is_outside, outside_carrier)
           values (%s, %s, %s, %s, %s, %s, now(), true, %s) returning *""",
        (g.company["id"], label, vin, forms.text(form.get("outside_vehicle"), 60),
         forms.text(form.get("outside_plate"), 20), forms.integer(form.get("odometer")) or 0, carrier),
    )
    audit("truck.created", "truck", truck["id"], {"unit": label, "outside": True})
    return vehicles.ensure_engine(truck), None


def outside_driver(form, truck):
    name = forms.text(form.get("outside_driver_name"), 120)
    if not name:
        return None, "Give the outside driver a name."
    phone = forms.text(form.get("outside_driver_phone"), 40)
    carrier = forms.text(form.get("outside_driver_carrier"), 160) or (truck or {}).get("outside_carrier")
    existing = one(
        """select * from drivers where company_id = %s and lower(name) = lower(%s)
           and coalesce(phone, '') = coalesce(%s, '') order by is_outside desc limit 1""",
        (g.company["id"], name, phone),
    )
    if existing:
        return existing, None
    driver = insert(
        """insert into drivers (company_id, name, phone, is_outside, outside_carrier)
           values (%s, %s, %s, true, %s) returning *""",
        (g.company["id"], name, phone, carrier),
    )
    audit("driver.created", "driver", driver["id"], {"name": name, "outside": True})
    return driver, None


def chosen_driver(form, truck):
    raw = form.get("driver_id")
    if raw == "outside":
        driver, problem = outside_driver(form, truck)
        return (driver["id"] if driver else None), problem
    if raw == "":
        return None, None
    driver_id = forms.integer(raw)
    if driver_id is None:
        return (truck or {}).get("driver_id"), None
    if not one("select id from drivers where id = %s and company_id = %s", (driver_id, g.company["id"])):
        return None, "That driver is not in this company."
    return driver_id, None


def form_choices():
    return {"trucks": active_trucks(), "drivers": active_drivers()}


@bp.get("/maintenance")
@login_required
@company_required
def index():
    status = forms.pick(request.args.get("status"), STATUSES + ["all", "open"], "open")
    group = forms.pick(request.args.get("group"), list(GROUP_LABELS), "")
    params = [g.company["id"]]
    clause = ""
    if status == "open":
        clause = " and m.status <> 'done'"
    elif status != "all":
        clause = " and m.status = %s"
        params.append(status)
    if group:
        clause += " and m.kind = any(%s)"
        params.append(kinds_in(group))
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
                           orders=orders, status=status, statuses=STATUSES, spend=spend, kind_labels=KIND_LABELS,
                           group=group, group_labels=GROUP_LABELS)


@bp.get("/maintenance/new")
@login_required
@role_required("admin")
def new():
    g.google_map = google_places.available()
    return render_template("maintenance/form.html", title="New work order", active="/maintenance",
                           groups=GROUPS, statuses=STATUSES,
                           truck_id=forms.integer(request.args.get("truck_id")), order=None,
                           prefill_description=forms.text(request.args.get("description"), 2000),
                           pti_id=forms.integer(request.args.get("pti")), **form_choices())


@bp.post("/maintenance")
@login_required
@role_required("admin")
def create():
    description = forms.required(request.form.get("description"), 2000)
    if not description:
        flash("Describe the work.", "bad")
        return redirect("/maintenance/new")
    if request.form.get("truck_id") == "outside":
        truck, problem = outside_truck(request.form)
        if problem:
            flash(problem, "bad")
            return redirect("/maintenance/new")
        truck_id = truck["id"]
    else:
        truck_id = forms.integer(request.form.get("truck_id"))
        truck = one("select * from trucks where id = %s and company_id = %s", (truck_id, g.company["id"]))
    if not truck:
        flash("Pick a truck.", "bad")
        return redirect("/maintenance/new")
    driver_id, problem = chosen_driver(request.form, truck)
    if problem:
        flash(problem, "bad")
        return redirect(f"/maintenance/new?truck_id={truck_id}")
    status = forms.pick(request.form.get("status"), STATUSES, "scheduled")
    kind = forms.pick(request.form.get("kind"), KINDS, "repair")
    performed_on = forms.day(request.form.get("performed_on"))
    odometer = forms.integer(request.form.get("odometer"))
    order = insert(
        """insert into maintenance_orders (company_id, truck_id, driver_id, kind, status, scheduled_for, performed_on,
             odometer, vendor, invoice_no, cost, description, next_due_on, next_due_odometer, created_by,
             shop_where, shop_lat, shop_lon)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning *""",
        (
            g.company["id"], truck_id, driver_id, kind, status,
            forms.day(request.form.get("scheduled_for")), performed_on, odometer,
            forms.text(request.form.get("vendor"), 160), forms.text(request.form.get("invoice_no"), 40),
            forms.decimal(request.form.get("cost")), description,
            forms.day(request.form.get("next_due_on")), forms.integer(request.form.get("next_due_odometer")),
            g.session["user_id"], *shop_origin_fields(request.form),
        ),
    )
    apply_completion(order, truck)
    audit("maintenance.created", "maintenance_order", order["id"], {"unit": truck["unit_number"], "kind": kind, "status": status})
    flash("Work order saved.", "ok")
    pti_id = forms.integer(request.form.get("pti_id"))
    if pti_id:
        execute(
            """update inspections set maintenance_order_id = %s
               where id = %s and company_id = %s and truck_id = %s and maintenance_order_id is null""",
            (order["id"], pti_id, g.company["id"], truck_id),
        )
    return redirect(f"/maintenance/{order['id']}")


def shop_origin_fields(form):
    """Where the shop search last looked, when someone typed or picked a place instead of Samsara's."""
    latitude, longitude = forms.decimal(form.get("shop_lat")), forms.decimal(form.get("shop_lon"))
    if latitude is None or longitude is None or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None, None, None
    return forms.text(form.get("shop_where"), 160), latitude, longitude


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


def origin_for(truck):
    latitude, longitude = request.args.get("lat"), request.args.get("lon")
    where = forms.text(request.args.get("where"), 160)
    if latitude and longitude:
        try:
            latitude, longitude = float(latitude), float(longitude)
        except ValueError:
            return None, "That point on the map did not make sense."
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return None, "That point on the map did not make sense."
        return {"latitude": latitude, "longitude": longitude,
                "label": where or "the spot you picked on the map",
                "source": "typed" if where else "picked"}, None
    asked = (request.args.get("q") or "").strip()
    if asked:
        if google_places.looks_like_link(asked):
            return origin_from_link(asked)
        try:
            place = shop_search.geocode(asked)
        except Exception as err:
            log.warning("geocoding %r failed: %s", asked, err)
            return None, f"Could not look that address up just now ({str(err)[:80]})."
        if not place:
            return None, f"Nothing found for “{asked}”. Try a city and state, or the name of a truck stop."
        place["source"] = "typed"
        return place, None
    if truck["latitude"] is not None and truck["longitude"] is not None:
        return {"latitude": truck["latitude"], "longitude": truck["longitude"],
                "label": truck["location"] or "a position without a street address",
                "at": truck["located_at"], "source": "samsara"}, None
    return None, None


def origin_from_link(link):
    try:
        found = google_places.read_link(link)
        if found["latitude"] is None and found["name"]:
            place = shop_search.geocode(found["name"])
            if place:
                found.update(latitude=place["latitude"], longitude=place["longitude"])
    except Exception as err:
        log.warning("reading Google Maps link %r failed: %s", link, err)
        return None, f"Could not read that Google Maps link ({str(err)[:80]})."
    if found["latitude"] is None:
        return None, "That link has no location in it. Open it in Google Maps and copy the link from the address bar."
    return {"latitude": found["latitude"], "longitude": found["longitude"],
            "label": found["name"] or "the place in that Google Maps link", "source": "typed"}, None


def shop_truck(truck_id):
    return one(
        """select t.*, d.name as driver_name from trucks t
           left join drivers d on d.id = t.driver_id
           where t.id = %s and t.company_id = %s""",
        (truck_id, g.company["id"]),
    )


def find_shops(truck):
    origin, problem = origin_for(truck)
    if origin is None:
        return origin, [], None, problem
    latitude, longitude = float(origin["latitude"]), float(origin["longitude"])
    try:
        found, meta = shop_search.nearby(latitude, longitude, radius_miles=config.SHOP_RADIUS_MILES)
    except Exception as err:
        log.warning("shop search around %.4f,%.4f failed: %s", latitude, longitude, err)
        found, meta = [], None
        problem = f"Could not reach the map service just now ({str(err)[:90]})."
    radius = meta["radius_miles"] if meta else config.SHOP_RADIUS_MILES
    saved = shop_search.saved_near(g.company["id"], latitude, longitude, max(radius, 100))
    if saved:
        now = meta["local_time"] if meta else datetime.now(shop_search.zone_for(longitude))
        from_google = bool(meta and meta.get("source") == "google")
        found = shop_search.with_saved(found, saved, latitude, longitude, now,
                                       details_budget=3 if from_google else 0)
    history = vendor_history(g.company["id"])
    for shop in found:
        shop["history"] = match_history(shop["name"], history)
        shop["detour"] = detour_for(shop["miles"])
        shop["dial"] = shop_search.dial(shop.get("phone"))
        shop["maps"] = shop.get("maps") or shop_search.maps_link(shop)
        address = shop.get("address") or ""
        shop["address_complete"] = shop.get("source") == "google" or bool(address[:1].isdigit() and "," in address)
    return origin, found, meta, problem


def fleet_oil_average():
    average = one(
        """select avg(cost) as average from maintenance_orders
           where company_id = %s and kind = 'oil' and status = 'done' and cost is not null""",
        (g.company["id"],),
    )
    return float(average["average"]) if average and average["average"] else None


@bp.get("/maintenance/shops/<int:truck_id>")
@login_required
@role_required("admin")
def shops(truck_id):
    truck = shop_truck(truck_id)
    if not truck:
        return render_template("errors/404.html"), 404
    origin, found, meta, problem = find_shops(truck)
    return render_template("maintenance/_shops.html", truck=truck, found=found, meta=meta,
                           origin=origin, query=(request.args.get("q") or request.args.get("where") or "").strip(),
                           google_key=config.GOOGLE_MAPS_BROWSER_KEY if meta and meta.get("source") == "google" else "",
                           saved_count=one("select count(*) as n from saved_shops where company_id = %s",
                                           (g.company["id"],))["n"],
                           fleet_average=fleet_oil_average(), ai_on=advisor.available(),
                           ai_paused=advisor.over_budget(), problem=problem)


@bp.get("/maintenance/shops/<int:truck_id>/advice")
@login_required
@role_required("admin")
def shops_advice(truck_id):
    truck = shop_truck(truck_id)
    if not truck:
        return jsonify({"state": "missing"}), 404
    if not advisor.available():
        return jsonify({"state": "off"})
    if advisor.over_budget():
        return jsonify({"state": "paused"})
    origin, found, meta, problem = find_shops(truck)
    if not found:
        return jsonify({"state": "none"})
    advice = advisor.shop_advice(dict(truck, location=origin["label"]), found, fleet_oil_average(),
                                 job=forms.text(request.args.get("job"), 300))
    if not advice:
        return jsonify({"state": "none"})
    return jsonify({"state": "ok", "pick": advice.pick, "why": advice.why,
                    "notes": {str(note.number): note.note for note in advice.notes}})


@bp.get("/maintenance/shops/address")
@login_required
@role_required("admin")
def shop_address():
    try:
        latitude = float(request.args.get("lat", ""))
        longitude = float(request.args.get("lon", ""))
    except ValueError:
        return jsonify({"address": None}), 400
    try:
        address = shop_search.reverse(latitude, longitude)
    except Exception as err:
        log.warning("reverse lookup %.5f,%.5f failed: %s", latitude, longitude, err)
        address = None
    name = forms.text(request.args.get("name"), 160) or ""
    maps = shop_search.maps_link({"name": name, "address": address, "latitude": latitude, "longitude": longitude})
    return jsonify({"address": address, "maps": maps})


@bp.get("/maintenance/oil/<int:truck_id>")
@login_required
@company_required
def oil(truck_id):
    truck = one("select * from trucks where id = %s and company_id = %s", (truck_id, g.company["id"]))
    if not truck:
        return render_template("errors/404.html"), 404
    truck = vehicles.ensure_engine(truck)
    advice = advisor.oil_advice(truck)
    return render_template("maintenance/_oil.html", truck=truck, advice=advice,
                           ai_on=advisor.available(), ai_paused=advisor.over_budget())


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
    g.google_map = google_places.available()
    return render_template("maintenance/form.html", title=f"Work order #{order['id']}", active="/maintenance",
                           groups=GROUPS, statuses=STATUSES,
                           order=order, truck_id=order["truck_id"], **form_choices())


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
    driver_id, problem = chosen_driver(request.form, truck)
    if problem:
        flash(problem, "bad")
        return redirect(f"/maintenance/{order_id}")
    updated = insert(
        """update maintenance_orders set driver_id = %s, kind = %s, status = %s, scheduled_for = %s, performed_on = %s,
             odometer = %s, vendor = %s, invoice_no = %s, cost = %s, description = %s,
             next_due_on = %s, next_due_odometer = %s, shop_where = %s, shop_lat = %s, shop_lon = %s,
             updated_at = now()
           where id = %s and company_id = %s returning *""",
        (
            driver_id,
            forms.pick(request.form.get("kind"), KINDS, order["kind"]), status,
            forms.day(request.form.get("scheduled_for")), performed_on,
            forms.integer(request.form.get("odometer")), forms.text(request.form.get("vendor"), 160),
            forms.text(request.form.get("invoice_no"), 40), forms.decimal(request.form.get("cost")),
            forms.required(request.form.get("description"), 2000),
            forms.day(request.form.get("next_due_on")), forms.integer(request.form.get("next_due_odometer")),
            *shop_origin_fields(request.form), order_id, g.company["id"],
        ),
    )
    apply_completion(updated, truck)
    audit("maintenance.updated", "maintenance_order", order_id, {"status": status})
    flash("Work order updated.", "ok")
    return redirect(f"/maintenance/{order_id}")


@bp.get("/maintenance/saved-shops")
@login_required
@company_required
def saved_shops():
    shops = rows(
        """select s.*, u.name as added_by_name from saved_shops s
           left join users u on u.id = s.added_by
           where s.company_id = %s order by s.name""",
        (g.company["id"],),
    )
    return render_template("maintenance/saved_shops.html", title="Saved shops", active="/maintenance",
                           shops=shops, google_on=google_places.available())


def save_shop(link=None, name=None, address=None, phone=None, note=None):
    """Store one shop from a Google Maps link or a name and address. Returns (row, problem)."""
    found = {"name": name, "latitude": None, "longitude": None, "place_id": None, "url": None}
    if link:
        try:
            found.update({key: value for key, value in google_places.read_link(link).items() if value})
        except Exception as err:
            log.warning("reading saved-shop link %r failed: %s", link, err)
            return None, f"{link[:60]} — could not read it ({str(err)[:80]})."
    if found["latitude"] is None:
        lookup = address or found["name"]
        if not lookup:
            return None, f"{(link or '')[:60]} — no location in the link. Copy it from the Google Maps address bar."
        try:
            place = shop_search.geocode(lookup)
        except Exception as err:
            return None, f"{lookup[:60]} — could not look it up ({str(err)[:80]})."
        if not place:
            return None, f"{lookup[:60]} — nothing found at that address."
        found.update(latitude=place["latitude"], longitude=place["longitude"])
        address = address or place["label"]
    name = forms.text(name, 160) or forms.text(found["name"], 160)
    if not address:
        try:
            address = shop_search.reverse(found["latitude"], found["longitude"])
        except Exception as err:
            log.warning("reverse lookup for saved shop failed: %s", err)
    if not name:
        name = address or "Saved shop"
    if not found["place_id"] and google_places.available():
        try:
            match = google_places.place_id_near(name, found["latitude"], found["longitude"])
            found["place_id"] = match and match.get("id")
        except google_places.GoogleError as err:
            log.warning("place id lookup for %r failed: %s", name, err)
    row = insert(
        """insert into saved_shops (company_id, name, address, latitude, longitude, phone, maps_url, place_id,
             source_url, note, added_by)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning *""",
        (g.company["id"], name, forms.text(address, 300), found["latitude"], found["longitude"],
         forms.text(phone, 40), found["url"], found["place_id"], forms.text(link, 1000),
         forms.text(note, 300), g.session["user_id"]),
    )
    audit("saved_shop.added", "saved_shop", row["id"], {"name": name})
    return row, None


@bp.post("/maintenance/saved-shops")
@login_required
@role_required("admin")
def add_saved_shops():
    links = [line.strip() for line in (request.form.get("links") or "").splitlines() if line.strip()][:40]
    name, address = forms.text(request.form.get("name"), 160), forms.text(request.form.get("address"), 300)
    note, phone = request.form.get("note"), request.form.get("phone")
    results = [save_shop(link=link, note=note) for link in links]
    if name or address:
        results.append(save_shop(name=name, address=address, phone=phone, note=note))
    added = [row["name"] for row, _problem in results if row]
    problems = [problem for row, problem in results if not row]
    if not links and not (name or address):
        flash("Paste a Google Maps link, or type a name and address.", "bad")
    if added:
        flash(f"Saved {len(added)}: {', '.join(added)[:300]}", "ok")
    for problem in problems:
        flash(problem, "bad")
    return redirect("/maintenance/saved-shops")


@bp.post("/maintenance/saved-shops/<int:shop_id>")
@login_required
@role_required("admin")
def edit_saved_shop(shop_id):
    shop = one("select * from saved_shops where id = %s and company_id = %s", (shop_id, g.company["id"]))
    if not shop:
        return render_template("errors/404.html"), 404
    if request.form.get("delete"):
        execute("delete from saved_shops where id = %s and company_id = %s", (shop_id, g.company["id"]))
        audit("saved_shop.deleted", "saved_shop", shop_id, {"name": shop["name"]})
        flash(f"Removed {shop['name']}.", "ok")
        return redirect("/maintenance/saved-shops")
    execute(
        "update saved_shops set name = %s, phone = %s, note = %s where id = %s and company_id = %s",
        (forms.text(request.form.get("name"), 160) or shop["name"], forms.text(request.form.get("phone"), 40),
         forms.text(request.form.get("note"), 300), shop_id, g.company["id"]),
    )
    flash("Saved.", "ok")
    return redirect("/maintenance/saved-shops")
