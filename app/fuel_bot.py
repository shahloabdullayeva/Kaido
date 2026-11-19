import json
from datetime import datetime, timedelta, timezone
from html import escape

from . import brand_prices, fuel
from .db import execute, insert, one, rows
from .logs import get
from .telegram import answer, call, edit, send

log = get("fuel-bot")

FRESH_MINUTES = 90
REPEAT_HOURS = 4
URGENT_PERCENT = 15
URGENT_REPEAT_MINUTES = 90
SNOOZE_MINUTES = 90
EXPIRE_HOURS = 12
SHOWN = 3
AGE_PENALTY_PER_DAY = 0.004
KEPT = 6
AHEAD_DEGREES = 70
NEAR_MILES = 12
NUMBERS = ["1.", "2.", "3.", "4.", "5.", "6."]
SKIP_REASONS = [
    ("busy", "Already fueling"),
    ("far", "Off my route"),
    ("park", "No parking there"),
    ("brand", "Don't like this brand"),
    ("price", "Found cheaper"),
    ("later", "Remind me later"),
]
SKIP_TEXT = dict(SKIP_REASONS)
PERCENTS = [20, 25, 30, 35, 40, 50]
PREF_BRANDS = ["Pilot", "Flying J", "Love's", "TA", "Petro"]
GENERIC_NAMES = {"gas pumps", "fuel station", "gas station", "fuel", "diesel", "truck lanes", "diesel lanes",
                 "truck fuel", "fuel pumps", "truck stop", "travel center"}
COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
SAME_SPOT_MILES = 0.35

TRUCK_SQL = """select t.*, d.name as driver_name, d.telegram_username, d.telegram_user_id,
                      c.fuel_alert_percent, c.fuel_search_miles, c.fuel_reserve_percent, c.fuel_default_mpg,
                      c.fuel_assistant_enabled, c.name as company_name
               from trucks t join companies c on c.id = t.company_id
               left join drivers d on d.id = t.driver_id"""


def prefs_for(truck):
    if not truck.get("driver_id"):
        return {"brands_liked": [], "brands_avoided": [], "stations_avoided": [], "needs": [], "alert_percent": None,
                "learned": {}}
    found = one("select * from driver_fuel_prefs where driver_id = %s", (truck["driver_id"],))
    if found:
        return found
    return insert(
        """insert into driver_fuel_prefs (driver_id, company_id) values (%s, %s)
           on conflict (driver_id) do update set updated_at = driver_fuel_prefs.updated_at returning *""",
        (truck["driver_id"], truck["company_id"]),
    )


def learn(truck, kind, key, amount=1):
    if not truck.get("driver_id"):
        return 0
    prefs = prefs_for(truck)
    learned = prefs["learned"] or {}
    bucket = learned.setdefault(kind, {})
    bucket[key] = bucket.get(key, 0) + amount
    execute("update driver_fuel_prefs set learned = %s, updated_at = now() where driver_id = %s",
            (json.dumps(learned), truck["driver_id"]))
    return bucket[key]


def usual_brands(truck):
    if not truck.get("driver_id"):
        return set()
    found = rows(
        """select s.brand, count(*) as n from fuel_transactions f join fuel_stations s on s.id = f.station_id
           where f.driver_id = %s and f.fuel_type = 'diesel' and s.brand is not null
             and f.purchased_at > now() - interval '90 days' group by s.brand""",
        (truck["driver_id"],),
    )
    total = sum(r["n"] for r in found)
    return {r["brand"] for r in found if r["n"] >= 3 and total and r["n"] / total >= 0.3}


def mpg_of(truck):
    return fuel.truck_mpg(truck["id"]) or float(truck["fuel_default_mpg"] or 6.5)


def range_of(truck, mpg):
    if truck.get("fuel_percent") is None:
        return None
    usable = max(0.0, float(truck["fuel_percent"]) - float(truck["fuel_reserve_percent"] or 10)) / 100
    return int(usable * float(truck["tank_gallons"] or 200) * mpg)


def suggestions(truck, prefs=None, limit=KEPT):
    prefs = prefs or prefs_for(truck)
    mpg = mpg_of(truck)
    reach = range_of(truck, mpg)
    radius = min(int(truck["fuel_search_miles"] or 150), reach / fuel.ROAD_FACTOR) if reach else int(truck["fuel_search_miles"] or 150)
    radius = max(radius, 15)
    stations = fuel.nearby_stations(truck["latitude"], truck["longitude"], radius)
    moving = truck.get("heading") is not None and float(truck.get("speed_mph") or 0) >= 10
    avoided_brands = set(prefs["brands_avoided"] or [])
    avoided_stations = set(prefs["stations_avoided"] or [])
    liked = set(prefs["brands_liked"] or []) | usual_brands(truck)
    needs = set(prefs["needs"] or [])
    picked = []
    for station in stations:
        if station["id"] in avoided_stations or (station["brand"] and station["brand"] in avoided_brands):
            continue
        amenities = station["amenities"] or {}
        if any(amenities.get(need) is False for need in needs):
            continue
        if station["source"] == "transaction" and (station["located_by"] or "").startswith("osm:"):
            continue
        ahead = True
        if moving and station["miles"] > NEAR_MILES:
            ahead = fuel.angle_between(truck["heading"], fuel.bearing(
                truck["latitude"], truck["longitude"], station["latitude"], station["longitude"])) <= AHEAD_DEGREES
        if not ahead:
            continue
        station["road_miles"] = round(station["miles"] * fuel.ROAD_FACTOR)
        direction = fuel.bearing(truck["latitude"], truck["longitude"], station["latitude"], station["longitude"])
        station["compass"] = COMPASS[int((direction + 22.5) // 45) % 8]
        station["behind"] = moving and station["miles"] > 1 and fuel.angle_between(truck["heading"], direction) > 100
        picked.append(station)
    prices = fuel.latest_prices(truck["company_id"], [s["id"] for s in picked])
    fresh_after = datetime.now(timezone.utc) - timedelta(days=fuel.PRICE_FRESH_DAYS)
    stale = [s["id"] for s in picked if s["id"] not in prices or prices[s["id"]]["observed_at"] < fresh_after]
    prices.update(brand_prices.website_prices(truck["company_id"], stale))
    tank = float(truck["tank_gallons"] or 200)
    pct = float(truck["fuel_percent"] or 30)
    options = []
    for station in picked:
        price = prices.get(station["id"])
        fill = max(20.0, tank * (1 - pct / 100) + station["road_miles"] / mpg)
        score = float(price["net_ppu"]) if price else 99.0
        if price and price["source"] != "website":
            age = (datetime.now(timezone.utc) - price["observed_at"]).days
            score += AGE_PENALTY_PER_DAY * max(0, age - 1)
        score += station["road_miles"] * 0.0004
        if station["behind"] and price:
            score += station["road_miles"] * 2 / mpg * float(price["net_ppu"]) / fill + 0.04
        if station["brand"] in liked:
            score -= 0.03
        if needs and not all((station["amenities"] or {}).get(n) for n in needs):
            score += 0.05
        if not price and station["brand"] not in fuel.TRUCK_STOP_BRANDS:
            continue
        options.append({
            "station_id": station["id"], "name": display_name(station), "brand": station["brand"],
            "compass": station["compass"], "behind": station["behind"],
            "city": station["city"], "state": station["state"], "miles": station["road_miles"],
            "latitude": float(station["latitude"]), "longitude": float(station["longitude"]),
            "net": float(price["net_ppu"]) if price else None,
            "retail": float(price["retail_ppu"]) if price and price["retail_ppu"] else None,
            "price_at": price["observed_at"].isoformat() if price else None,
            "price_source": price["source"] if price else None,
            "estimated_discount": price.get("estimated_discount") if price else None,
            "amenities": station["amenities"] or {}, "fill": round(fill), "score": round(score, 4),
            "liked": station["brand"] in liked,
        })
    options.sort(key=lambda o: o["score"])
    unique = []
    for option in options:
        if not any(fuel.haversine(option["latitude"], option["longitude"], kept["latitude"], kept["longitude"]) < SAME_SPOT_MILES
                   for kept in unique):
            unique.append(option)
    options = unique
    priced = [o for o in options if o["net"] is not None]
    unpriced = [o for o in options if o["net"] is None]
    chosen = priced[:limit]
    if len(chosen) < SHOWN:
        chosen += sorted(unpriced, key=lambda o: o["miles"])[:SHOWN - len(chosen)]
    reference = None
    if priced:
        nearest = min(priced, key=lambda o: o["miles"])
        reference = nearest["net"]
        worst = max(o["net"] for o in priced)
        for option in chosen:
            if option["net"] is not None:
                option["saves"] = round((reference - option["net"]) * option["fill"], 2)
                option["vs_worst"] = round((worst - option["net"]) * option["fill"], 2)
    return {"options": chosen, "mpg": mpg, "range": reach, "radius": round(radius), "reference": reference}


def display_name(station):
    name = " ".join((station["name"] or "").split())
    brand = station["brand"]
    if not brand:
        return name or "Fuel stop"
    if name.lower() in GENERIC_NAMES or not name:
        return brand
    if brand.lower().replace("'", "") not in name.lower().replace("'", ""):
        return f"{brand} · {name}"
    return name


def option_lines(index, option):
    where = ", ".join(p for p in [option.get("city"), option.get("state")] if p)
    head = f"{NUMBERS[index]} <b>{escape(option['name'])}</b>" + (f", {escape(where)}" if where else "")
    head += f" · {option['miles']} mi"
    price = f"${option['net']:.2f}" if option["net"] is not None else "price unknown"
    if option.get("saves") and option["saves"] >= 5:
        price += f" · saves ${option['saves']:.0f}"
    return [head, f"{price} · <a href=\"{fuel.maps_link(option)}\">Map</a>"]


def card(truck, offer, options, page=0):
    pct = offer["fuel_percent"]
    top = f"<b>Fuel</b> · Unit {escape(fuel.unit_label(truck['unit_number']))}"
    if pct is not None:
        top += f" · Tank {float(pct):.0f}%"
    who = mention(truck)
    lines = [top + (f" {who}" if who else "")]
    shown = options[page * SHOWN:(page + 1) * SHOWN]
    if not shown:
        lines.append("No priced truck stops in range. Fuel at the next big truck stop.")
    for index, option in enumerate(shown):
        lines += option_lines(page * SHOWN + index, option)
    return "\n".join(lines)


def keyboard(offer_id, options, page=0):
    shown = options[page * SHOWN:(page + 1) * SHOWN]
    buttons = [[{"text": f"Take {NUMBERS[page * SHOWN + i]} {short(o)}", "callback_data": f"fa:{offer_id}:{page * SHOWN + i}"}]
               for i, o in enumerate(shown)]
    row = [{"text": "Skip", "callback_data": f"fs:{offer_id}"}]
    if len(options) > (page + 1) * SHOWN:
        row.append({"text": "More stops", "callback_data": f"fm:{offer_id}:{page + 1}"})
    elif page:
        row.append({"text": "First stops", "callback_data": f"fm:{offer_id}:0"})
    buttons.append(row)
    return {"inline_keyboard": buttons}


def short(option):
    name = option["name"] if len(option["name"]) <= 14 else (option["brand"] or option["name"])
    price = f" ${option['net']:.2f}" if option["net"] is not None else ""
    return f"{name[:16]}{price} · {option['miles']} mi"


def mention(truck):
    if truck.get("telegram_username"):
        return "@" + escape(truck["telegram_username"])
    if truck.get("telegram_user_id"):
        return f"<a href=\"tg://user?id={int(truck['telegram_user_id'])}\">{escape(truck.get('driver_name') or 'driver')}</a>"
    return ""


def offer_for(truck, reason):
    prefs = prefs_for(truck)
    found = suggestions(truck, prefs)
    offer = insert(
        """insert into fuel_offers (company_id, truck_id, driver_id, chat_id, reason, fuel_percent, range_miles,
             latitude, longitude, options)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning *""",
        (truck["company_id"], truck["id"], truck["driver_id"], truck["telegram_chat_id"], reason,
         truck["fuel_percent"], found["range"], truck["latitude"], truck["longitude"], json.dumps(found["options"])),
    )
    result = send(truck["telegram_chat_id"], card(truck, offer, found["options"]),
                  reply_markup=keyboard(offer["id"], found["options"]))
    execute("update fuel_offers set message_id = %s, status = %s where id = %s",
            (result.get("message_id"), "sent" if result.get("ok") else "failed", offer["id"]))
    return offer["id"], bool(result.get("ok"))


def should_offer(truck, prefs):
    if truck["fuel_percent"] is None:
        return False
    threshold = prefs.get("alert_percent") or truck["fuel_alert_percent"] or 35
    pct = float(truck["fuel_percent"])
    if pct > threshold:
        return False
    last = one("select * from fuel_offers where truck_id = %s and reason = 'low' order by created_at desc limit 1",
               (truck["id"],))
    if not last:
        return True
    age = datetime.now(timezone.utc) - last["created_at"]
    if last["skip_reason"] == "later":
        return age > timedelta(minutes=SNOOZE_MINUTES)
    if last["skip_reason"] == "busy" or last["status"] == "fueled":
        refilled = last["fuel_percent"] is None or pct > float(last["fuel_percent"]) + 10
        return refilled or age > timedelta(hours=REPEAT_HOURS * 2)
    if pct <= URGENT_PERCENT and age > timedelta(minutes=URGENT_REPEAT_MINUTES):
        return True
    if last["fuel_percent"] is not None and pct > float(last["fuel_percent"]) + 15:
        return True
    return age > timedelta(hours=REPEAT_HOURS)


def ready_trucks(force=False):
    return rows(
        TRUCK_SQL + """ where c.status = 'active' and t.status = 'active' and t.telegram_chat_id is not null
                         and t.latitude is not null and t.fuel_percent is not null
                         and t.fuel_percent_at > now() - make_interval(mins => %s)
                         and t.located_at > now() - make_interval(mins => %s)""" + ("" if force else " and c.fuel_assistant_enabled"),
        (FRESH_MINUTES, FRESH_MINUTES),
    )


def match_refuels():
    matched = 0
    for event in fuel.detect_refuels():
        offer = one(
            """select * from fuel_offers where truck_id = %s and status in ('sent', 'accepted', 'skipped')
                 and created_at between %s and %s order by created_at desc limit 1""",
            (event["truck_id"], event["at"] - timedelta(hours=EXPIRE_HOURS), event["at"]),
        )
        if not offer:
            continue
        options = offer["options"] or []
        near = [o for o in options if fuel.haversine(event["latitude"], event["longitude"], o["latitude"], o["longitude"]) <= 2]
        chosen_ok = offer["chosen_station_id"] and any(o["station_id"] == offer["chosen_station_id"] for o in near)
        execute("update fuel_offers set status = 'fueled', followed = %s where id = %s",
                (bool(chosen_ok or (near and not offer["chosen_station_id"])), offer["id"]))
        matched += 1
    return matched


def match_transactions():
    matched = 0
    todo = rows(
        """select f.* from fuel_transactions f where f.offer_id is null and f.fuel_type = 'diesel'
             and f.net_ppu is not null and f.purchased_at > now() - interval '45 days'"""
    )
    for entry in todo:
        offer = one(
            """select * from fuel_offers where truck_id = %s and transaction_id is null and status <> 'failed'
                 and created_at between %s and %s order by created_at desc limit 1""",
            (entry["truck_id"], entry["purchased_at"] - timedelta(hours=18), entry["purchased_at"]),
        )
        if not offer:
            continue
        options = offer["options"] or []
        followed = None
        if entry["station_id"]:
            used = fuel.resolve_station(one("select * from fuel_stations where id = %s", (entry["station_id"],)))
            ids = {used["id"], entry["station_id"]}
            followed = (offer["chosen_station_id"] in ids) if offer["chosen_station_id"] else any(o["station_id"] in ids for o in options)
        priced = [o for o in options if o.get("net") is not None]
        saved = None
        if priced:
            nearest = min(priced, key=lambda o: o["miles"])
            saved = round((nearest["net"] - float(entry["net_ppu"])) * float(entry["gallons"]), 2)
        execute("update fuel_transactions set offer_id = %s where id = %s", (offer["id"], entry["id"]))
        execute("update fuel_offers set transaction_id = %s, followed = coalesce(%s, followed), saved_usd = %s, status = 'fueled' where id = %s",
                (entry["id"], followed, saved, offer["id"]))
        matched += 1
    return matched


def run(force=False):
    sent = []
    for truck in ready_trucks(force):
        prefs = prefs_for(truck)
        if should_offer(truck, prefs):
            offer_id, ok = offer_for(truck, "low")
            sent.append((truck["unit_number"], offer_id, ok))
    execute("""update fuel_offers set status = 'expired' where status = 'sent'
               and created_at < now() - make_interval(hours => %s)""", (EXPIRE_HOURS,))
    fuel.enrich()
    fuel.analyse()
    return {"offers": sent, "refuels": match_refuels(), "receipts": match_transactions(), "fueled": refuel_notices()}


REFUEL_RISE = 15
REFUEL_LOOKBACK_HOURS = 3
STATION_NEAR_MILES = 1.0
PLAN_MATCH_MILES = 2
OFF_TRIP_MILES = 15


def best_station(near):
    if not near:
        return None
    close = [s for s in near if s["miles"] <= near[0]["miles"] + 0.3]
    return sorted(close, key=lambda s: ("#" not in (s["name"] or ""), s["source"] != "brand", s["miles"]))[0]


def fill_place(points):
    for point in points:
        station = best_station(fuel.nearby_stations(point["latitude"], point["longitude"], STATION_NEAR_MILES))
        if station:
            return point, station
    return points[0], None


def check_plan(trip, spot, station):
    from . import trips as trip_plans
    points, miles = trip_plans.route_of(trip)
    _, off = trip_plans.locate(points, miles, float(spot["latitude"]), float(spot["longitude"]))
    if off > OFF_TRIP_MILES:
        return None, None
    stops = trip["plan"]["fuel_stops"]
    for stop in stops:
        if station and stop.get("station_id") == station["id"]:
            return True, stop
        if fuel.haversine(spot["latitude"], spot["longitude"], stop["latitude"], stop["longitude"]) <= PLAN_MATCH_MILES:
            return True, stop
    current = ((trip["plan"] or {}).get("live") or {}).get("current", 0)
    return False, stops[current] if current < len(stops) else None


def active_trip(truck_id):
    return one(
        """select * from trips where truck_id = %s and status in ('sent', 'accepted') and chat_id is not null
             and created_at > now() - interval '8 days' order by id desc limit 1""",
        (truck_id,),
    )


def refuel_notices():
    sent = []
    trucks = rows(
        TRUCK_SQL + """ where t.telegram_chat_id is not null and t.fuel_percent is not null
                         and t.fuel_percent_at > now() - interval '1 hour' and c.status = 'active'"""
    )
    for truck in trucks:
        trip = active_trip(truck["id"])
        if not truck["fuel_assistant_enabled"] and not trip:
            continue
        track = rows(
            """select fuel_percent, latitude, longitude, speed_mph, recorded_at from truck_positions
               where truck_id = %s and fuel_percent is not null and recorded_at > now() - make_interval(hours => %s)
               order by recorded_at""",
            (truck["id"], REFUEL_LOOKBACK_HOURS),
        )
        if len(track) < 2:
            continue
        low_index = min(range(len(track)), key=lambda i: float(track[i]["fuel_percent"]))
        low, last = track[low_index], track[-1]
        rise = float(last["fuel_percent"]) - float(low["fuel_percent"])
        if rise < REFUEL_RISE or low_index == len(track) - 1:
            continue
        settled = float(last["speed_mph"] or 0) > 5 or abs(float(last["fuel_percent"]) - float(track[-2]["fuel_percent"])) < 3
        if not settled:
            continue
        if one("select id from fuel_refuels where truck_id = %s and started_at > %s - interval '2 hours'",
               (truck["id"], low["recorded_at"])):
            continue
        after = [p for p in track[low_index + 1:] if float(p["fuel_percent"]) - float(low["fuel_percent"]) >= 5]
        rise_point = after[0] if after else last
        window = track[max(0, low_index - 1):track.index(rise_point) + 1]
        stopped = [p for p in window if float(p["speed_mph"] or 0) <= 5]
        spot, station = fill_place(stopped + [low, rise_point])
        gallons = round(rise / 100 * float(truck["tank_gallons"] or 200))
        planned = None
        planned_stop = None
        if trip:
            planned, planned_stop = check_plan(trip, spot, station)
        lines = [f"<b>Fueled</b> · Unit {escape(fuel.unit_label(truck['unit_number']))}"]
        if station:
            where = ", ".join(p for p in [station["city"], station["state"]] if p)
            lines.append(escape(station["name"]) + (f", {escape(where)}" if where else ""))
        lines.append(f"{float(low['fuel_percent']):.0f}% to {float(last['fuel_percent']):.0f}% · about {gallons} gal")
        if station:
            price = (brand_prices.website_prices(truck["company_id"], [station["id"]]).get(station["id"])
                     or fuel.latest_prices(truck["company_id"], [station["id"]]).get(station["id"]))
            if price:
                lines[-1] += f" · about ${gallons * float(price['net_ppu']):,.0f}"
        if planned is True:
            lines.append("Planned stop. Good.")
        elif planned is False and planned_stop:
            where = ", ".join(p for p in [planned_stop.get("city"), planned_stop.get("state")] if p)
            lines.append(f"Not the planned stop. Plan was {escape(planned_stop['name'])}" + (f", {escape(where)}." if where else "."))
        result = send(truck["telegram_chat_id"], "\n".join(lines))
        insert(
            """insert into fuel_refuels (company_id, truck_id, started_at, from_percent, to_percent, gallons, latitude, longitude,
                 station_id, trip_id, planned, message_id)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               on conflict (truck_id, started_at) do nothing returning id""",
            (truck["company_id"], truck["id"], low["recorded_at"], low["fuel_percent"], last["fuel_percent"], gallons,
             spot["latitude"], spot["longitude"], station["id"] if station else None, trip["id"] if trip else None,
             planned, result.get("message_id")),
        )
        sent.append((truck["unit_number"], gallons, bool(result.get("ok"))))
    return sent


def load_offer(offer_id):
    offer = one("select * from fuel_offers where id = %s", (offer_id,))
    if not offer:
        return None, None
    truck = one(TRUCK_SQL + " where t.id = %s", (offer["truck_id"],))
    return offer, truck


def handle_callback(query):
    data = query.get("data") or ""
    message = query.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    message_id = message.get("message_id")
    user = query.get("from") or {}
    parts = data.split(":")
    kind = parts[0]
    if kind == "fp":
        return prefs_callback(query, parts, chat_id, message_id)
    try:
        offer_id = int(parts[1])
    except (IndexError, ValueError):
        answer(query["id"])
        return True
    offer, truck = load_offer(offer_id)
    if not offer or offer["chat_id"] != chat_id:
        answer(query["id"], "This suggestion is no longer active.")
        return True
    options = offer["options"] or []
    if kind == "fm":
        page = int(parts[2]) if len(parts) > 2 else 0
        edit(chat_id, message_id, card(truck, offer, options, page), reply_markup=keyboard(offer_id, options, page))
        answer(query["id"])
        return True
    if kind == "fb":
        edit(chat_id, message_id, card(truck, offer, options), reply_markup=keyboard(offer_id, options))
        answer(query["id"])
        return True
    if kind == "fs":
        buttons = [[{"text": text, "callback_data": f"fr:{offer_id}:{code}"}] for code, text in SKIP_REASONS]
        buttons.append([{"text": "Back to stops", "callback_data": f"fb:{offer_id}"}])
        call("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": buttons}})
        answer(query["id"], "Why skip? It helps Kaido pick better stops.")
        return True
    if kind == "fa":
        index = int(parts[2]) if len(parts) > 2 else 0
        if index >= len(options):
            answer(query["id"])
            return True
        option = options[index]
        execute(
            """update fuel_offers set status = 'accepted', chosen_station_id = %s, answered_by = %s, answered_at = now()
               where id = %s""",
            (option["station_id"], user.get("id"), offer_id),
        )
        if option.get("brand"):
            learn(truck, "accepted", option["brand"])
        who = escape(user.get("first_name") or user.get("username") or "Driver")
        lines = [f"<b>Unit {escape(fuel.unit_label(truck['unit_number']))}</b> — {who} is going to:", ""]
        lines += option_lines(index, option)
        lines += ["", "Kaido will match the receipt when it comes in. Drive safe."]
        edit(chat_id, message_id, "\n".join(lines))
        call("sendVenue", {"chat_id": chat_id, "latitude": option["latitude"], "longitude": option["longitude"],
                           "title": option["name"][:60],
                           "address": ", ".join(p for p in [option.get("city"), option.get("state")] if p) or "Fuel stop",
                           "reply_to_message_id": message_id})
        answer(query["id"], "Saved. Tap the location to navigate.")
        return True
    if kind == "fr":
        code = parts[2] if len(parts) > 2 else "other"
        execute(
            """update fuel_offers set status = 'skipped', skip_reason = %s, answered_by = %s, answered_at = now()
               where id = %s""",
            (code, user.get("id"), offer_id),
        )
        extra = ""
        top = options[0] if options else None
        if code == "brand" and top and top.get("brand") and truck.get("driver_id"):
            count = learn(truck, "brand_skips", top["brand"])
            if count >= 2:
                execute(
                    """update driver_fuel_prefs set brands_avoided = array(select distinct unnest(brands_avoided || %s::text[])),
                         updated_at = now() where driver_id = %s""",
                    ([top["brand"]], truck["driver_id"]),
                )
                extra = f"\nGot it — no more {escape(top['brand'])} suggestions. Change it any time with /fuelprefs."
            else:
                extra = f"\nNoted. Skip {escape(top['brand'])} once more and Kaido will stop suggesting it."
        if code == "park" and top and truck.get("driver_id"):
            learn(truck, "no_parking", str(top["station_id"]))
        if code == "far" and top:
            learn(truck, "off_route", str(top["station_id"]))
        tail = "I'll check again in about 90 minutes." if code == "later" else "OK, no suggestion this time."
        edit(chat_id, message_id, f"<b>Unit {escape(fuel.unit_label(truck['unit_number']))}</b> — skipped: {SKIP_TEXT.get(code, code)}.\n{tail}{extra}")
        answer(query["id"], "Thanks — noted.")
        return True
    answer(query["id"])
    return True


def prefs_text(truck, prefs):
    threshold = prefs.get("alert_percent") or truck["fuel_alert_percent"]
    lines = [f"<b>Fuel preferences — Unit {escape(fuel.unit_label(truck['unit_number']))}</b>"
             + (f" ({escape(fuel.person(truck['driver_name']))})" if truck.get("driver_name") else "")]
    lines.append(f"Remind me at: <b>{threshold}%</b> tank")
    lines.append("Must have: " + (", ".join(fuel.NEEDS[n] for n in prefs["needs"] if n in fuel.NEEDS) or "nothing special"))
    lines.append("Favourite brands: " + (", ".join(prefs["brands_liked"]) or "—"))
    lines.append("Never suggest: " + (", ".join(prefs["brands_avoided"]) or "—"))
    usual = usual_brands(truck)
    if usual:
        lines.append("Kaido noticed you usually fuel at: " + ", ".join(sorted(usual)))
    lines += ["", "Tap to change. Tapping a brand cycles: favourite, then never, then normal."]
    return "\n".join(lines)


def prefs_keyboard(truck, prefs):
    threshold = prefs.get("alert_percent") or truck["fuel_alert_percent"]
    tid = truck["id"]
    rows_out = [[{"text": f"Remind at {threshold}% (tap to change)", "callback_data": f"fp:{tid}:pct"}]]
    needs = []
    for key in ("parking", "showers", "scale", "def", "food", "repair"):
        on = key in (prefs["needs"] or [])
        needs.append({"text": ("[x] " if on else "[ ] ") + fuel.NEEDS[key], "callback_data": f"fp:{tid}:n:{key}"})
    rows_out += [needs[:3], needs[3:]]
    brands = []
    for brand in PREF_BRANDS:
        mark = "Fav: " if brand in (prefs["brands_liked"] or []) else "Never: " if brand in (prefs["brands_avoided"] or []) else ""
        brands.append({"text": mark + brand, "callback_data": f"fp:{tid}:b:{PREF_BRANDS.index(brand)}"})
    rows_out += [brands[:3], brands[3:]]
    return {"inline_keyboard": rows_out}


def prefs_callback(query, parts, chat_id, message_id):
    try:
        truck_id = int(parts[1])
    except (IndexError, ValueError):
        answer(query["id"])
        return True
    truck = one(TRUCK_SQL + " where t.id = %s and t.telegram_chat_id = %s", (truck_id, chat_id))
    if not truck or not truck["driver_id"]:
        answer(query["id"], "This truck has no driver set yet. Send /unit first.")
        return True
    prefs = prefs_for(truck)
    action = parts[2] if len(parts) > 2 else ""
    if action == "pct":
        current = prefs["alert_percent"] or truck["fuel_alert_percent"]
        later = [p for p in PERCENTS if p > current]
        execute("update driver_fuel_prefs set alert_percent = %s, updated_at = now() where driver_id = %s",
                (later[0] if later else PERCENTS[0], truck["driver_id"]))
    elif action == "n" and len(parts) > 3 and parts[3] in fuel.NEEDS:
        needs = set(prefs["needs"] or [])
        needs ^= {parts[3]}
        execute("update driver_fuel_prefs set needs = %s, updated_at = now() where driver_id = %s",
                (sorted(needs), truck["driver_id"]))
    elif action == "b" and len(parts) > 3:
        brand = PREF_BRANDS[int(parts[3]) % len(PREF_BRANDS)]
        liked = set(prefs["brands_liked"] or [])
        avoided = set(prefs["brands_avoided"] or [])
        if brand in liked:
            liked.discard(brand)
            avoided.add(brand)
        elif brand in avoided:
            avoided.discard(brand)
        else:
            liked.add(brand)
        execute("update driver_fuel_prefs set brands_liked = %s, brands_avoided = %s, updated_at = now() where driver_id = %s",
                (sorted(liked), sorted(avoided), truck["driver_id"]))
    prefs = prefs_for(truck)
    edit(chat_id, message_id, prefs_text(truck, prefs), reply_markup=prefs_keyboard(truck, prefs))
    answer(query["id"], "Saved.")
    return True


def group_truck(chat_id, message):
    trucks = rows(TRUCK_SQL + " where t.telegram_chat_id = %s and t.status <> 'sold' order by t.id", (chat_id,))
    if len(trucks) <= 1:
        return trucks[0] if trucks else None
    sender = (message.get("from") or {}).get("id")
    mine = [t for t in trucks if t["telegram_user_id"] == sender]
    return mine[0] if len(mine) == 1 else None


def handle_command(command, chat_id, message):
    if command not in ("/fuel", "/fuelprefs", "/fuelweek"):
        return False
    truck = group_truck(chat_id, message)
    if not truck:
        send(chat_id, "This group is not connected to one truck. Ask the office for the /truck code, then send /unit.")
        return True
    if command == "/fuelprefs":
        if not truck["driver_id"]:
            send(chat_id, "No driver is set for this truck yet. Send /unit first.")
            return True
        prefs = prefs_for(truck)
        send(chat_id, prefs_text(truck, prefs), reply_markup=prefs_keyboard(truck, prefs))
        return True
    if command == "/fuelweek":
        from . import fuel_report
        fuel_report.send_driver(truck, force=True)
        return True
    if truck["latitude"] is None:
        send(chat_id, "Kaido doesn't have this truck's location yet, so it can't pick a stop.")
        return True
    offer_for(truck, "asked")
    return True
