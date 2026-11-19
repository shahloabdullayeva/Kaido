import math
from datetime import datetime, timedelta, timezone

import csv
import io

from flask import Blueprint, Response, flash, g, redirect, render_template, request

from .. import brand_prices, forms, fuel, fuel_guard, fuel_import, eia
from ..audit import audit
from ..auth import login_required
from ..db import execute, insert, one, rows
from ..logs import get
from ..tenancy import active_drivers, active_trucks, company_required, role_required

bp = Blueprint("fuel", __name__)

FUEL_TYPES = ["diesel", "def", "reefer", "gas"]


@bp.get("/fuel")
@login_required
@company_required
def index():
    truck_id = forms.integer(request.args.get("truck_id"))
    oldest_first = request.args.get("dir") == "asc"
    order = "asc" if oldest_first else "desc"
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
            order by f.purchased_at {order}, f.id {order} limit 200""",
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
                           totals=totals, trucks=active_trucks(), truck_id=truck_id, oldest_first=oldest_first)


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


@bp.get("/fuel/import")
@login_required
@role_required("admin")
def import_form():
    history = rows(
        """select i.*, u.name as author from fuel_imports i left join users u on u.id = i.created_by
           where i.company_id = %s order by i.created_at desc limit 10""",
        (g.company["id"],),
    )
    return render_template("fuel/import.html", title="Import fuel", active="/fuel", history=history, report=None)


@bp.post("/fuel/import")
@login_required
@role_required("admin")
def import_file():
    upload = request.files.get("sheet")
    if not upload or not upload.filename:
        flash("Choose the file you downloaded from eManager.", "bad")
        return redirect("/fuel/import")
    try:
        report = fuel_import.run(g.company["id"], g.session["user_id"], upload.filename, upload.read())
    except Exception as err:
        get("fuel").warning("EFS import of %s failed", upload.filename, exc_info=True)
        flash(f"Could not import that file. {str(err)[:400]}", "bad")
        return redirect("/fuel/import")
    audit("fuel.imported", "fuel_import", None, {"file": upload.filename, "added": report["added"],
                                                  "duplicate": report["duplicate"], "unmatched": len(report["unmatched"])})
    history = rows(
        """select i.*, u.name as author from fuel_imports i left join users u on u.id = i.created_by
           where i.company_id = %s order by i.created_at desc limit 10""",
        (g.company["id"],),
    )
    return render_template("fuel/import.html", title="Import fuel", active="/fuel", history=history,
                           report=report, filename=upload.filename)


RANGES = [7, 30, 90, 3650]
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
SKIP_LABELS = {"busy": "Already fueling", "far": "Off route", "park": "No parking", "brand": "Doesn't like the brand",
               "price": "Found cheaper", "later": "Remind later"}
CHART_W = 640
CHART_H = 220
PAD_L = 56
PAD_R = 16
PAD_T = 16
PAD_B = 32


def nice_ticks(low, high, count=4):
    if high <= low:
        high = low + 1
    raw = (high - low) / count
    power = 10 ** math.floor(math.log10(raw))
    step = next(m * power for m in (1, 2, 2.5, 5, 10) if m * power >= raw)
    start = math.floor(low / step) * step
    ticks = []
    value = start
    while value <= high + step * 0.001:
        ticks.append(round(value, 6))
        value += step
    if ticks[-1] < high:
        ticks.append(round(ticks[-1] + step, 6))
    return ticks


def scale(ticks):
    low, high = ticks[0], ticks[-1]
    inner = CHART_H - PAD_T - PAD_B
    return lambda v: PAD_T + inner - (float(v) - low) / ((high - low) or 1) * inner


def line_chart(labels, series, fmt):
    values = [v for s in series for v in s["values"] if v is not None]
    if not values:
        return None
    spread = (max(values) - min(values)) or 0.1
    ticks = nice_ticks(min(values) - spread * 0.15, max(values) + spread * 0.15)
    y = scale(ticks)
    slot = (CHART_W - PAD_L - PAD_R) / max(1, len(labels))
    xs = [PAD_L + slot * i + slot / 2 for i in range(len(labels))]
    lines = []
    for item in series:
        points = [(round(xs[i], 1), round(y(v), 1), v, labels[i]) for i, v in enumerate(item["values"]) if v is not None]
        lines.append({"name": item["name"], "cls": item["cls"], "points": points,
                      "path": " ".join(f"{'M' if n == 0 else 'L'}{p[0]},{p[1]}" for n, p in enumerate(points))})
    return {"w": CHART_W, "h": CHART_H, "pad_l": PAD_L, "pad_r": PAD_R, "base": CHART_H - PAD_B,
            "ticks": [{"y": round(y(t), 1), "label": fmt(t)} for t in ticks],
            "labels": [{"x": round(x, 1), "text": l} for x, l in zip(xs, labels)], "lines": lines, "bars": [],
            "fmt": fmt}


def bar_chart(labels, series, fmt, width_px=CHART_W):
    values = [v for s in series for v in s["values"] if v is not None]
    if not values:
        return None
    ticks = nice_ticks(0, max(values) or 1)
    y = scale(ticks)
    base = CHART_H - PAD_B
    slot = (width_px - PAD_L - PAD_R) / max(1, len(labels))
    group = min(slot * 0.7, 26 * len(series) + 2 * (len(series) - 1))
    width = (group - 2 * (len(series) - 1)) / len(series)
    bars = []
    for i, label in enumerate(labels):
        left = PAD_L + slot * i + (slot - group) / 2
        for n, item in enumerate(series):
            value = item["values"][i]
            if value is None:
                continue
            top = y(value)
            x = left + n * (width + 2)
            h = max(0.0, base - top)
            r = min(4, width / 2, h)
            path = (f"M{x:.1f},{base:.1f} L{x:.1f},{top + r:.1f} Q{x:.1f},{top:.1f} {x + r:.1f},{top:.1f} "
                    f"L{x + width - r:.1f},{top:.1f} Q{x + width:.1f},{top:.1f} {x + width:.1f},{top + r:.1f} "
                    f"L{x + width:.1f},{base:.1f} Z")
            bars.append({"path": path, "cls": item["cls"], "title": f"{label} · {item['name']}: {fmt(value)}",
                         "hit": (round(x - 2, 1), round(PAD_T, 1), round(width + 4, 1), round(base - PAD_T, 1))})
    return {"w": width_px, "h": CHART_H, "pad_l": PAD_L, "pad_r": PAD_R, "base": base,
            "ticks": [{"y": round(y(t), 1), "label": fmt(t)} for t in ticks],
            "labels": [{"x": round(PAD_L + slot * i + slot / 2, 1), "text": l} for i, l in enumerate(labels)],
            "lines": [], "bars": bars, "legend": [{"name": s["name"], "cls": s["cls"]} for s in series]}


def dollars(value):
    value = float(value)
    return f"${value / 1000:,.1f}k" if abs(value) >= 1000 else f"${value:,.0f}"


def per_gallon(value):
    return f"${float(value):.2f}"


def days_arg():
    days = forms.integer(request.args.get("days"))
    return days if days in RANGES else max(RANGES)


@bp.get("/fuel/insights")
@login_required
@company_required
def insights():
    days = days_arg()
    company_id = g.company["id"]
    since = f"now() - interval '{days} days'"
    kpi = one(
        f"""select count(*) as fills, coalesce(sum(gallons), 0) as gallons, coalesce(sum(total), 0) as spend,
                   sum(total) / nullif(sum(gallons), 0) as avg_net,
                   sum(retail_ppu * gallons) / nullif(sum(gallons) filter (where retail_ppu is not null), 0) as avg_pump,
                   coalesce(sum(discount_ppu * gallons), 0) as discount, coalesce(sum(missed_usd), 0) as missed,
                   count(*) filter (where net_ppu is not null and coalesce(discount_ppu, 0) < 0.01) as no_discount,
                   count(*) filter (where checked_at is not null) as checked,
                   count(*) filter (where source = 'demo') as demo
            from fuel_transactions where company_id = %s and fuel_type = 'diesel' and purchased_at >= {since}""",
        (company_id,),
    )
    offers = one(
        f"""select count(*) filter (where status <> 'failed') as sent, count(*) filter (where chosen_station_id is not null) as taken,
                   count(*) filter (where followed) as followed, coalesce(sum(saved_usd) filter (where saved_usd > 0), 0) as saved
            from fuel_offers where company_id = %s and created_at >= {since}""",
        (company_id,),
    )
    mpg = one(
        f"""with per_truck as (
              select t.id, (select max(miles) - min(miles) from odometer_readings r
                            where r.truck_id = t.id and r.read_at >= {since}) as miles,
                     (select sum(gallons) from fuel_transactions f
                      where f.truck_id = t.id and f.fuel_type = 'diesel' and f.purchased_at >= {since}) as gallons
              from trucks t where t.company_id = %s)
            select sum(miles) as miles, sum(gallons) as gallons from per_truck
            where miles between 300 and %s and gallons > 50 and miles / gallons between 4 and 9""",
        (company_id, days * 1500),
    )
    fleet_mpg = None
    if mpg and mpg["miles"] and mpg["gallons"]:
        value = float(mpg["miles"]) / float(mpg["gallons"])
        fleet_mpg = value if 3.5 <= value <= 11 else None
    weeks = rows(
        f"""select date_trunc('week', purchased_at) as week, sum(total) as spend,
                   sum(total) / nullif(sum(gallons), 0) as net,
                   sum(retail_ppu * gallons) / nullif(sum(gallons) filter (where retail_ppu is not null), 0) as pump,
                   coalesce(sum(discount_ppu * gallons), 0) as discount, coalesce(sum(missed_usd), 0) as missed
            from fuel_transactions where company_id = %s and fuel_type = 'diesel'
              and purchased_at >= greatest({since}, now() - interval '84 days') - interval '{0 if days >= 30 else 21} days'
            group by 1 order by 1""",
        (company_id,),
    )
    labels = [w["week"].strftime("%d %b") for w in weeks]
    price_chart = line_chart(labels, [
        {"name": "You paid (after discount)", "cls": "s1", "values": [float(w["net"]) if w["net"] else None for w in weeks]},
        {"name": "Pump price", "cls": "s0", "values": [float(w["pump"]) if w["pump"] else None for w in weeks]},
    ], per_gallon)
    if price_chart:
        price_chart["legend"] = [{"name": "You paid (after discount)", "cls": "s1"}, {"name": "Pump price", "cls": "s0"}]
    spend_chart = bar_chart(labels, [{"name": "Diesel spend", "cls": "s1", "values": [float(w["spend"]) for w in weeks]}], dollars)
    if spend_chart:
        spend_chart["legend"] = []
    saving_chart = bar_chart(labels, [
        {"name": "Discounts captured", "cls": "s3", "values": [float(w["discount"]) for w in weeks]},
        {"name": "Missed savings", "cls": "s2", "values": [float(w["missed"]) for w in weeks]},
    ], dollars, CHART_W * 2)
    drivers = rows(
        f"""select initcap(regexp_replace(trim(min(coalesce(d.name, f.raw->>'driver name', 'Unit ' || t.unit_number))), '\s+', ' ', 'g')) as who, max(f.driver_id) as driver_id,
                   count(*) as fills, sum(f.gallons) as gallons, sum(f.total) / nullif(sum(f.gallons), 0) as avg,
                   coalesce(sum(f.discount_ppu * f.gallons), 0) as discount, coalesce(sum(f.missed_usd), 0) as missed,
                   count(*) filter (where f.net_ppu is not null and coalesce(f.discount_ppu, 0) < 0.01) as no_discount,
                   (select count(*) from fuel_offers o where o.company_id = f.company_id and o.driver_id = max(f.driver_id)
                      and o.created_at >= {since} and o.status <> 'failed') as offered,
                   (select count(*) from fuel_offers o where o.company_id = f.company_id and o.driver_id = max(f.driver_id)
                      and o.created_at >= {since} and o.chosen_station_id is not null) as taken
            from fuel_transactions f join trucks t on t.id = f.truck_id left join drivers d on d.id = f.driver_id
            where f.company_id = %s and f.fuel_type = 'diesel' and f.purchased_at >= {since}
            group by lower(regexp_replace(trim(coalesce(d.name, f.raw->>'driver name', 'Unit ' || t.unit_number)), '\s+', ' ', 'g')),
                     f.company_id
            order by missed desc, gallons desc limit 25""",
        (company_id,),
    )
    misses = rows(
        f"""select f.*, t.unit_number, initcap(coalesce(d.name, f.raw->>'driver name')) as who,
                   s.name as station_name, s.city as station_city, s.state as station_state,
                   b.name as best_name, b.city as best_city, b.state as best_state
            from fuel_transactions f join trucks t on t.id = f.truck_id left join drivers d on d.id = f.driver_id
            left join fuel_stations s on s.id = f.station_id left join fuel_stations b on b.id = f.best_station_id
            where f.company_id = %s and f.fuel_type = 'diesel' and f.purchased_at >= {since} and f.missed_usd > 0
            order by f.missed_usd desc limit 25""",
        (company_id,),
    )
    stations = rows(
        f"""select s.id, s.name, s.brand, s.city, s.state, s.latitude, s.longitude, count(*) as fills,
                   sum(f.gallons) as gallons, sum(f.total) / nullif(sum(f.gallons), 0) as avg,
                   avg(f.discount_ppu) as discount, max(f.purchased_at) as last_at
            from fuel_transactions f join fuel_stations s on s.id = f.station_id
            where f.company_id = %s and f.fuel_type = 'diesel' and f.purchased_at >= {since}
            group by s.id order by gallons desc""",
        (company_id,),
    )
    pins = [{"lat": float(s["latitude"]), "lon": float(s["longitude"]), "name": s["name"],
             "where": ", ".join(p for p in [s["city"], s["state"]] if p), "avg": round(float(s["avg"]), 3) if s["avg"] else None,
             "fills": s["fills"], "gallons": round(float(s["gallons"]))}
            for s in stations if s["latitude"] is not None]
    market = eia.changes()
    trend_regions = [("US", "U.S. average", "s1"), ("CA", "California", "s2"), ("3", "Gulf Coast", "s3")]
    trend = {code: eia.history(code, 12) for code, _, _ in trend_regions}
    trend_labels = [w["week"].strftime("%d %b") for w in trend["US"]]
    market_chart = line_chart(trend_labels, [
        {"name": name, "cls": cls, "values": [float(w["price"]) for w in trend[code]][-len(trend_labels):]}
        for code, name, cls in trend_regions if trend[code]
    ], per_gallon) if trend_labels else None
    if market_chart:
        market_chart["legend"] = [{"name": name, "cls": cls} for _, name, cls in trend_regions]
    state_day, state_rows = eia.states_table()
    stop_avg = None
    if state_rows:
        total = sum(r["stations"] for r in state_rows)
        stop_avg = {"price": sum(float(r["avg_price"]) * r["stations"] for r in state_rows) / total, "stations": total,
                    "states": len(state_rows)}
    return render_template("fuel/insights.html", title="Fuel insights", active="/fuel", days=days, ranges=RANGES,
                           market=market, market_chart=market_chart, state_day=state_day, state_rows=state_rows,
                           stop_avg=stop_avg,
                           kpi=kpi, offers=offers, fleet_mpg=fleet_mpg, price_chart=price_chart,
                           spend_chart=spend_chart, saving_chart=saving_chart, drivers=drivers, misses=misses,
                           stations=stations[:12], pins=pins)


@bp.get("/fuel/offers")
@login_required
@company_required
def offers_log():
    truck_id = forms.integer(request.args.get("truck_id"))
    params = [g.company["id"]]
    clause = ""
    if truck_id:
        clause = " and o.truck_id = %s"
        params.append(truck_id)
    entries = rows(
        f"""select o.*, t.unit_number, d.name as driver_name, s.name as chosen_name, s.city as chosen_city,
                   s.state as chosen_state, f.net_ppu as paid_ppu, f.gallons as paid_gallons, fs.name as paid_station
            from fuel_offers o join trucks t on t.id = o.truck_id left join drivers d on d.id = o.driver_id
            left join fuel_stations s on s.id = o.chosen_station_id
            left join fuel_transactions f on f.id = o.transaction_id
            left join fuel_stations fs on fs.id = f.station_id
            where o.company_id = %s{clause} order by o.created_at desc limit 200""",
        tuple(params),
    )
    return render_template("fuel/offers.html", title="Fuel suggestions", active="/fuel", entries=entries,
                           trucks=active_trucks(), truck_id=truck_id, skip_labels=SKIP_LABELS)


@bp.get("/fuel/alerts")
@login_required
@company_required
def alerts():
    show = request.args.get("show") if request.args.get("show") in ("open", "all") else "all"
    entries = rows(
        f"""select a.*, t.unit_number, d.name as driver_name, u.name as reviewer
            from fuel_alerts a left join trucks t on t.id = a.truck_id left join drivers d on d.id = a.driver_id
            left join users u on u.id = a.reviewed_by
            where a.company_id = %s{" and a.status = 'open'" if show == 'open' else ''}
            order by a.happened_at desc limit 300""",
        (g.company["id"],),
    )
    counts = one(
        """select count(*) filter (where status = 'open') as open, count(*) filter (where status = 'confirmed') as confirmed,
                  count(*) filter (where status = 'ok') as ok from fuel_alerts where company_id = %s""",
        (g.company["id"],),
    )
    return render_template("fuel/alerts.html", title="Fuel checks", active="/fuel", entries=entries, show=show,
                           counts=counts, labels=fuel_guard.LABELS)


@bp.post("/fuel/alerts/<int:alert_id>")
@login_required
@role_required("admin")
def review_alert(alert_id):
    status = forms.pick(request.form.get("status"), ["ok", "confirmed", "open"], "ok")
    done = execute(
        """update fuel_alerts set status = %s, note = %s, reviewed_by = %s, reviewed_at = now()
           where id = %s and company_id = %s""",
        (status, forms.text(request.form.get("note"), 500), g.session["user_id"], alert_id, g.company["id"]),
    )
    if done:
        audit("fuel.alert_reviewed", "fuel_alert", alert_id, {"status": status})
        flash("Saved.", "ok")
    return redirect(request.form.get("back") or "/fuel/alerts")


def recent_prices():
    return rows(
        """select distinct on (p.station_id) p.*, s.name, s.city, s.state, s.brand
           from fuel_prices p join fuel_stations s on s.id = p.station_id
           where p.company_id = %s and p.fuel_type = 'diesel'
           order by p.station_id, p.observed_at desc""",
        (g.company["id"],),
    )


@bp.get("/fuel/prices")
@login_required
@role_required("admin")
def prices():
    found = recent_prices()
    cutoff = datetime.now(timezone.utc) - timedelta(days=fuel.PRICE_OLD_DAYS)
    for price in found:
        price["stale"] = price["observed_at"] < cutoff
    discounts = brand_prices.brand_discounts(g.company["id"])
    own = {p["station_id"]: p for p in found}
    for row in rows(
        """select r.station_id, r.retail_ppu, r.fetched_at, r.source as site, s.name, s.city, s.state, s.brand
           from station_retail_prices r join fuel_stations s on s.id = r.station_id
           where r.fuel_type = 'diesel' and r.fetched_at > now() - interval '30 hours'"""
    ):
        mine = own.get(row["station_id"])
        if mine and mine["observed_at"] > cutoff + timedelta(days=fuel.PRICE_OLD_DAYS - 7):
            continue
        discount = discounts.get(row["brand"], 0.0)
        entry = {"station_id": row["station_id"], "name": row["name"], "city": row["city"], "state": row["state"],
                 "brand": row["brand"], "retail_ppu": float(row["retail_ppu"]), "net_ppu": round(float(row["retail_ppu"]) - discount, 4),
                 "source": "website", "observed_at": row["fetched_at"], "stale": False, "estimated": bool(discount)}
        if mine:
            found.remove(mine)
        found.append(entry)
    found.sort(key=lambda p: (p["stale"], p["net_ppu"], p["name"]))
    return render_template("fuel/prices.html", title="Fuel prices", active="/fuel", prices=found, report=None)


@bp.get("/fuel/prices/sample.csv")
@login_required
@role_required("admin")
def sample_prices():
    found = rows(
        """select distinct on (p.station_id) p.retail_ppu, p.net_ppu, s.name, s.city, s.state, s.latitude, s.longitude
           from fuel_prices p join fuel_stations s on s.id = p.station_id
           where p.company_id = %s and p.fuel_type = 'diesel' and p.source = 'transaction' and s.latitude is not null
           order by p.station_id, p.observed_at desc""",
        (g.company["id"],),
    )
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Station Name", "City", "State", "Latitude", "Longitude", "Retail Price", "Discount", "Your Price", "Price Date"])
    today = datetime.now().strftime("%Y-%m-%d")
    for price in sorted(found, key=lambda p: (p["state"] or "", p["name"])):
        retail = float(price["retail_ppu"] or price["net_ppu"])
        net = float(price["net_ppu"])
        writer.writerow([price["name"], price["city"] or "", price["state"] or "", f"{float(price['latitude']):.6f}",
                         f"{float(price['longitude']):.6f}", f"{retail:.3f}", f"{retail - net:.3f}", f"{net:.3f}", today])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=sample-price-list-{today}.csv"})


@bp.post("/fuel/prices")
@login_required
@role_required("admin")
def import_prices():
    upload = request.files.get("sheet")
    if not upload or not upload.filename:
        flash("Choose the price list file.", "bad")
        return redirect("/fuel/prices")
    try:
        report = fuel.import_price_file(g.company["id"], upload.filename, upload.read())
    except Exception as err:
        get("fuel").warning("price list import of %s failed", upload.filename, exc_info=True)
        flash(f"Could not import that file. {str(err)[:400]}", "bad")
        return redirect("/fuel/prices")
    audit("fuel.prices_imported", "fuel_price", None, {"file": upload.filename, **report})
    flash(f"{report['added']} prices saved, {report['skipped']} rows skipped.", "ok")
    return redirect("/fuel/prices")


@bp.get("/fuel/settings")
@login_required
@role_required("admin")
def settings():
    prefs = rows(
        """select p.*, d.name as driver_name from driver_fuel_prefs p join drivers d on d.id = p.driver_id
           where p.company_id = %s order by lower(d.name)""",
        (g.company["id"],),
    )
    company = one("select * from companies where id = %s", (g.company["id"],))
    return render_template("fuel/settings.html", title="Fuel assistant", active="/fuel", company=company, prefs=prefs,
                           weekdays=list(enumerate(WEEKDAY_NAMES, start=1)), trucks=connected_trucks(), needs=fuel.NEEDS)


def connected_trucks():
    found = rows(
        """select t.id, t.unit_number, t.telegram_chat_title, t.fuel_percent, t.fuel_percent_at, t.location, t.located_at,
                  d.name as driver_name
           from trucks t left join drivers d on d.id = t.driver_id
           where t.company_id = %s and t.telegram_chat_id is not null and t.status <> 'sold'
           order by lower(t.unit_number)""",
        (g.company["id"],),
    )
    for truck in found:
        truck["label"] = fuel.unit_label(truck["unit_number"])
        trip = one(
            """select id, plan from trips where truck_id = %s and status in ('sent', 'accepted')
               order by id desc limit 1""",
            (truck["id"],),
        )
        truck["stop"] = truck["trip_id"] = truck["stop_sent_at"] = truck["answer"] = None
        since = None
        if trip:
            live = trip["plan"].get("live") or {}
            sent = live.get("sent") or {}
            stops = trip["plan"].get("fuel_stops") or []
            index = max((int(k) for k in sent), default=None)
            if index is not None and index < len(stops):
                truck["stop"] = stops[index]
                truck["trip_id"] = trip["id"]
                truck["stop_sent_at"] = datetime.fromisoformat(sent[str(index)]["at"]) if sent[str(index)].get("at") else None
                since = truck["stop_sent_at"]
                if sent[str(index)].get("confirmed"):
                    truck["answer"] = "will fuel there"
                if stops[index]["station_id"] in (live.get("skipped") or []):
                    truck["answer"] = "skipped"
        truck["offer"] = one(
            """select o.*, s.name as chosen_name from fuel_offers o left join fuel_stations s on s.id = o.chosen_station_id
               where o.truck_id = %s order by o.created_at desc limit 1""",
            (truck["id"],),
        )
        if not since and truck["offer"]:
            since = truck["offer"]["created_at"]
            truck["answer"] = {"accepted": "took a stop", "skipped": "skipped", "fueled": None}.get(truck["offer"]["status"])
        truck["refuel"] = one(
            """select r.*, s.name as station_name from fuel_refuels r left join fuel_stations s on s.id = r.station_id
               where r.truck_id = %s and r.detected_at >= coalesce(%s, now() - interval '3 days')
               order by r.detected_at desc limit 1""",
            (truck["id"], since),
        )
    return found


@bp.post("/fuel/settings")
@login_required
@role_required("admin")
def save_settings():
    values = {
        "enabled": request.form.get("fuel_assistant_enabled") == "on",
        "from_group": request.form.get("trips_from_group") == "on",
        "alert": min(80, max(5, forms.integer(request.form.get("fuel_alert_percent")) or 35)),
        "search": min(400, max(20, forms.integer(request.form.get("fuel_search_miles")) or 150)),
        "reserve": min(40, max(0, forms.integer(request.form.get("fuel_reserve_percent")) or 10)),
        "mpg": min(12, max(3, float(forms.decimal(request.form.get("fuel_default_mpg")) or 6.5))),
        "weekday": min(7, max(1, forms.integer(request.form.get("fuel_report_weekday")) or 1)),
        "hour": min(23, max(0, forms.integer(request.form.get("fuel_report_hour")) or 0)),
    }
    execute(
        """update companies set fuel_assistant_enabled = %(enabled)s, trips_from_group = %(from_group)s, fuel_alert_percent = %(alert)s,
             fuel_search_miles = %(search)s, fuel_reserve_percent = %(reserve)s, fuel_default_mpg = %(mpg)s,
             fuel_report_weekday = %(weekday)s, fuel_report_hour = %(hour)s, updated_at = now()
           where id = %(id)s""",
        {**values, "id": g.company["id"]},
    )
    audit("fuel.settings", "company", g.company["id"], values)
    flash("Fuel assistant settings saved.", "ok")
    return redirect("/fuel/settings")
