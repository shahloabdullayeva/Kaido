import json
import re
from datetime import datetime, timezone

from .db import execute, insert, one, rows
from .samsara import SamsaraClient, SamsaraError, meters_to_miles, parse_fault_codes
from .security import decrypt, encrypt

STAT_TYPES = ["obdOdometerMeters", "gpsOdometerMeters", "faultCodes", "engineStates", "gps", "fuelPercents"]

UNIT_PATTERN = re.compile(r"#\s*(\d+[A-Za-z]?)")
NAME_PREFIXES = re.compile(r"^\s*(bmg|llap|unit|truck)\b[\s.:#-]*", re.I)
PAREN_PATTERN = re.compile(r"\([^)]*\)")
SERIAL_PATTERN = re.compile(r"^[A-Z0-9]{3,}(-[A-Z0-9]{2,}){1,}$")
HONORIFICS = {"aka", "\u0430\u043a\u0430", "opa", "jr", "sr"}
NOT_NAMES = {
    "inactive", "spare", "shop", "sold", "available", "unassigned", "rental",
    "rented", "empty", "none", "new", "old", "trailer", "truck", "unit", "test",
    "oo", "o", "cd", "c", "d", "team", "solo", "driver",
}


def _name_words(part):
    part = re.sub(r"[^A-Za-z\u0400-\u04ff' .-]", " ", part)
    part = re.sub(r"\s+", " ", part).strip(" .-'")
    words = []
    for word in part.split():
        bare = word.strip(".-'").lower()
        if not bare or bare in HONORIFICS or bare in NOT_NAMES:
            continue
        if len(bare) < 2 and not words:
            continue
        words.append(word.strip(".-'"))
    return words


def driver_names(vehicle_name):
    if not vehicle_name:
        return []
    text = PAREN_PATTERN.sub(" ", vehicle_name)
    text = UNIT_PATTERN.sub(" ", text)
    for _ in range(3):
        stripped = NAME_PREFIXES.sub("", text)
        if stripped == text:
            break
        text = stripped
    if SERIAL_PATTERN.match(text.strip().upper()):
        return []
    text = re.sub(r"\bO\s*/\s*O\b", " ", text, flags=re.I)
    text = re.sub(r"[&/]| and ", "|", text)
    found = []
    for part in text.split("|"):
        words = _name_words(part)
        if not words:
            continue
        if len(words) == 1 and len(words[0]) < 3:
            continue
        pretty = " ".join(w if (w[:1].isupper() and not w.isupper()) else w.title() for w in words)
        if pretty.lower() in NOT_NAMES:
            continue
        found.append(pretty)
    return found


def import_drivers(company_id):
    links = rows(
        """select v.external_name, v.truck_id, t.driver_id
           from vehicle_links v join trucks t on t.id = v.truck_id
           where v.company_id = %s and v.truck_id is not null""",
        (company_id,),
    )
    created = 0
    assigned = 0
    for link in links:
        names = driver_names(link["external_name"])
        if not names:
            continue
        primary = None
        for name in names:
            existing = one(
                "select id from drivers where company_id = %s and lower(name) = lower(%s)",
                (company_id, name),
            )
            if existing:
                driver_id = existing["id"]
            else:
                driver = insert(
                    """insert into drivers (company_id, name, status, notes)
                       values (%s, %s, 'active', %s) returning id""",
                    (company_id, name, f"Imported from the Samsara vehicle name: {link['external_name']}"),
                )
                driver_id = driver["id"]
                created += 1
            if primary is None:
                primary = driver_id
        if primary and not link["driver_id"]:
            execute("update trucks set driver_id = %s, updated_at = now() where id = %s", (primary, link["truck_id"]))
            assigned += 1
    return {"created": created, "assigned": assigned}


def unit_from_name(name):
    if not name:
        return None
    match = UNIT_PATTERN.search(name)
    if match:
        return match.group(1).upper()
    bare = name.strip()
    return bare[:40] if bare else None


def get_integration(company_id):
    return one("select * from integrations where company_id = %s and provider = 'samsara'", (company_id,))


def client_for(company_id):
    integration = get_integration(company_id)
    if not integration or not integration["credential"]:
        raise SamsaraError("Samsara is not connected for this company.")
    return SamsaraClient(decrypt(integration["credential"])), integration


def connect(company_id, token, user_id):
    client = SamsaraClient(token)
    try:
        identity = client.whoami()
    except SamsaraError:
        identity = {}
        client.get("/fleet/vehicles", {"limit": 1})
    insert(
        """insert into integrations (company_id, provider, credential, status, created_by, updated_at)
           values (%s, 'samsara', %s, 'connected', %s, now())
           on conflict (company_id, provider) do update
             set credential = excluded.credential, status = 'connected', last_error = null, updated_at = now()
           returning id""",
        (company_id, encrypt(token), user_id),
    )
    return identity


def disconnect(company_id):
    execute(
        """update integrations set credential = null, status = 'disconnected', sync_cursor = null, updated_at = now()
           where company_id = %s and provider = 'samsara'""",
        (company_id,),
    )


def link_vehicles(company_id, client):
    vehicles = client.vehicles()
    seen = 0
    for vehicle in vehicles:
        external_id = str(vehicle.get("id") or "")
        if not external_id:
            continue
        seen += 1
        vin = (vehicle.get("vin") or "").strip() or None
        name = (vehicle.get("name") or "").strip() or None
        existing = one(
            "select * from vehicle_links where company_id = %s and provider = 'samsara' and external_id = %s",
            (company_id, external_id),
        )
        truck_id = existing["truck_id"] if existing else None
        if truck_id is None:
            match = None
            if vin:
                match = one(
                    "select id from trucks where company_id = %s and upper(vin) = upper(%s) limit 1",
                    (company_id, vin),
                )
            if not match and name:
                unit = unit_from_name(name)
                if unit:
                    match = one(
                        "select id from trucks where company_id = %s and lower(unit_number) = lower(%s) limit 1",
                        (company_id, unit),
                    )
                if not match:
                    match = one(
                        "select id from trucks where company_id = %s and lower(unit_number) = lower(%s) limit 1",
                        (company_id, name),
                    )
            truck_id = match["id"] if match else None
        insert(
            """insert into vehicle_links (company_id, truck_id, provider, external_id, external_name, external_vin, last_seen_at)
               values (%s, %s, 'samsara', %s, %s, %s, now())
               on conflict (company_id, provider, external_id) do update
                 set external_name = excluded.external_name, external_vin = excluded.external_vin,
                     last_seen_at = now(),
                     truck_id = coalesce(vehicle_links.truck_id, excluded.truck_id)
               returning id""",
            (company_id, truck_id, external_id, name, vin),
        )
    return seen


def import_vehicles(company_id, user_id):
    client, _integration = client_for(company_id)
    link_vehicles(company_id, client)
    pending = rows(
        """select * from vehicle_links where company_id = %s and provider = 'samsara' and truck_id is null""",
        (company_id,),
    )
    vehicles = {str(v.get("id")): v for v in client.vehicles()}
    created = 0
    skipped = 0
    for link in pending:
        vehicle = vehicles.get(link["external_id"], {})
        unit = unit_from_name(link["external_name"]) or link["external_id"]
        clash = one(
            "select id from trucks where company_id = %s and lower(unit_number) = lower(%s)",
            (company_id, unit),
        )
        if clash:
            execute("update vehicle_links set truck_id = %s where id = %s", (clash["id"], link["id"]))
            skipped += 1
            continue
        year = vehicle.get("year")
        try:
            year = int(year) if year else None
        except (TypeError, ValueError):
            year = None
        truck = insert(
            """insert into trucks (company_id, unit_number, vin, make, model, year, status, notes)
               values (%s, %s, %s, %s, %s, %s, 'active', %s) returning id""",
            (
                company_id, unit, (vehicle.get("vin") or link["external_vin"] or None),
                (vehicle.get("make") or "").title() or None,
                (vehicle.get("model") or "").title() or None,
                year, f"Imported from Samsara as {link['external_name']}",
            ),
        )
        execute("update vehicle_links set truck_id = %s where id = %s", (truck["id"], link["id"]))
        created += 1
    return {"created": created, "matched": skipped}


def record_odometer(company_id, truck, miles, read_at):
    if miles is None or miles <= 0:
        return 0
    latest = one(
        "select miles from odometer_readings where truck_id = %s order by read_at desc limit 1",
        (truck["id"],),
    )
    if latest and latest["miles"] == miles:
        return 0
    execute(
        "insert into odometer_readings (company_id, truck_id, miles, read_at, source) values (%s, %s, %s, coalesce(%s, now()), 'telematics')",
        (company_id, truck["id"], miles, read_at),
    )
    if miles >= (truck["odometer"] or 0):
        execute("update trucks set odometer = %s, odometer_at = coalesce(%s, now()), updated_at = now() where id = %s",
                (miles, read_at, truck["id"]))
    return 1


def record_position(truck, gps):
    if not isinstance(gps, dict):
        return 0
    latitude = gps.get("latitude")
    longitude = gps.get("longitude")
    if latitude is None or longitude is None:
        return 0
    reverse = gps.get("reverseGeo") or {}
    execute(
        """update trucks set latitude = %s, longitude = %s, location = %s,
             located_at = coalesce(%s, now()), updated_at = now() where id = %s""",
        (latitude, longitude, reverse.get("formattedLocation"), gps.get("time"), truck["id"]),
    )
    return 1


def sync_faults(company_id, truck, faults):
    opened = 0
    current_keys = {fault["code_key"] for fault in faults}
    open_events = rows(
        "select * from fault_events where truck_id = %s and cleared_at is null and source = 'samsara'",
        (truck["id"],),
    )
    open_by_key = {event["code_key"]: event for event in open_events}
    for fault in faults:
        existing = open_by_key.get(fault["code_key"])
        if existing:
            execute(
                """update fault_events set last_seen_at = now(), occurrence_count = coalesce(%s, occurrence_count),
                     severity = %s, lamp = %s, description = coalesce(%s, description), raw = %s
                   where id = %s""",
                (fault["occurrence_count"], fault["severity"], fault["lamp"], fault["description"],
                 json.dumps(fault["raw"]), existing["id"]),
            )
            continue
        insert(
            """insert into fault_events (company_id, truck_id, source, protocol, code_key, spn, fmi, dtc_code,
                 description, lamp, severity, occurrence_count, raw)
               values (%s, %s, 'samsara', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id""",
            (
                company_id, truck["id"], fault["protocol"], fault["code_key"], fault["spn"], fault["fmi"],
                fault["dtc_code"], fault["description"], fault["lamp"], fault["severity"],
                fault["occurrence_count"], json.dumps(fault["raw"]),
            ),
        )
        opened += 1
    cleared = 0
    for key, event in open_by_key.items():
        if key not in current_keys:
            execute("update fault_events set cleared_at = now() where id = %s", (event["id"],))
            cleared += 1
    return opened, cleared


def sync_defects(company_id, client):
    try:
        defects = client.defects()
    except SamsaraError:
        return None
    seen = 0
    for defect in defects:
        external_id = str(defect.get("id") or "")
        if not external_id:
            continue
        vehicle = defect.get("vehicle") or defect.get("asset") or {}
        link = one(
            "select truck_id from vehicle_links where company_id = %s and external_id = %s",
            (company_id, str(vehicle.get("id") or "")),
        )
        insert(
            """insert into dvir_defects (company_id, truck_id, external_id, defect_type, comment, reported_by,
                 is_resolved, reported_at, resolved_at, raw)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               on conflict (company_id, external_id) do update
                 set is_resolved = excluded.is_resolved, resolved_at = excluded.resolved_at,
                     comment = excluded.comment, raw = excluded.raw
               returning id""",
            (
                company_id, link["truck_id"] if link else None, external_id,
                (defect.get("defectType") or defect.get("type")),
                defect.get("comment"),
                ((defect.get("reportedBy") or {}).get("name") if isinstance(defect.get("reportedBy"), dict) else None),
                bool(defect.get("isResolved")),
                defect.get("createdAtTime") or defect.get("reportedAtTime"),
                defect.get("resolvedAtTime"),
                json.dumps(defect),
            ),
        )
        seen += 1
    return seen


def sync_company(company_id):
    run = insert(
        "insert into sync_runs (company_id, provider) values (%s, 'samsara') returning *",
        (company_id,),
    )
    counters = {"vehicles": 0, "odometer": 0, "positions": 0, "faults_opened": 0, "faults_cleared": 0, "defects": 0, "unlinked": 0}
    try:
        client, _integration = client_for(company_id)
        counters["vehicles"] = link_vehicles(company_id, client)
        stats = client.vehicle_stats(STAT_TYPES)
        for stat in stats:
            external_id = str(stat.get("id") or "")
            link = one(
                """select v.truck_id, t.* from vehicle_links v
                   left join trucks t on t.id = v.truck_id
                   where v.company_id = %s and v.external_id = %s""",
                (company_id, external_id),
            )
            if not link or not link["truck_id"]:
                counters["unlinked"] += 1
                continue
            truck = {"id": link["truck_id"], "odometer": link["odometer"]}
            odometer_block = stat.get("obdOdometerMeters") or stat.get("gpsOdometerMeters") or {}
            miles = meters_to_miles(odometer_block.get("value"))
            counters["odometer"] += record_odometer(company_id, truck, miles, odometer_block.get("time"))
            counters["positions"] += record_position(truck, stat.get("gps"))
            faults = parse_fault_codes(stat.get("faultCodes"))
            opened, cleared = sync_faults(company_id, truck, faults)
            counters["faults_opened"] += opened
            counters["faults_cleared"] += cleared
        defects = sync_defects(company_id, client)
        counters["defects"] = defects if defects is not None else 0
        counters["dvir_available"] = defects is not None
        execute(
            """update integrations set status = 'connected', last_sync_at = now(), last_error = null, updated_at = now()
               where company_id = %s and provider = 'samsara'""",
            (company_id,),
        )
        execute(
            """update sync_runs set finished_at = now(), status = 'ok', vehicles_seen = %s, odometer_rows = %s,
                 faults_opened = %s, faults_cleared = %s, defects_seen = %s
               where id = %s""",
            (counters["vehicles"], counters["odometer"], counters["faults_opened"],
             counters["faults_cleared"], counters["defects"], run["id"]),
        )
        counters["status"] = "ok"
        return counters
    except Exception as err:
        message = str(err)[:500]
        execute(
            """update integrations set status = 'error', last_error = %s, updated_at = now()
               where company_id = %s and provider = 'samsara'""",
            (message, company_id),
        )
        execute("update sync_runs set finished_at = now(), status = 'error', error = %s where id = %s",
                (message, run["id"]))
        counters["status"] = "error"
        counters["error"] = message
        return counters


def sync_all():
    results = {}
    targets = rows(
        """select c.id, c.name from companies c
           join integrations i on i.company_id = c.id and i.provider = 'samsara'
           where c.status = 'active' and i.credential is not null""",
    )
    for company in targets:
        results[company["name"]] = sync_company(company["id"])
    return results
