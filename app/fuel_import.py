import hashlib

from . import sheets
from .db import execute, one, rows

COLUMNS = {
    "date": (["tran date", "transaction date", "trans date", "date", "post date", "purchase date"], []),
    "time": (["tran time", "transaction time", "trans time", "time"], []),
    "card": (["card number", "card no", "card", "card num"], []),
    "unit": (["unit", "unit number", "unit no", "truck", "truck number", "vehicle", "unit id"], []),
    "driver": (["driver name", "driver", "driver id", "employee"], []),
    "odometer": (["odometer", "odo", "hubometer", "hub", "mileage"], []),
    "location": (["location name", "truck stop", "location", "merchant", "site name", "stop name"], []),
    "city": (["city", "location city"], []),
    "state": (["state", "st", "location state", "state prov"], []),
    "item": (["item", "product", "fuel type", "product description", "item description", "category", "description"], []),
    "qty": (["qty", "quantity", "gallons", "units", "volume", "gals"], []),
    "ppu": (["ppu", "unit price", "price per gallon", "price", "retail ppu"], ["disc"]),
    "amount": (["amt", "amount", "line amount", "total", "line total", "net amount", "total amount"], ["disc", "fee"]),
    "invoice": (["invoice", "invoice number", "invoice no", "tran", "tran number", "transaction number",
                 "transaction id", "trans id", "trans no", "auth code"], []),
}

FUEL_WORDS = [
    ("def", ["def", "diesel exhaust"]),
    ("reefer", ["rfr", "reefer", "rdsl"]),
    ("diesel", ["ulsd", "dsl", "diesel", "uls", "dies", "bio"]),
    ("gas", ["gas", "unl", "unleaded", "gasoline"]),
]


def pick_columns(headers):
    chosen = {}
    for key, (candidates, avoid) in COLUMNS.items():
        usable = [h for h in headers if not any(bad in h for bad in avoid)]
        found = None
        for wanted in candidates:
            if wanted in usable:
                found = wanted
                break
        if not found:
            for wanted in candidates:
                for header in usable:
                    if header.startswith(wanted + " ") or header == wanted or header.split()[:1] == [wanted]:
                        found = header
                        break
                if found:
                    break
        chosen[key] = found
    return chosen


def fuel_type(item):
    text = (item or "diesel").lower()
    for kind, words in FUEL_WORDS:
        if any(word in text for word in words):
            return kind
    return None


def last4(card):
    digits = "".join(ch for ch in str(card or "") if ch.isdigit())
    return digits[-4:] if len(digits) >= 4 else None


def reference(values):
    if values["invoice"]:
        parts = ["efs", str(values["invoice"]), values["item"] or "", f"{values['qty'] or 0:.3f}", f"{values['amount'] or 0:.2f}"]
        return ":".join(parts)
    raw = "|".join(str(values[k] or "") for k in ("when", "card", "item", "qty", "amount", "location"))
    return "efs:h:" + hashlib.sha256(raw.encode()).hexdigest()[:24]


def run(company_id, user_id, filename, data):
    headers, records = sheets.read(filename, data)
    columns = pick_columns(headers)
    missing = [name for name in ("date", "qty", "amount") if not columns[name]]
    if missing or not (columns["unit"] or columns["card"]):
        need = missing + ([] if (columns["unit"] or columns["card"]) else ["unit or card"])
        raise ValueError(
            "Could not find these columns: " + ", ".join(need) + ". Columns in the file: "
            + ", ".join(h for h in headers if h)[:400]
        )
    trucks = rows(
        "select id, unit_number, fuel_card_last4, odometer from trucks where company_id = %s and status <> 'sold'",
        (company_id,),
    )
    by_unit = {sheets.unit_key(t["unit_number"]): t for t in trucks}
    by_lead = {}
    for truck in trucks:
        lead = sheets.unit_lead(truck["unit_number"])
        if lead:
            by_lead.setdefault(lead, []).append(truck)
    by_card = {}
    for truck in trucks:
        if truck["fuel_card_last4"]:
            by_card.setdefault(truck["fuel_card_last4"], []).append(truck)
    drivers = {d["name"].lower(): d["id"] for d in rows("select id, name from drivers where company_id = %s", (company_id,))}

    report = {"total": 0, "added": 0, "duplicate": 0, "skipped": [], "unmatched": [], "columns": columns}
    for record in records:
        get = lambda key: sheets.value(record, columns[key])
        when = sheets.when(get("date"), get("time"))
        qty = sheets.number(get("qty"))
        amount = sheets.number(get("amount"))
        if when is None and qty is None and amount is None:
            continue
        report["total"] += 1
        item = get("item")
        values = {
            "when": when, "card": get("card"), "unit": get("unit"), "item": str(item) if item is not None else None,
            "qty": qty, "amount": amount, "location": get("location"), "invoice": get("invoice"),
        }
        kind = fuel_type(values["item"])
        if kind is None:
            report["skipped"].append({**values, "why": "not fuel (" + str(values["item"]) + ")"})
            continue
        if when is None or not qty or amount is None:
            report["skipped"].append({**values, "why": "missing date, gallons or amount"})
            continue
        truck = by_unit.get(sheets.unit_key(values["unit"])) if values["unit"] else None
        if not truck and values["unit"]:
            lead = sheets.unit_lead(values["unit"])
            candidates = by_lead.get(lead, []) if lead else []
            truck = by_unit.get(lead) if lead else None
            if not truck and len(candidates) == 1:
                truck = candidates[0]
        if not truck:
            candidates = by_card.get(last4(values["card"]) or "", [])
            truck = candidates[0] if len(candidates) == 1 else None
        if not truck:
            report["unmatched"].append({**values, "why": "no truck with this unit or card"})
            continue
        odometer = sheets.number(get("odometer"))
        odometer = int(odometer) if odometer and odometer > 0 else None
        ppu = sheets.number(get("ppu")) or (round(amount / qty, 4) if qty else None)
        driver_name = get("driver")
        place = ", ".join(str(part) for part in [values["location"], get("city")] if part)
        added = one(
            """insert into fuel_transactions (company_id, truck_id, driver_id, purchased_at, gallons, price_per_gallon,
                 total, odometer, location, state, fuel_type, card_last4, invoice_no, source, raw, external_ref, created_by)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'import', %s, %s, %s)
               on conflict (company_id, external_ref) where external_ref is not null do nothing
               returning id""",
            (
                company_id, truck["id"], drivers.get(str(driver_name).lower()) if driver_name else None, when,
                round(qty, 3), ppu, round(amount, 2), odometer, place[:160] or None,
                (str(get("state"))[:4] if get("state") else None), kind, last4(values["card"]),
                (str(values["invoice"])[:40] if values["invoice"] else None),
                sheets_json(record), reference(values), user_id,
            ),
        )
        if not added:
            report["duplicate"] += 1
            continue
        report["added"] += 1
        if odometer and kind == "diesel":
            execute(
                "insert into odometer_readings (company_id, truck_id, miles, read_at, source, created_by) values (%s, %s, %s, %s, 'fuel', %s)",
                (company_id, truck["id"], odometer, when, user_id),
            )
    execute(
        """insert into fuel_imports (company_id, filename, rows_total, rows_added, rows_duplicate, rows_unmatched, created_by)
           values (%s, %s, %s, %s, %s, %s, %s)""",
        (company_id, filename, report["total"], report["added"], report["duplicate"], len(report["unmatched"]), user_id),
    )
    return report


def sheets_json(record):
    import json
    return json.dumps({k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in record.items() if k}, default=str)
