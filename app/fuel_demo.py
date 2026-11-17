import json
import random
from datetime import datetime, time, timedelta, timezone

from . import brand_prices, fuel
from .db import execute, insert, one, rows

MPG = 6.5
FILL_AT = 0.35
DEF_SHARE = 0.18
NO_DISCOUNT_SHARE = 0.05
PRICIER_SHARE = 0.2
SEARCH_MILES = 250


def daily_miles(truck_id, start, end):
    found = rows(
        """select read_at::date as day, max(miles) - min(miles) as miles from odometer_readings
           where truck_id = %s and read_at between %s and %s group by 1 order by 1""",
        (truck_id, start, end),
    )
    return {r["day"]: r["miles"] for r in found if r["miles"] and 0 < r["miles"] < 900}


def candidates(truck):
    if truck["latitude"] is None:
        return []
    found = [s for s in fuel.nearby_stations(truck["latitude"], truck["longitude"], SEARCH_MILES)
             if s["brand"] in ("Love's", "TA", "Petro")]
    retail = {r["station_id"]: float(r["retail_ppu"]) for r in rows(
        "select station_id, retail_ppu from station_retail_prices where fuel_type = 'diesel' and station_id = any(%s)",
        ([s["id"] for s in found],))}
    return [dict(s, retail=retail[s["id"]]) for s in found if s["id"] in retail]


def generate(company_id, days=28, seed=7):
    rng = random.Random(seed)
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)
    discounts = brand_prices.brand_discounts(company_id)
    trucks = rows(
        """select t.*, d.name as driver_name from trucks t left join drivers d on d.id = t.driver_id
           where t.company_id = %s and t.status = 'active' and t.driver_id is not null""",
        (company_id,),
    )
    added = 0
    for truck in trucks:
        stations = candidates(truck)
        miles_by_day = daily_miles(truck["id"], start, end)
        if not stations or not miles_by_day:
            continue
        tank = float(truck["tank_gallons"] or 200)
        level = tank * rng.uniform(0.5, 0.9)
        typical = sum(miles_by_day.values()) / len(miles_by_day)
        for offset in range(days):
            day = (start + timedelta(days=offset)).date()
            known = miles_by_day.get(day)
            level -= (known if known is not None else typical * rng.uniform(0.6, 1.3)) / MPG
            if level > tank * FILL_AT:
                continue
            ranked = sorted(stations, key=lambda s: s["retail"])
            station = rng.choice(ranked[len(ranked) // 2:]) if rng.random() < PRICIER_SHARE else rng.choice(ranked[:max(1, len(ranked) // 3)])
            drift = rng.uniform(-0.06, 0.06) + (days - offset) * rng.uniform(-0.003, 0.004)
            retail = round(station["retail"] + drift, 3)
            discount = 0.0 if rng.random() < NO_DISCOUNT_SHARE else max(0.0, discounts.get(station["brand"], 0.35) + rng.uniform(-0.05, 0.05))
            net = round(retail - discount, 3)
            gallons = round(min(tank - max(level, 0), tank * rng.uniform(0.55, 0.85)), 2)
            when = datetime.combine(day, time(rng.randint(5, 21), rng.randint(0, 59)), timezone.utc)
            level += gallons
            raw = {"demo": True, "location name": station["name"], "city": station["city"] or "", "state prov": station["state"],
                   "unit price": f"{retail:.3f}", "disc ppu": f"{net:.3f}", "driver name": truck["driver_name"]}
            entry = insert(
                """insert into fuel_transactions (company_id, truck_id, driver_id, purchased_at, gallons, price_per_gallon, total,
                     location, state, fuel_type, source, raw, station_id, retail_ppu, net_ppu, discount_ppu, fraud_checked_at)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'diesel', 'demo', %s, %s, %s, %s, %s, now()) returning id""",
                (company_id, truck["id"], truck["driver_id"], when, gallons, retail, round(gallons * net, 2),
                 f"{station['name']}, {station['city'] or ''}".strip(", ")[:160], station["state"], json.dumps(raw), station["id"],
                 retail, net, round(retail - net, 4)),
            )
            execute(
                """insert into fuel_prices (company_id, station_id, fuel_type, retail_ppu, net_ppu, observed_at, source, transaction_id)
                   values (%s, %s, 'diesel', %s, %s, %s, 'transaction', %s) on conflict do nothing""",
                (company_id, station["id"], retail, net, when, entry["id"]),
            )
            added += 1
            if rng.random() < DEF_SHARE:
                def_gallons = round(rng.uniform(5, 15), 2)
                def_price = round(rng.uniform(4.3, 4.9), 3)
                insert(
                    """insert into fuel_transactions (company_id, truck_id, driver_id, purchased_at, gallons, price_per_gallon, total,
                         location, state, fuel_type, source, raw, station_id, retail_ppu, net_ppu, discount_ppu, fraud_checked_at)
                       values (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'def', 'demo', %s, %s, %s, %s, 0, now()) returning id""",
                    (company_id, truck["id"], truck["driver_id"], when + timedelta(minutes=4), def_gallons, def_price,
                     round(def_gallons * def_price, 2), f"{station['name']}, {station['city'] or ''}".strip(", ")[:160],
                     station["state"], json.dumps({"demo": True}), station["id"], def_price, def_price),
                )
                added += 1
    return added


def remove(company_id):
    return execute("delete from fuel_transactions where company_id = %s and source = 'demo'", (company_id,))


def count(company_id):
    return one("select count(*) as n from fuel_transactions where company_id = %s and source = 'demo'", (company_id,))["n"]
