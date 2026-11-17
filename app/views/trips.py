import json
from datetime import datetime

import requests
from flask import Blueprint, flash, g, redirect, render_template, request

from .. import forms, fuel, trips
from ..audit import audit
from ..auth import login_required
from ..db import execute, one, rows
from ..fuel_bot import TRUCK_SQL
from ..logs import get
from ..tenancy import company_required, role_required

bp = Blueprint("trips", __name__)

REST_LABELS = {"break": "30 min break", "rest": "10 h rest", "restart": "34 h restart"}
STATUS_TONES = {"draft": "muted", "sent": "info", "accepted": "ok", "declined": "bad", "done": "ok", "cancelled": "muted"}


def city_of(stop):
    text = stop.get("address") or stop.get("name") or ""
    parts = [p.strip() for p in text.split(",")]
    if len(parts) >= 3:
        state = parts[-1].split()[0] if parts[-1] else ""
        return f"{parts[-2]}, {state}".strip(", ")
    return text


def company_trucks():
    found = rows(TRUCK_SQL + " where t.company_id = %s and t.status = 'active' order by lower(t.unit_number), t.located_at desc nulls last",
                 (g.company["id"],))
    for truck in found:
        truck["label"] = fuel.unit_label(truck["unit_number"])
    return found


def company_truck(truck_id):
    return one(TRUCK_SQL + " where t.id = %s and t.company_id = %s", (truck_id, g.company["id"]))


def company_trip(trip_id):
    return one(
        """select tr.*, t.unit_number, t.telegram_chat_id, d.name as driver_name
           from trips tr join trucks t on t.id = tr.truck_id left join drivers d on d.id = tr.driver_id
           where tr.id = %s and tr.company_id = %s""",
        (trip_id, g.company["id"]),
    )


def plan_trip(truck, text):
    load = trips.parse_load(text)
    if not load["stops"]:
        raise ValueError("Kaido could not find a pickup or delivery in that text. Each stop needs a line like "
                         "\"PU1: name\" or \"DEL1: name\" followed by the address.")
    return trips.build(g.company["id"], truck, load, g.session["user_id"], text)


@bp.get("/trips")
@login_required
@company_required
def index():
    found = rows(
        """select tr.*, t.unit_number, d.name as driver_name
           from trips tr join trucks t on t.id = tr.truck_id left join drivers d on d.id = tr.driver_id
           where tr.company_id = %s order by tr.created_at desc limit 200""",
        (g.company["id"],),
    )
    for trip in found:
        summary = (trip["plan"] or {}).get("summary") or {}
        stops = trip["stops"] or []
        trip["summary"] = summary
        trip["unit"] = fuel.unit_label(trip["unit_number"])
        trip["who"] = fuel.person(trip["driver_name"]) if trip["driver_name"] else None
        trip["from_city"] = city_of(stops[0]) if stops else "—"
        trip["to_city"] = city_of(stops[-1]) if stops else "—"
    return render_template("trips/list.html", title="Trips", active="/trips", trips=found, tones=STATUS_TONES)


@bp.get("/trips/new")
@login_required
@role_required("admin")
def new():
    return render_template("trips/new.html", title="Plan a trip", active="/trips", trucks=company_trucks(),
                           truck_id=forms.integer(request.args.get("truck_id")), text="")


@bp.post("/trips")
@login_required
@role_required("admin")
def create():
    text = (request.form.get("load") or "").strip()
    if request.form.get("truck_id") in ("random", "nearest"):
        truck = trips.random_active_truck(g.company["id"]) if request.form.get("truck_id") == "random" \
            else trips.nearest_active_truck(g.company["id"], trips.parse_load(text))
        if not truck:
            flash("No truck with a driver is live on Samsara in the last hour.", "bad")
            return render_template("trips/new.html", title="Plan a trip", active="/trips", trucks=company_trucks(),
                                   truck_id=None, text=text)
    else:
        truck = company_truck(forms.integer(request.form.get("truck_id")))
    if not text or not truck:
        flash("Paste the load and pick a truck.", "bad")
        return render_template("trips/new.html", title="Plan a trip", active="/trips", trucks=company_trucks(),
                               truck_id=truck["id"] if truck else None, text=text)
    try:
        trip = plan_trip(truck, text[:8000])
    except ValueError as err:
        flash(str(err), "bad")
        return render_template("trips/new.html", title="Plan a trip", active="/trips", trucks=company_trucks(),
                               truck_id=truck["id"], text=text)
    except requests.RequestException as err:
        get("trips").warning("trip planning failed: %s", err)
        flash("The map service did not answer. Wait a minute and try again.", "bad")
        return render_template("trips/new.html", title="Plan a trip", active="/trips", trucks=company_trucks(),
                               truck_id=truck["id"], text=text)
    audit("trip.planned", "trip", trip["id"], {"unit": truck["unit_number"], "load": trip["load_number"]})
    return redirect(f"/trips/{trip['id']}")


def timeline(trip):
    plan = trip["plan"] or {}
    stops = trip["stops"] or []
    leg_ends = (trip["route"] or {}).get("leg_ends") or []
    start_lon = float(trip["start_longitude"])
    entries = [{"mile": 0, "kind": "start", "title": "Truck now",
                "detail": f"Tank {float(trip['start_fuel_percent']):.0f}% of {trip['tank_gallons']} gal",
                "when": trips.when_text(trip["created_at"].isoformat(), start_lon), "tone": "muted"}]
    for index, stop in enumerate(plan.get("fuel_stops") or [], 1):
        price = f"${stop['price']:.3f}"
        if stop["source"] == "website":
            price += " est."
        elif stop.get("age_days"):
            price += f" paid {stop['age_days']}d ago"
        entries.append({"mile": stop["mile"], "kind": "fuel", "number": index, "title": trips.place_name(stop),
                        "detail": f"Buy {stop['gallons']:.0f} gal at {price}, ${stop['cost']:,.0f}",
                        "extra": f"arrive about {stop['arrive_percent']}%, leave {stop['depart_percent']}%"
                                 + (f", {stop['off_route']:.1f} mi off route" if stop.get("off_route", 0) >= 0.5 else ""),
                        "when": trips.when_text(stop.get("eta"), stop["longitude"]), "tone": "info",
                        "link": fuel.maps_link(stop)})
    for rest in plan.get("rests") or []:
        spot = rest.get("spot")
        entries.append({"mile": rest["mile"], "kind": rest["kind"], "title": REST_LABELS.get(rest["kind"], rest["kind"]),
                        "detail": (f"at {trips.place_name(spot)}" + (f", {spot['spaces']} spots" if spot.get("spaces") else ""))
                                  if spot else "no truck stop with parking found nearby",
                        "when": trips.when_text(rest["start"], rest["longitude"]),
                        "tone": "warn" if rest["kind"] == "restart" else "muted"})
    for index, stop in enumerate(stops):
        window = None
        if stop.get("window_start"):
            opens = datetime.fromisoformat(stop["window_start"])
            closes = datetime.fromisoformat(stop["window_end"])
            window = f"{stop.get('window_type') or 'Window'} {opens:%b %d %H:%M} to {closes:%b %d %H:%M}"
        late = stop.get("late_hours") or 0
        state = f"LATE by about {late:.0f} h" if late else "on time"
        extra = state + (f", wait {stop['wait_hours']:.1f} h for the window" if stop.get("wait_hours") else "")
        entries.append({"mile": leg_ends[index] if index < len(leg_ends) else None, "kind": stop["kind"],
                        "title": ("Pickup: " if stop["kind"] == "pickup" else "Delivery: ") + (stop.get("name") or ""),
                        "detail": (stop.get("address") or "") + (f" · {window}" if window else ""), "extra": extra,
                        "when": trips.when_text(stop.get("eta"), stop["longitude"]), "tone": "bad" if late else "ok"})
    entries.sort(key=lambda e: (e["mile"] if e["mile"] is not None else 1e9, e["kind"] in ("pickup", "delivery")))
    return entries


def map_data(trip):
    plan = trip["plan"] or {}
    return json.dumps({
        "route": (trip["route"] or {}).get("points") or [],
        "start": [float(trip["start_latitude"]), float(trip["start_longitude"])],
        "stops": [{"lat": s["latitude"], "lon": s["longitude"], "kind": s["kind"], "name": s.get("name") or "",
                   "address": s.get("address") or ""} for s in trip["stops"] or []],
        "fuel": [{"lat": s["latitude"], "lon": s["longitude"], "name": trips.place_name(s), "gallons": s["gallons"],
                  "price": s["price"], "estimated": s["source"] == "website", "mile": s["mile"]}
                 for s in plan.get("fuel_stops") or []],
        "rests": [{"lat": r["latitude"], "lon": r["longitude"], "kind": REST_LABELS.get(r["kind"], r["kind"]),
                   "mile": r["mile"], "where": trips.place_name(r["spot"]) if r.get("spot") else ""}
                  for r in plan.get("rests") or [] if r["kind"] in ("rest", "restart")],
    })


@bp.get("/trips/<int:trip_id>")
@login_required
@company_required
def show(trip_id):
    trip = company_trip(trip_id)
    if not trip:
        flash("Trip not found.", "bad")
        return redirect("/trips")
    truck = one(TRUCK_SQL + " where t.id = %s", (trip["truck_id"],))
    summary = (trip["plan"] or {}).get("summary") or {}
    per_mile = None
    if summary.get("average_price") and summary.get("burn_gallons") and summary.get("miles"):
        per_mile = summary["burn_gallons"] * summary["average_price"] / summary["miles"]
    return render_template(
        "trips/show.html", title=f"Trip {trip['load_number'] or trip['id']}", active="/trips", trip=trip, truck=truck,
        summary=summary, plan=trip["plan"] or {}, entries=timeline(trip), map_json=map_data(trip),
        preview=trips.message(trip, truck), maps_url=trips.maps_route(trip), per_mile=per_mile,
        unit=fuel.unit_label(trip["unit_number"]), who=fuel.person(trip["driver_name"]) if trip["driver_name"] else None,
        tones=STATUS_TONES,
    )


@bp.post("/trips/<int:trip_id>/send")
@login_required
@role_required("admin")
def send(trip_id):
    trip = company_trip(trip_id)
    if not trip:
        return redirect("/trips")
    if not trip["telegram_chat_id"]:
        flash("This truck has no Telegram group yet. Connect it from the truck page first.", "bad")
        return redirect(f"/trips/{trip_id}")
    result = trips.send_to_driver(trip_id)
    if result.get("ok"):
        audit("trip.sent", "trip", trip_id, {"unit": trip["unit_number"]})
        flash("Plan sent to the driver's group.", "ok")
    else:
        flash(f"Telegram did not deliver it: {result.get('reason') or 'unknown error'}", "bad")
    return redirect(f"/trips/{trip_id}")


@bp.post("/trips/<int:trip_id>/replan")
@login_required
@role_required("admin")
def replan(trip_id):
    trip = company_trip(trip_id)
    if not trip:
        return redirect("/trips")
    truck = company_truck(trip["truck_id"])
    if not trip["source_text"] or not truck:
        flash("This trip has no saved load text to plan again.", "bad")
        return redirect(f"/trips/{trip_id}")
    try:
        fresh = plan_trip(truck, trip["source_text"])
    except ValueError as err:
        flash(str(err), "bad")
        return redirect(f"/trips/{trip_id}")
    except requests.RequestException as err:
        get("trips").warning("trip re-plan failed: %s", err)
        flash("The map service did not answer. Wait a minute and try again.", "bad")
        return redirect(f"/trips/{trip_id}")
    if trip["status"] in ("draft", "sent"):
        execute("update trips set status = 'cancelled', answer_note = %s, updated_at = now() where id = %s",
                (f"Re-planned as trip {fresh['id']}", trip_id))
    audit("trip.replanned", "trip", fresh["id"], {"from": trip_id})
    flash("Planned again from the truck's current position.", "ok")
    return redirect(f"/trips/{fresh['id']}")


@bp.post("/trips/<int:trip_id>/cancel")
@login_required
@role_required("admin")
def cancel(trip_id):
    trip = company_trip(trip_id)
    if not trip:
        return redirect("/trips")
    execute("update trips set status = 'cancelled', updated_at = now() where id = %s and company_id = %s",
            (trip_id, g.company["id"]))
    audit("trip.cancelled", "trip", trip_id, {"unit": trip["unit_number"]})
    flash("Trip cancelled.", "ok")
    return redirect(f"/trips/{trip_id}")
