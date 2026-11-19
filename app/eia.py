from datetime import date, datetime

import requests
import xlrd

from .db import execute, one, rows
from .logs import get

log = get("eia")

URL = "https://www.eia.gov/dnav/pet/xls/PET_PRI_GND_A_EPD2D_PTE_DPGAL_W.xls"
USER_AGENT = "Kaido/1.0 (+https://kaidofleet.com)"
FRESH_DAYS = 21
REGION_PENALTY = 0.10

SERIES = {
    "New England (PADD 1A)": "1A",
    "Central Atlantic (PADD 1B)": "1B",
    "Lower Atlantic (PADD 1C)": "1C",
    "Midwest": "2",
    "Gulf Coast": "3",
    "Rocky Mountain": "4",
    "West Coast (PADD 5) Except California": "5",
    "California": "CA",
    "U.S.": "US",
}

STATES = {
    "1A": "CT ME MA NH RI VT",
    "1B": "DE DC MD NJ NY PA",
    "1C": "FL GA NC SC VA WV",
    "2": "IL IN IA KS KY MI MN MO NE ND SD OH OK TN WI",
    "3": "AL AR LA MS NM TX",
    "4": "CO ID MT UT WY",
    "5": "AK AZ HI NV OR WA",
    "CA": "CA",
}
REGION_OF = {state: region for region, states in STATES.items() for state in states.split()}
NAMES = {"1A": "New England", "1B": "Central Atlantic", "1C": "Lower Atlantic", "2": "Midwest", "3": "Gulf Coast",
         "4": "Rocky Mountain", "5": "West Coast", "CA": "California", "US": "U.S."}


def region_for(series_name):
    text = series_name.replace("Weekly ", "", 1)
    for label, code in sorted(SERIES.items(), key=lambda item: -len(item[0])):
        if text.startswith(label + " No 2 Diesel"):
            return code
    return None


def fetch(weeks=60):
    response = requests.get(URL, headers={"User-Agent": USER_AGENT}, timeout=60)
    response.raise_for_status()
    book = xlrd.open_workbook(file_contents=response.content)
    saved = 0
    for sheet in book.sheets():
        if not sheet.name.startswith("Data") or sheet.nrows < 4:
            continue
        header = sheet.row_values(2)
        for row_index in range(max(3, sheet.nrows - weeks), sheet.nrows):
            values = sheet.row_values(row_index)
            if not values[0]:
                continue
            week = xlrd.xldate_as_datetime(values[0], book.datemode).date()
            for column, name in enumerate(header[1:], 1):
                region = region_for(str(name))
                value = values[column] if column < len(values) else ""
                if not region or value in ("", None):
                    continue
                execute(
                    """insert into regional_diesel_prices (region, week, price) values (%s, %s, %s)
                       on conflict (region, week) do update set price = excluded.price, fetched_at = now()""",
                    (region, week, float(value)),
                )
                saved += 1
    return saved


def latest():
    found = rows(
        """select distinct on (region) region, week, price from regional_diesel_prices
           where week > current_date - make_interval(days => %s) order by region, week desc""",
        (FRESH_DAYS,),
    )
    return {row["region"]: row for row in found}


def price_for_state(state, table=None):
    table = latest() if table is None else table
    region = REGION_OF.get((state or "").upper())
    found = table.get(region) if region else None
    found = found or table.get("US")
    if not found:
        return None
    return {"region": found["region"], "name": NAMES.get(found["region"], found["region"]), "price": float(found["price"]),
            "week": found["week"], "age_days": (date.today() - found["week"]).days}


def history(region="US", weeks=12):
    return rows(
        "select week, price from regional_diesel_prices where region = %s order by week desc limit %s",
        (region, weeks),
    )[::-1]


def changes():
    table = rows(
        """select region, week, price, row_number() over (partition by region order by week desc) as n
           from regional_diesel_prices"""
    )
    by_region = {}
    for row in table:
        by_region.setdefault(row["region"], {})[row["n"]] = row
    out = []
    order = ["US", "1A", "1B", "1C", "2", "3", "4", "5", "CA"]
    for region in order:
        weeks = by_region.get(region)
        if not weeks or 1 not in weeks:
            continue
        now = float(weeks[1]["price"])
        def delta(n):
            return round(now - float(weeks[n]["price"]), 3) if n in weeks else None
        out.append({"region": region, "name": NAMES[region], "states": STATES.get(region, "").replace(" ", ", "),
                    "week": weeks[1]["week"], "price": now, "week_change": delta(2), "month_change": delta(5),
                    "year_change": delta(53)})
    return out


def snapshot_states(day=None):
    found = rows(
        """select s.state, r.retail_ppu, r.station_id from station_retail_prices r join fuel_stations s on s.id = r.station_id
           where r.fuel_type = 'diesel' and r.fetched_at > now() - interval '30 hours' and s.state is not null"""
    )
    by_state = {}
    for row in found:
        by_state.setdefault(row["state"].upper(), []).append(row)
    day = day or date.today()
    for state, items in by_state.items():
        prices = [float(i["retail_ppu"]) for i in items]
        cheapest = min(items, key=lambda i: float(i["retail_ppu"]))
        execute(
            """insert into state_diesel_daily (day, state, stations, avg_price, min_price, max_price, cheapest_station_id)
               values (%s, %s, %s, %s, %s, %s, %s)
               on conflict (day, state) do update set stations = excluded.stations, avg_price = excluded.avg_price,
                 min_price = excluded.min_price, max_price = excluded.max_price, cheapest_station_id = excluded.cheapest_station_id""",
            (day, state, len(prices), round(sum(prices) / len(prices), 3), min(prices), max(prices), cheapest["station_id"]),
        )
    return len(by_state)


def states_table():
    latest_day = one("select max(day) as day from state_diesel_daily")
    if not latest_day or not latest_day["day"]:
        return None, []
    day = latest_day["day"]
    found = rows(
        """select d.*, s.name as cheapest_name, s.city as cheapest_city,
                  (select avg_price from state_diesel_daily p where p.state = d.state and p.day = d.day - 1) as yesterday,
                  (select avg_price from state_diesel_daily p where p.state = d.state and p.day <= d.day - 7
                    order by p.day desc limit 1) as week_ago
           from state_diesel_daily d left join fuel_stations s on s.id = d.cheapest_station_id
           where d.day = %s order by d.avg_price""",
        (day,),
    )
    regions = latest()
    for row in found:
        regional = price_for_state(row["state"], regions)
        row["region_name"] = regional["name"] if regional else None
        row["region_price"] = regional["price"] if regional else None
        row["day_change"] = round(float(row["avg_price"]) - float(row["yesterday"]), 3) if row["yesterday"] else None
        row["week_change"] = round(float(row["avg_price"]) - float(row["week_ago"]), 3) if row["week_ago"] else None
    return day, found


def run():
    try:
        saved = fetch()
    except (requests.RequestException, xlrd.XLRDError) as err:
        log.warning("EIA fetch failed: %s", err)
        return {"saved": 0, "error": str(err)}
    newest = one("select max(week) as week from regional_diesel_prices")
    return {"saved": saved, "latest_week": str(newest["week"]) if newest else None}
