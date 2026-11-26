import re
from datetime import datetime

from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, send_file

from .. import advisor, comebacks, downtime, forms, google_places, places, pm_list, shops as shop_search, vehicles, work_orders
from ..work_types import CUSTOM_PREFIX, GROUP_LABELS, kinds_in
from ..audit import audit
from ..auth import login_required
from ..config import config
from ..db import execute, insert, one, rows
from ..logs import get
from ..tenancy import active_drivers, active_trucks, company_required, role_required

bp = Blueprint("maintenance", __name__)
log = get("maintenance")

STATUSES = work_orders.STATUSES


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


def company_trailers():
    return rows(
        """select tr.id, tr.unit_number, tr.kind, tr.truck_id, tr.location, t.unit_number as truck_unit
           from trailers tr left join trucks t on t.id = tr.truck_id
           where tr.company_id = %s and tr.status <> 'sold' order by lower(tr.unit_number)""",
        (g.company["id"],),
    )


def form_choices():
    return {"trucks": active_trucks(), "drivers": active_drivers(), "trailers": company_trailers(),
            "payment_methods": work_orders.PAYMENT_METHODS, "priorities": work_orders.PRIORITIES}


def author():
    return g.session.get("name") or g.session.get("email")


def load_order(order_id):
    return one(
        f"""select m.*, {work_orders.UNIT_COL} as unit_number, t.unit_number as truck_unit, tr.unit_number as trailer_unit,
                   d.name as driver_name, d.phone as driver_phone
            from maintenance_orders m {work_orders.UNIT_JOIN}
            left join drivers d on d.id = m.driver_id
            where m.id = %s and m.company_id = %s""",
        (order_id, g.company["id"]),
    )


def close_out(order, status):
    if status == "done":
        execute(
            """update maintenance_orders set resolved_at = coalesce(resolved_at, now()),
                 performed_on = coalesce(performed_on, current_date) where id = %s""",
            (order["id"],),
        )
    elif status != "cancelled":
        execute("update maintenance_orders set resolved_at = null where id = %s", (order["id"],))


def driver_contact_for(form, driver_id):
    contact = forms.text(form.get("driver_contact"), 60)
    if driver_id and contact:
        execute(
            "update drivers set phone = %s where id = %s and company_id = %s and coalesce(phone, '') = ''",
            (contact, driver_id, g.company["id"]),
        )
    if not contact and driver_id:
        driver = one("select phone from drivers where id = %s", (driver_id,))
        contact = driver and driver["phone"]
    return contact


def store_extras(order_id, parts, form):
    work_orders.save_parts(g.company["id"], order_id, parts)
    saved, problems = work_orders.save_files(g.company["id"], order_id, request.files.getlist("invoice_files"),
                                             g.session["user_id"])
    for problem in problems:
        flash(problem, "bad")
    if saved:
        audit("maintenance.files_added", "maintenance_order", order_id, {"files": [row["name"] for row in saved]})


LIST_FILTERS = ["all", "open"] + work_orders.STATUSES


@bp.get("/maintenance")
@login_required
@company_required
def index():
    status = forms.pick(request.args.get("status"), LIST_FILTERS, "all")
    group = forms.pick(request.args.get("group"), list(GROUP_LABELS), "")
    asset = forms.pick(request.args.get("asset"), ["truck", "trailer"], "")
    flag = forms.pick(request.args.get("flag"), ["comebacks"], "")
    downtime.refresh(g.company["id"])
    params = [g.company["id"]]
    clause = ""
    if status == "all":
        clause = " and m.status <> 'cancelled'"
    elif status == "open":
        clause = " and m.status not in ('done', 'cancelled')"
    else:
        clause = " and m.status = %s"
        params.append(status)
    if asset:
        clause += " and m.asset_type = %s"
        params.append(asset)
    if flag:
        clause += " and exists (select 1 from maintenance_comebacks c where c.order_id = m.id and c.dismissed_at is null)"
    for key in ("truck_id", "trailer_id", "driver_id"):
        value = forms.integer(request.args.get(key))
        if value:
            clause += f" and m.{key} = %s"
            params.append(value)
    if group:
        clause += " and (m.kind = any(%s) or m.kind like %s)" if group == "pm" else " and m.kind = any(%s)"
        params.append(kinds_in(group))
        if group == "pm":
            params.append(CUSTOM_PREFIX + "%")
    orders = rows(
        f"""select m.*, {work_orders.UNIT_COL} as unit_number, d.name as driver_name,
                   coalesce(m.driver_contact, d.phone) as contact,
                   (select count(*) from maintenance_files f where f.order_id = m.id) as files,
                   (select count(*) from work_order_comments c where c.order_id = m.id and c.kind = 'comment') as comments,
                   (select count(*) from maintenance_comebacks c where c.order_id = m.id and c.dismissed_at is null) as comeback,
                   extract(epoch from coalesce(m.down_ended_at, now()) - m.down_started_at) / 86400.0 as down_days
            from maintenance_orders m {work_orders.UNIT_JOIN}
            left join drivers d on d.id = m.driver_id
            where m.company_id = %s{clause}
            order by (m.status in ('done', 'cancelled')), coalesce(m.performed_on, m.scheduled_for, m.reported_at::date) desc,
                     m.id desc limit 300""",
        tuple(params),
    )
    spend = one(
        """select coalesce(sum(cost), 0) as month_cost, count(*) as month_orders
           from maintenance_orders where company_id = %s and status = 'done'
             and performed_on >= date_trunc('month', current_date)""",
        (g.company["id"],),
    )
    cancelled = one("select count(*) as n from maintenance_orders where company_id = %s and status = 'cancelled'",
                    (g.company["id"],))["n"]
    shops = []
    if flag:
        shops = rows(
            """select coalesce(nullif(m.vendor, ''), 'No shop recorded') as vendor, count(distinct c.order_id) as comebacks,
                      (select count(*) from maintenance_orders x where x.company_id = m.company_id and x.status = 'done'
                         and lower(x.vendor) = lower(m.vendor)) as jobs
               from maintenance_comebacks c join maintenance_orders m on m.id = c.earlier_id
               where c.company_id = %s and c.dismissed_at is null group by 1, m.company_id, m.vendor order by 2 desc""",
            (g.company["id"],),
        )
    return render_template("maintenance/list.html", title="Maintenance", active="/maintenance", flag=flag, shops=shops,
                           comeback_days=one("select comeback_days from companies where id = %s", (g.company["id"],))["comeback_days"],
                           orders=orders, status=status, statuses=work_orders.STATUSES, spend=spend,
                           group=group, group_labels=GROUP_LABELS, asset=asset, cancelled=cancelled)


@bp.get("/maintenance/new")
@login_required
@role_required("admin")
def new():
    breakdown = request.args.get("breakdown") == "1"
    return render_template("maintenance/new.html", title="New work order", active="/maintenance",
                           truck_id=forms.integer(request.args.get("truck_id")),
                           trailer_id=forms.integer(request.args.get("trailer_id")),
                           asset="trailer" if request.args.get("trailer_id") or request.args.get("asset") == "trailer" else "truck",
                           prefill_description=forms.text(request.args.get("description"), 2000),
                           pti_id=forms.integer(request.args.get("pti")), breakdown=breakdown,
                           priority="high" if breakdown else "medium",
                           now=datetime.now().strftime("%Y-%m-%dT%H:%M"), **form_choices())


@bp.post("/maintenance")
@login_required
@role_required("admin")
def create():
    form = request.form
    company_id = g.company["id"]
    asset = forms.pick(form.get("asset_type"), ["truck", "trailer"], "truck")
    back = "/maintenance/new" + ("?asset=trailer" if asset == "trailer" else "")
    description = forms.required(form.get("description"), 2000)
    if not description:
        flash("Say what is wrong.", "bad")
        return redirect(back)
    truck = trailer = None
    if asset == "trailer":
        trailer = one("select * from trailers where id = %s and company_id = %s",
                      (forms.integer(form.get("trailer_id")), company_id))
        if not trailer:
            flash("Pick a trailer.", "bad")
            return redirect(back)
        truck_id = forms.integer(form.get("truck_id"))
        truck = one("select * from trucks where id = %s and company_id = %s", (truck_id, company_id)) if truck_id else None
    elif form.get("truck_id") == "outside":
        truck, problem = outside_truck(form)
        if problem:
            flash(problem, "bad")
            return redirect(back)
    else:
        truck = one("select * from trucks where id = %s and company_id = %s",
                    (forms.integer(form.get("truck_id")), company_id))
        if not truck:
            flash("Pick a truck.", "bad")
            return redirect(back)
    driver_id, problem = chosen_driver(form, truck)
    if problem:
        flash(problem, "bad")
        return redirect(back)
    vendor = forms.text(form.get("vendor"), 160)
    scheduled_for = forms.day(form.get("scheduled_for"))
    status = "scheduled" if vendor or scheduled_for else "open"
    order = insert(
        """insert into maintenance_orders (company_id, asset_type, truck_id, trailer_id, driver_id, kind, status, priority,
             reported_at, scheduled_for, vendor, description, breakdown, location, odometer, created_by)
           values (%s, %s, %s, %s, %s, 'repair', %s, %s, coalesce(%s, now()), %s, %s, %s, %s, %s, %s, %s) returning *""",
        (company_id, asset, truck["id"] if truck else None, trailer["id"] if trailer else None, driver_id, status,
         forms.pick(form.get("priority"), work_orders.PRIORITIES, "medium"), forms.moment(form.get("reported_at")),
         scheduled_for, vendor, description, forms.checkbox(form.get("breakdown")),
         forms.text(form.get("location"), 200),
         ((truck or {}).get("odometer") or None) if asset == "truck" else None, g.session["user_id"]),
    )
    work_orders.add_comment(company_id, order["id"], "event", "opened this work order", g.session["user_id"], author())
    downtime.on_create(order)
    comebacks.check(order["id"])
    unit = trailer["unit_number"] if trailer else truck["unit_number"]
    audit("maintenance.created", "maintenance_order", order["id"], {"unit": unit, "asset": asset, "status": status})
    pti_id = forms.integer(form.get("pti_id"))
    if pti_id and truck:
        execute(
            """update inspections set maintenance_order_id = %s
               where id = %s and company_id = %s and truck_id = %s and maintenance_order_id is null""",
            (order["id"], pti_id, company_id, truck["id"]),
        )
    flash("Work order opened.", "ok")
    return redirect(f"/maintenance/{order['id']}")


def shop_origin_fields(form):
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


def save_rating(order_id):
    rating = forms.integer(request.form.get("shop_rating"))
    execute("update maintenance_orders set shop_rating = %s, shop_comment = %s where id = %s and company_id = %s",
            (rating if rating and 1 <= rating <= 5 else None, forms.text(request.form.get("shop_comment"), 500),
             order_id, g.company["id"]))


def vendor_history(company_id):
    history = rows(
        """select vendor, count(*) as visits, avg(cost) as average, max(performed_on) as last,
             avg(shop_rating) as rating, count(shop_rating) as rated,
             avg(performed_on - coalesce(scheduled_for, created_at::date)) filter (where performed_on is not null) as days,
             (array_agg(shop_comment order by performed_on desc nulls last) filter (where shop_comment is not null))[1] as comment
           from maintenance_orders
           where company_id = %s and status = 'done' and vendor is not null and vendor <> ''
           group by vendor""",
        (company_id,),
    )
    repeats = comebacks.by_vendor(company_id)
    return [dict(row, tokens=_tokens(row["vendor"]), comebacks=repeats.get(row["vendor"].lower(), 0)) for row in history]


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
                "average": float(best["average"]) if best["average"] is not None else None,
                "last": best["last"].strftime("%b %Y") if best["last"] else None,
                "rating": round(float(best["rating"]), 1) if best["rating"] is not None else None, "rated": best["rated"],
                                "days": round(float(best["days"]), 1) if best["days"] is not None else None, "comment": best["comment"],
                "comebacks": best["comebacks"]}
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
        """select t.*, d.name as driver_name, d.phone as driver_phone from trucks t
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
        need = forms.pick(request.args.get("need"), list(shop_search.NEEDS), "repair")
        found, meta = shop_search.nearby(latitude, longitude, radius_miles=config.SHOP_RADIUS_MILES, need=need)
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
        found = shop_search.by_need(found, forms.pick(request.args.get("need"), list(shop_search.NEEDS), "repair"))
    history = vendor_history(g.company["id"])
    for shop in found:
        shop["history"] = match_history(shop["name"], history)
        shop["detour"] = detour_for(shop["miles"])
        shop["dial"] = shop_search.dial(shop.get("phone"))
        shop["maps"] = shop.get("maps") or shop_search.maps_link(shop)
        address = shop.get("address") or ""
        shop["address_complete"] = shop.get("source") == "google" or bool(address[:1].isdigit() and "," in address)
    drive = forms.pick(request.args.get("drive"), ["yes", "no"], None)
    found = shop_search.by_drive(found, drive)
    found = shop_search.sort_shops(found, forms.pick(request.args.get("sort"), list(shop_search.SORTS), "near"),
                                   tow_first=drive == "no")
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
                           ai_paused=advisor.over_budget(), problem=problem,
                           drive=forms.pick(request.args.get("drive"), ["yes", "no"], None),
                           services=shop_search.SERVICES, light_note=shop_search.LIGHT_NOTE,
                           needs=shop_search.NEEDS, need=forms.pick(request.args.get("need"), list(shop_search.NEEDS), "repair"),
                           sorts=shop_search.SORTS, sort=forms.pick(request.args.get("sort"), list(shop_search.SORTS), "near"))


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
    job = forms.text(request.args.get("job"), 300)
    if request.args.get("drive") == "no":
        job = (job + " — " if job else "") + "the truck cannot drive, so it needs a tow truck or mobile road service first"
    advice = advisor.shop_advice(dict(truck, location=origin["label"]), found, fleet_oil_average(), job=job)
    if not advice:
        return jsonify({"state": "none"})
    return jsonify({"state": "ok", "pick": advice.pick, "why": advice.why,
                    "notes": {str(note.number): note.note for note in advice.notes}})


@bp.get("/maintenance/places")
@login_required
@company_required
def place_suggestions():
    return jsonify({"places": [{key: item.get(key) for key in ("label", "detail", "lat", "lon")}
                               for item in places.suggest(request.args.get("q"))]})


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


def saved_shop_for(order):
    if not order["vendor"]:
        return None
    found = rows("select * from saved_shops where company_id = %s and lower(name) = lower(%s)",
                 (g.company["id"], order["vendor"].strip()))
    if order["shop_lat"] is not None:
        found = [row for row in found if shop_search.haversine(float(order["shop_lat"]), float(order["shop_lon"]),
                                                                float(row["latitude"]), float(row["longitude"])) < 1]
    return found[0] if found else None


@bp.post("/maintenance/<int:order_id>/save-shop")
@login_required
@role_required("admin")
def save_order_shop(order_id):
    order = load_order(order_id)
    if not order:
        return render_template("errors/404.html"), 404
    back = f"/maintenance/{order_id}"
    if not order["vendor"]:
        flash("Add the shop's name first.", "bad")
        return redirect(back)
    if saved_shop_for(order):
        flash(f"{order['vendor']} is already in saved shops.", "info")
        return redirect(back)
    note = forms.text(request.form.get("note"), 600)
    if order["shop_lat"] is not None:
        row = insert(
            """insert into saved_shops (company_id, name, address, latitude, longitude, phone, note, added_by)
               values (%s, %s, %s, %s, %s, %s, %s, %s) returning *""",
            (g.company["id"], forms.text(order["vendor"], 160), forms.text(order["shop_address"] or order["shop_where"], 300),
             order["shop_lat"], order["shop_lon"], forms.text(order["shop_phone"], 40), note, g.session["user_id"]),
        )
        audit("saved_shop.added", "saved_shop", row["id"], {"name": row["name"], "work_order": order_id})
        problem = None
    else:
        row, problem = save_shop(name=order["vendor"], address=order["shop_address"] or order["shop_where"],
                                 phone=order["shop_phone"], note=note)
    if problem:
        flash(problem + " Add the shop address to the work order and try again.", "bad")
    else:
        flash(f"{row['name']} saved to saved shops.", "ok")
    return redirect(back)


@bp.get("/maintenance/<int:order_id>")
@login_required
@company_required
def detail(order_id):
    order = load_order(order_id)
    if not order:
        return render_template("errors/404.html"), 404
    g.google_map = google_places.available()
    parts = work_orders.parts_of(order_id)
    files = work_orders.files_of(order_id)
    costs_open = order["status"] == "done" or bool(parts or files or order["cost"] is not None or order["labor_cost"]
                                                   or order["invoice_no"] or order["paid_with"] or order["shop_rating"])
    downtime.refresh(g.company["id"])
    order = load_order(order_id)
    return render_template("maintenance/form.html", saved_shop=saved_shop_for(order), title=" + ".join(x for x in [order["truck_unit"], f"Trailer {order['trailer_unit']}" if order["trailer_unit"] else None] if x) or str(order["unit_number"]), active="/maintenance",
                           comeback_flags=comebacks.flags_for(order_id), down_days=downtime.days(order),
                           groups=pm_list.groups(g.company["id"], order["kind"]), statuses=work_orders.STATUSES,
                           order=order, truck_id=order["truck_id"], parts=parts, files=files,
                           comments=work_orders.comments_of(order_id), costs_open=costs_open, **form_choices())


@bp.post("/maintenance/<int:order_id>")
@login_required
@role_required("admin")
def update(order_id):
    order = one("select * from maintenance_orders where id = %s and company_id = %s", (order_id, g.company["id"]))
    if not order:
        return render_template("errors/404.html"), 404
    form = request.form
    status = forms.pick(form.get("status"), work_orders.STATUSES, order["status"])
    truck_id = order["truck_id"]
    if order["asset_type"] == "trailer" and "truck_id" in form:
        picked = forms.integer(form.get("truck_id"))
        truck_id = picked if picked and one("select id from trucks where id = %s and company_id = %s",
                                            (picked, g.company["id"])) else None
    truck = one("select * from trucks where id = %s and company_id = %s", (truck_id, g.company["id"])) if truck_id else None
    driver_id, problem = chosen_driver(form, truck)
    if problem:
        flash(problem, "bad")
        return redirect(f"/maintenance/{order_id}")
    parts, labor, tax, total = work_orders.money_from(form)
    updated = insert(
        """update maintenance_orders set truck_id = %s, driver_id = %s, kind = %s, status = %s, priority = %s,
             scheduled_for = %s, performed_on = %s, odometer = %s, vendor = %s, invoice_no = %s, cost = %s,
             description = %s, next_due_on = %s, next_due_odometer = %s, shop_where = %s, shop_lat = %s,
             shop_lon = %s, shop_phone = %s, shop_address = %s, driver_contact = %s, labor_cost = %s, tax = %s,
             paid_with = %s, location = %s, breakdown = %s, cause = %s, resolution = %s, towing_cost = %s,
             updated_at = now()
           where id = %s and company_id = %s returning *""",
        (
            truck_id, driver_id,
            forms.pick(form.get("kind"), pm_list.kinds(g.company["id"], order["kind"]), order["kind"]), status,
            forms.pick(form.get("priority"), work_orders.PRIORITIES, order["priority"]),
            forms.day(form.get("scheduled_for")), forms.day(form.get("performed_on")),
            forms.integer(form.get("odometer")), forms.text(form.get("vendor"), 160),
            forms.text(form.get("invoice_no"), 40), total,
            forms.required(form.get("description"), 2000) or order["description"],
            forms.day(form.get("next_due_on")), forms.integer(form.get("next_due_odometer")),
            *shop_origin_fields(form),
            forms.text(form.get("shop_phone"), 40), forms.text(form.get("shop_address"), 300),
            driver_contact_for(form, driver_id), labor, tax,
            forms.pick(form.get("paid_with"), list(work_orders.PAYMENT_LABELS), None),
            forms.text(form.get("location"), 200), forms.checkbox(form.get("breakdown")),
            forms.text(form.get("cause"), 500), forms.text(form.get("resolution"), 2000),
            forms.decimal(form.get("towing_cost")),
            order_id, g.company["id"],
        ),
    )
    store_extras(order_id, parts, form)
    save_rating(order_id)
    work_orders.log_status(g.company["id"], order_id, order["status"], status, g.session["user_id"], author())
    close_out(updated, status)
    if status != order["status"]:
        downtime.on_status(updated, status)
    if updated["breakdown"] and not order["breakdown"]:
        downtime.on_create(updated)
    comebacks.check(order_id)
    if truck:
        apply_completion(updated, truck)
    audit("maintenance.updated", "maintenance_order", order_id, {"status": status})
    flash("Work order updated.", "ok")
    return redirect(f"/maintenance/{order_id}")


@bp.post("/maintenance/<int:order_id>/status")
@login_required
@role_required("admin")
def change_status(order_id):
    order = one("select * from maintenance_orders where id = %s and company_id = %s", (order_id, g.company["id"]))
    if not order:
        return render_template("errors/404.html"), 404
    status = forms.pick(request.form.get("status"), work_orders.STATUSES, order["status"])
    if status != order["status"]:
        updated = insert("update maintenance_orders set status = %s, updated_at = now() where id = %s returning *",
                         (status, order_id))
        work_orders.log_status(g.company["id"], order_id, order["status"], status, g.session["user_id"], author())
        close_out(updated, status)
        downtime.on_status(updated, status)
        if status == "done":
            comebacks.check(order_id)
        truck = one("select * from trucks where id = %s", (order["truck_id"],)) if order["truck_id"] else None
        if truck:
            apply_completion(updated, truck)
        audit("maintenance.status", "maintenance_order", order_id, {"from": order["status"], "to": status})
    return redirect(f"/maintenance/{order_id}#comments")


@bp.post("/maintenance/<int:order_id>/comments")
@login_required
@company_required
def add_comment(order_id):
    order = one("select id from maintenance_orders where id = %s and company_id = %s", (order_id, g.company["id"]))
    if not order:
        return render_template("errors/404.html"), 404
    body = forms.text(request.form.get("body"), 4000)
    upload = request.files.get("file")
    if not body and not (upload and upload.filename):
        flash("Write something or attach a file.", "bad")
        return redirect(f"/maintenance/{order_id}#comments")
    row, problem = work_orders.add_comment(g.company["id"], order_id, "comment", body, g.session["user_id"], author(),
                                           upload)
    if problem:
        flash(problem, "bad")
    else:
        audit("maintenance.comment", "maintenance_order", order_id, {"comment": row["id"]})
    return redirect(f"/maintenance/{order_id}#comments")


@bp.get("/maintenance/<int:order_id>/comments/<int:comment_id>/file")
@login_required
@company_required
def comment_file(order_id, comment_id):
    item = one("select * from work_order_comments where id = %s and order_id = %s and company_id = %s",
               (comment_id, order_id, g.company["id"]))
    path = work_orders.comment_path(item)
    if not path:
        return render_template("errors/404.html"), 404
    inline = item["content_type"] in ("application/pdf", "image/jpeg", "image/png", "image/webp")
    response = send_file(path, mimetype=item["content_type"], as_attachment=not inline, download_name=item["file_name"],
                         max_age=0)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.post("/maintenance/<int:order_id>/comebacks/<int:flag_id>")
@login_required
@role_required("admin")
def comeback_flag(order_id, flag_id):
    dismiss = request.form.get("action") != "restore"
    execute(
        """update maintenance_comebacks set dismissed_at = case when %s then now() end, dismissed_by = case when %s then %s end
           where id = %s and order_id = %s and company_id = %s""",
        (dismiss, dismiss, g.session["user_id"], flag_id, order_id, g.company["id"]),
    )
    audit("maintenance.comeback", "maintenance_order", order_id, {"flag": flag_id, "dismissed": dismiss})
    return redirect(f"/maintenance/{order_id}")


@bp.post("/maintenance/comeback-window")
@login_required
@role_required("admin")
def comeback_window():
    days = min(max(forms.integer(request.form.get("days")) or 60, 1), 365)
    execute("update companies set comeback_days = %s where id = %s", (days, g.company["id"]))
    execute("delete from maintenance_comebacks where company_id = %s and dismissed_at is null", (g.company["id"],))
    comebacks.recheck_company(g.company["id"])
    audit("company.comeback_days", "company", g.company["id"], {"days": days})
    return redirect("/maintenance?flag=comebacks")


@bp.post("/maintenance/<int:order_id>/delete")
@login_required
@role_required("admin")
def delete(order_id):
    order = load_order(order_id)
    if not order:
        return render_template("errors/404.html"), 404
    work_orders.delete_order(g.company["id"], order_id)
    audit("maintenance.deleted", "maintenance_order", order_id, {"unit": order["unit_number"], "description": order["description"][:200]})
    flash(f"Work order #{order_id} deleted.", "ok")
    return redirect("/maintenance")


@bp.get("/maintenance/<int:order_id>/files/<int:file_id>")
@login_required
@company_required
def order_file(order_id, file_id):
    item = one("select * from maintenance_files where id = %s and order_id = %s and company_id = %s",
               (file_id, order_id, g.company["id"]))
    path = work_orders.file_path(item) if item else None
    if not path:
        return render_template("errors/404.html"), 404
    inline = item["content_type"] in ("application/pdf", "image/jpeg", "image/png", "image/webp")
    response = send_file(path, mimetype=item["content_type"], as_attachment=not inline, download_name=item["name"],
                         max_age=0)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.post("/maintenance/<int:order_id>/files/<int:file_id>/delete")
@login_required
@role_required("admin")
def delete_order_file(order_id, file_id):
    item = one("select * from maintenance_files where id = %s and order_id = %s and company_id = %s",
               (file_id, order_id, g.company["id"]))
    if not item:
        return render_template("errors/404.html"), 404
    work_orders.delete_file(item)
    audit("maintenance.file_deleted", "maintenance_order", order_id, {"file": item["name"]})
    flash(f"Removed {item['name']}.", "ok")
    return redirect(f"/maintenance/{order_id}#invoice")


@bp.get("/maintenance/pm-list")
@login_required
@role_required("admin")
def pm_list_page():
    company_id = g.company["id"]
    return render_template("maintenance/pm_list.html", title="Preventive maintenance list", active="/maintenance",
                           entries=pm_list.company_schedules(company_id), gone=pm_list.removed_items(company_id),
                           used=pm_list.used(company_id), limit=pm_list.LABEL_LIMIT)


@bp.post("/maintenance/pm-list")
@login_required
@role_required("admin")
def pm_list_save():
    company_id = g.company["id"]
    if request.form.get("remove"):
        label = pm_list.remove(company_id, forms.text(request.form.get("remove"), 40))
        if label:
            audit("company.pm_list", "company", company_id, {"removed": label})
            flash(f"{label} removed from the list. Work orders already logged as it keep the name.", "ok")
        else:
            flash("That one stays on the list.", "bad")
    elif request.form.get("restore"):
        if pm_list.restore(company_id, forms.text(request.form.get("restore"), 40)):
            audit("company.pm_list", "company", company_id, {"restored": request.form.get("restore")})
            flash("Back on the list.", "ok")
    else:
        label, problem = pm_list.add(company_id, request.form.get("label"))
        if problem:
            flash(problem, "bad")
        else:
            miles, months = forms.integer(request.form.get("miles")), forms.integer(request.form.get("months"))
            miles, months = (miles if miles and miles >= 500 else None), (months if months and 0 < months <= 240 else None)
            kind = pm_list.find(company_id, label)
            if kind and (miles or months):
                pm_list.set_interval(company_id, kind, miles, months)
            audit("company.pm_list", "company", company_id, {"added": label})
            flash(f"{label} added" + (" and now counted on every truck." if miles or months else ". Give it an interval to have it counted on trucks."), "ok")
    return redirect("/maintenance/pm-list")


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
    for shop in shops:
        note = shop["note"] or ""
        shop["note_rows"] = min(12, max(1, sum(len(line) // 48 + 1 for line in note.split("\n"))))
    pins = [{"id": shop["id"], "name": shop["name"], "note": shop["note"], "by": shop["saved_by_name"],
             "address": shop["address"], "phone": shop["phone"],
             "lat": float(shop["latitude"]), "lon": float(shop["longitude"]),
             "url": shop["maps_url"] or f"https://www.google.com/maps/search/?api=1&query={shop['latitude']},{shop['longitude']}"}
            for shop in shops]
    trucks = [{"id": truck["id"], "unit": truck["unit_number"], "lat": float(truck["latitude"]), "lon": float(truck["longitude"])}
              for truck in rows("""select id, unit_number, latitude, longitude from trucks
                                   where company_id = %s and latitude is not null and status <> 'sold' and not is_outside""",
                                (g.company["id"],))]
    return render_template("maintenance/saved_shops.html", title="Saved shops", active="/maintenance", wide=True,
                           shops=shops, pins=pins, truck_pins=trucks, google_on=google_places.available())


def credit_earlier(place):
    row = one(
        """select id, saved_by_name, saved_on, note from saved_shops
           where company_id = %s and lower(name) = lower(%s)
             and round(latitude, 3) = round(%s::numeric, 3) and round(longitude, 3) = round(%s::numeric, 3)""",
        (g.company["id"], place["name"], place["latitude"], place["longitude"]),
    )
    if not row:
        return
    note = row["note"]
    if place.get("note") and place["note"] not in (note or ""):
        note = f"{note} · {place['by']}: {place['note']}" if note else place["note"]
    earlier = place.get("saved_on") and (not row["saved_on"] or place["saved_on"] < row["saved_on"])
    execute(
        """update saved_shops set note = %s, saved_by_name = %s, saved_on = %s where id = %s""",
        (forms.text(note, 600), forms.text(place.get("by"), 120) if earlier else row["saved_by_name"],
         place["saved_on"] if earlier else row["saved_on"], row["id"]),
    )


def save_list(link, note=None):
    try:
        full = google_places.expand_link(link)
        listing = google_places.read_list(full)
    except Exception as err:
        log.warning("reading saved-shop list %r failed: %s", link, err)
        return 0, 0, f"{link[:60]} — could not read the list ({str(err)[:80]})."
    if listing is None:
        return None, 0, None
    existing = rows("select name, latitude, longitude from saved_shops where company_id = %s", (g.company["id"],))
    seen = {(row["name"].strip().lower(), round(float(row["latitude"]), 3), round(float(row["longitude"]), 3)) for row in existing}
    added = skipped = 0
    source = " · ".join(part for part in [listing.get("owner"), listing.get("title")] if part)
    for place in listing["places"]:
        key = (place["name"].lower(), round(place["latitude"], 3), round(place["longitude"], 3))
        if place["name"] and key in seen:
            credit_earlier(place)
        if not place["name"] or key in seen:
            skipped += 1
            continue
        seen.add(key)
        insert(
            """insert into saved_shops (company_id, name, latitude, longitude, maps_url, source_url, note, added_by,
                 saved_by_name, saved_on)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id""",
            (g.company["id"], forms.text(place["name"], 160), place["latitude"], place["longitude"], place["url"],
             forms.text(link, 1000), forms.text(place["note"] or note, 600), g.session["user_id"],
             forms.text(place.get("by"), 120), place.get("saved_on")),
        )
        added += 1
    audit("saved_shop.list_imported", "saved_shop", None,
          {"list": source, "added": added, "skipped": skipped})
    return added, skipped, None


def save_shop(link=None, name=None, address=None, phone=None, note=None):
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
         forms.text(note, 600), g.session["user_id"]),
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
    results = []
    for link in links:
        added, skipped, problem = save_list(link, note)
        if added is None:
            results.append(save_shop(link=link, note=note))
        elif problem:
            results.append((None, problem))
        else:
            flash(f"Imported {added} shops from the Google Maps list" + (f", skipped {skipped} already saved or not a shop" if skipped else "") + ".", "ok")
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
         forms.text(request.form.get("note"), 600), shop_id, g.company["id"]),
    )
    flash("Saved.", "ok")
    return redirect("/maintenance/saved-shops")
