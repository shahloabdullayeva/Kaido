import json
import re
import time
from html import unescape

import requests

from . import fuel
from .db import execute, insert, one, rows
from .logs import get

log = get("brand-prices")

USER_AGENT = "Mozilla/5.0 (compatible; Kaido/1.0; +https://kaidofleet.com)"
PAUSE = 1.5
FRESH_HOURS = 30
LOVES_SITEMAP = "https://www.loves.com/sitemap-locations.xml"
LOVES_DIESEL = ("Diesel", "Bio-Diesel", "Ultra Low Sulfur Diesel", "Renewable Diesel")


def fetch(url):
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    return response.text


def count_after(page, label):
    match = re.search(re.escape(label) + r"(?:<!-- -->)?:\s*(?:<!-- -->)?\s*(\d+)", page)
    return int(match.group(1)) if match else None


def loves_page(url, page):
    text = page.replace('\\"', '"')
    start = text.find('"fuelPrices":[')
    if start < 0:
        return None
    end = text.find("]", start)
    try:
        products = json.loads(text[start + len('"fuelPrices":'):end + 1])
    except ValueError:
        return None
    diesel = [p for p in products if p.get("productName") == "DIESEL"] or \
        [p for p in products if any((p.get("fuelType") or "").startswith(kind) for kind in LOVES_DIESEL)]
    if not diesel or not diesel[0].get("cashPrice"):
        return None
    price = diesel[0]
    geo = re.search(r'"latitude":(-?[\d.]+),"longitude":(-?[\d.]+)', text)
    if not geo:
        return None
    store = re.search(r'"storeNumber":(\d+)', text)
    city = re.search(r'"addressLocality":"([^"]+)"', text)
    state = re.search(r'"addressRegion":"([A-Z]{2})"', text)
    street = re.search(r'"streetAddress":"([^"]+)"', text)
    parking = count_after(text, "Truck Parking")
    showers = count_after(text, "Shower Count")
    def_lanes = count_after(text, "DEF Lanes")
    amenities = {"parking": bool(parking), "showers": bool(showers) or "Showers" in text, "food": True,
                 "scale": "CAT Scale" in text, "def": bool(def_lanes), "repair": "Truck Care" in text or "Speedco" in text}
    if parking:
        amenities["spaces"] = str(parking)
    def_price = next((p for p in products if p.get("productName") == "DEF" and p.get("cashPrice")), None)
    return {
        "key": f"loves:{store.group(1) if store else url.rsplit('-', 1)[-1]}",
        "name": f"Love's #{store.group(1)}" if store else "Love's",
        "brand": "Love's", "latitude": float(geo.group(1)), "longitude": float(geo.group(2)),
        "city": unescape(city.group(1)) if city else None, "state": state.group(1) if state else None,
        "address": unescape(street.group(1)) if street else None, "amenities": amenities,
        "retail": float(price.get("creditPrice") or price["cashPrice"]), "cash": float(price["cashPrice"]),
        "changed_at": price.get("lastPriceChangeDateTime"),
        "def": float(def_price["cashPrice"]) if def_price else None,
    }


def save(found, source):
    twin = None
    for station in fuel.nearby_stations(found["latitude"], found["longitude"], 0.3):
        if station["brand"] == found["brand"] and station["source"] in ("osm", "brand"):
            twin = station
            break
    if twin and twin["key"] != found["key"]:
        merged = dict(twin["amenities"] or {})
        merged.update(found["amenities"])
        merged["typical"] = []
        execute(
            """update fuel_stations set name = %s, address = coalesce(%s, address), city = coalesce(%s, city),
                 amenities = %s, updated_at = now() where id = %s""",
            (found["name"], found["address"], found["city"], json.dumps(merged), twin["id"]),
        )
        station_id = twin["id"]
    else:
        station_id = insert(
            """insert into fuel_stations (key, name, brand, latitude, longitude, address, city, state, amenities,
                 located_by, source, updated_at)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'brand', 'brand', now())
               on conflict (key) do update set name = excluded.name, latitude = excluded.latitude,
                 longitude = excluded.longitude, address = excluded.address, city = excluded.city,
                 amenities = excluded.amenities, updated_at = now()
               returning id""",
            (found["key"], found["name"], found["brand"], found["latitude"], found["longitude"], found["address"],
             found["city"], found["state"], json.dumps(found["amenities"])),
        )["id"]
    for fuel_type, retail, cash in (("diesel", found["retail"], found["cash"]), ("def", found.get("def"), found.get("def"))):
        if not retail:
            continue
        execute(
            """insert into station_retail_prices (station_id, fuel_type, retail_ppu, cash_ppu, changed_at, fetched_at, source)
               values (%s, %s, %s, %s, %s, now(), %s)
               on conflict (station_id, fuel_type) do update set retail_ppu = excluded.retail_ppu,
                 cash_ppu = excluded.cash_ppu, changed_at = excluded.changed_at, fetched_at = now(), source = excluded.source""",
            (station_id, fuel_type, retail, cash, found.get("changed_at"), source),
        )
    return station_id


def loves(limit=None, only=None):
    run = insert("insert into brand_fetches (brand) values ('loves') returning id")
    sitemap = fetch(LOVES_SITEMAP)
    urls = [u for u in re.findall(r"<loc>([^<]+)</loc>", sitemap) if "travel-stop" in u]
    if only:
        urls = [u for u in urls if any(f"/locations/{s.lower()}/" in u for s in only)]
    pages = prices = failed = 0
    for url in urls[:limit] if limit else urls:
        try:
            found = loves_page(url, fetch(url))
            pages += 1
            if found:
                save(found, "loves")
                prices += 1
        except (requests.RequestException, ValueError) as err:
            failed += 1
            log.info("Love's page %s failed: %s", url, err)
            if failed >= 25 and failed > pages:
                break
        time.sleep(PAUSE)
    execute("update brand_fetches set finished_at = now(), pages = %s, prices = %s, failed = %s where id = %s",
            (pages, prices, failed, run["id"]))
    return {"pages": pages, "prices": prices, "failed": failed}


FETCHERS = {"loves": loves}


def run(brands=None, limit=None, only=None):
    done = {}
    for name in brands or FETCHERS:
        try:
            done[name] = FETCHERS[name](limit=limit, only=only)
        except requests.RequestException as err:
            log.warning("%s price fetch failed: %s", name, err)
            done[name] = {"error": str(err)[:200]}
    return done


def brand_discounts(company_id, days=60):
    found = rows(
        """select s.brand, avg(f.discount_ppu) as discount, count(*) as fills
           from fuel_transactions f join fuel_stations s on s.id = f.station_id
           where f.company_id = %s and f.fuel_type = 'diesel' and f.discount_ppu is not null and s.brand is not null
             and f.purchased_at > now() - make_interval(days => %s)
           group by s.brand having count(*) >= 2""",
        (company_id, days),
    )
    if not found:
        found = rows(
            """select s.brand, avg(f.discount_ppu) as discount, count(*) as fills
               from fuel_transactions f join fuel_stations s on s.id = f.station_id
               where f.company_id = %s and f.fuel_type = 'diesel' and f.discount_ppu is not null and s.brand is not null
               group by s.brand having count(*) >= 2""",
            (company_id,),
        )
    return {r["brand"]: float(r["discount"]) for r in found}


def website_prices(company_id, station_ids, fuel_type="diesel"):
    if not station_ids:
        return {}
    found = rows(
        """select r.*, s.brand from station_retail_prices r join fuel_stations s on s.id = r.station_id
           where r.station_id = any(%s) and r.fuel_type = %s and r.fetched_at > now() - make_interval(hours => %s)""",
        (list(station_ids), fuel_type, FRESH_HOURS),
    )
    discounts = brand_discounts(company_id)
    priced = {}
    for row in found:
        discount = discounts.get(row["brand"], 0.0)
        priced[row["station_id"]] = {
            "station_id": row["station_id"], "retail_ppu": row["retail_ppu"],
            "net_ppu": round(float(row["retail_ppu"]) - discount, 4),
            "observed_at": row["fetched_at"],
            "fetched_at": row["fetched_at"], "source": "website", "estimated_discount": round(discount, 4),
        }
    return priced
