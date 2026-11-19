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


def fetch(weeks=8):
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


def run():
    try:
        saved = fetch()
    except (requests.RequestException, xlrd.XLRDError) as err:
        log.warning("EIA fetch failed: %s", err)
        return {"saved": 0, "error": str(err)}
    newest = one("select max(week) as week from regional_diesel_prices")
    return {"saved": saved, "latest_week": str(newest["week"]) if newest else None}
