from datetime import datetime
from html import escape

import requests

from .db import execute, insert, one, rows
from .logs import get
from .vehicles import decode_vin

log = get("recalls")
RECALLS_URL = "https://api.nhtsa.gov/recalls/recallsByVehicle"
VIN_LOOKUP = "https://www.nhtsa.gov/recalls?vin={vin}"


def lookup_url(vin):
    return VIN_LOOKUP.format(vin=vin or "")


def _query(make, model, year):
    response = requests.get(RECALLS_URL, params={"make": make, "model": model, "modelYear": year}, timeout=20)
    if response.status_code == 400:
        return []
    response.raise_for_status()
    return response.json().get("results") or []


def campaigns_for(make, model, year):
    make, model = (make or "").strip().upper(), (model or "").strip().upper()
    found = _query(make, model, year)
    if not found and " " in make:
        found = _query(make.split()[0], model, year)
    return found


def _date(text):
    try:
        return datetime.strptime(text, "%m/%d/%Y").date()
    except (TypeError, ValueError):
        return None


def save_campaign(item):
    existing = one("select campaign from recall_campaigns where campaign = %s", (item["NHTSACampaignNumber"],))
    execute(
        """insert into recall_campaigns (campaign, manufacturer, make, model, model_year, component, summary, consequence,
             remedy, notes, report_date, park_it, fetched_at)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
           on conflict (campaign) do update set component = excluded.component, summary = excluded.summary,
             consequence = excluded.consequence, remedy = excluded.remedy, notes = excluded.notes,
             park_it = excluded.park_it, fetched_at = now()""",
        (item["NHTSACampaignNumber"], item.get("Manufacturer"), item.get("Make"), item.get("Model"),
         int(item["ModelYear"]) if str(item.get("ModelYear") or "").isdigit() else None, item.get("Component"),
         item.get("Summary"), item.get("Consequence"), item.get("Remedy"), item.get("Notes"),
         _date(item.get("ReportReceivedDate")), str(item.get("parkIt")).lower() == "true"),
    )
    return existing is None


def fill_vehicle(table, vehicle):
    if vehicle.get("make") and vehicle.get("year") and (table == "trailers" or vehicle.get("model")):
        return vehicle
    if not vehicle.get("vin") or len(vehicle["vin"]) != 17:
        return vehicle
    try:
        found = decode_vin(vehicle["vin"])
    except Exception as err:
        log.warning("VIN decode failed for %s: %s", vehicle["vin"], err)
        return vehicle
    if table == "trucks":
        execute("""update trucks set make = coalesce(make, %s), model = coalesce(model, %s), year = coalesce(year, %s)
                   where id = %s""", (found["make"], found["model"], found["year"], vehicle["id"]))
        vehicle = dict(vehicle, make=vehicle.get("make") or found["make"], model=vehicle.get("model") or found["model"],
                       year=vehicle.get("year") or found["year"])
    else:
        execute("update trailers set make = coalesce(make, %s), year = coalesce(year, %s) where id = %s",
                (found["make"], found["year"], vehicle["id"]))
        vehicle = dict(vehicle, make=vehicle.get("make") or found["make"], year=vehicle.get("year") or found["year"],
                       model=found["model"])
    return vehicle


def run(notify=True):
    baseline = not one("select 1 from recall_checks limit 1")
    cache, new_campaigns, linked, vehicles = {}, [], 0, 0
    targets = [("trucks", row) for row in rows(
        "select t.* from trucks t join companies c on c.id = t.company_id where c.status = 'active' and t.status <> 'sold' and t.vin is not null")]
    targets += [("trailers", dict(row, model=None)) for row in rows(
        "select r.* from trailers r join companies c on c.id = r.company_id where c.status = 'active' and r.status <> 'sold' and r.vin is not null")]
    for table, vehicle in targets:
        vehicle = fill_vehicle(table, vehicle)
        if not (vehicle.get("make") and vehicle.get("model") and vehicle.get("year")):
            continue
        vehicles += 1
        key = (vehicle["make"].upper(), vehicle["model"].upper(), vehicle["year"])
        if key not in cache:
            try:
                cache[key] = campaigns_for(*key)
            except (requests.RequestException, ValueError) as err:
                log.warning("recall lookup %s failed: %s", key, err)
                cache[key] = None
                continue
            for item in cache[key]:
                if save_campaign(item) and not baseline:
                    new_campaigns.append(item["NHTSACampaignNumber"])
        for item in cache[key] or []:
            column = "truck_id" if table == "trucks" else "trailer_id"
            added = insert(
                f"""insert into vehicle_recalls (company_id, {column}, campaign) values (%s, %s, %s)
                    on conflict do nothing returning id""",
                (vehicle["company_id"], vehicle["id"], item["NHTSACampaignNumber"]),
            )
            linked += 1 if added else 0
    insert("insert into recall_checks (vehicles, lookups, new_campaigns, linked) values (%s, %s, %s, %s) returning id",
           (vehicles, len(cache), len(new_campaigns), linked))
    if notify and new_campaigns:
        tell(new_campaigns)
    return {"vehicles": vehicles, "lookups": len(cache), "new_campaigns": len(new_campaigns), "linked": linked,
            "baseline": baseline}


def tell(campaigns):
    from .alert_group import office
    for company in rows("select distinct company_id from vehicle_recalls where campaign = any(%s)", (campaigns,)):
        lines = ["New safety recall (may apply, confirm with the dealer)"]
        for row in rows(
            """select v.campaign, c.component, coalesce(t.unit_number, r.unit_number) as unit from vehicle_recalls v
               join recall_campaigns c on c.campaign = v.campaign left join trucks t on t.id = v.truck_id
               left join trailers r on r.id = v.trailer_id
               where v.company_id = %s and v.campaign = any(%s) order by v.campaign, unit""",
            (company["company_id"], campaigns),
        ):
            lines.append(f"{escape(row['unit'])}: {row['campaign']} {escape((row['component'] or '').split(':')[0].title())}")
        office(company["company_id"], "Recalls", "\n".join(lines[:40]))


def for_vehicle(column, vehicle_id):
    return rows(
        f"""select v.*, c.component, c.summary, c.consequence, c.remedy, c.report_date, c.park_it, c.make, c.model, c.model_year,
                   m.status as order_status
            from vehicle_recalls v join recall_campaigns c on c.campaign = v.campaign
            left join maintenance_orders m on m.id = v.work_order_id
            where v.{column} = %s order by (v.status = 'open') desc, c.report_date desc nulls last""",
        (vehicle_id,),
    )
