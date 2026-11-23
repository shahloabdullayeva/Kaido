import re
from datetime import datetime, timedelta, timezone
from html import escape

from . import config
from .db import execute, insert, one, rows
from .fuel import unit_label
from .logs import get
from .reminders import company_chats
from .telegram import send

log = get("health")

FRESH_MINUTES = 45
RUNNING_RPM = 400
BATTERY_LOW_MV = 12200
BATTERY_OK_MV = 12450
CHARGING_LOW_MV = 12800
CHARGING_OK_MV = 13200
COOLANT_HOT_C = 104
COOLANT_OK_C = 99
OIL_LOW_IDLE_KPA = 69
OIL_LOW_KPA = 140
OIL_IDLE_RPM = 1000
OIL_MARGIN_KPA = 30
OIL_SAME_MINUTES = 3
DEF_LOW = 15
DEF_EMPTY = 5
DEF_OK = 30
TIRE_LOW_KPA = 586
TIRE_FLAT_KPA = 414
TIRE_OK_KPA = 620
TIRE_FRESH_MINUTES = 120
IDLE_MINUTES = 60
SILENT_HOURS = 6
SILENT_MAX_HOURS = 48
REOPEN_HOURS = 6
FAULT_NEW_DAYS = 30
OFFICE_ONLY = {"idling", "not_reporting", "service_soon", "service_over", "mpg_drop"}
REOPEN = {"mpg_drop": 24 * 7, "service_soon": 24 * 30, "service_over": 24 * 30}
HOUR_MS = 3_600_000
HOS_FRESH_MINUTES = 40
HOS_WORKING = ("DS_D", "DS_ON")
MPG_RECENT_DAYS = 7
MPG_BASE_DAYS = 28
MPG_RECENT_MILES = 800
MPG_BASE_MILES = 2000
MPG_DROP = 0.12
MPG_OK = 0.06
ML_PER_GALLON = 3785.41
M_PER_MILE = 1609.344

TITLES = {
    "battery_low": "Battery low",
    "not_charging": "Battery not charging",
    "coolant_hot": "Engine running hot",
    "oil_low": "Low oil pressure",
    "def_low": "DEF low",
    "idling": "Idling",
    "not_reporting": "Not reporting",
    "check_engine": "Check engine",
    "tire_low": "Tire pressure low",
    "hos_drive": "Driving hours almost out",
    "hos_shift": "14-hour shift almost out",
    "hos_break": "30-minute break due",
    "hos_cycle": "70-hour cycle almost out",
    "hos_violation": "Hours violation",
    "service_soon": "Service due soon",
    "service_over": "Service overdue",
    "mpg_drop": "MPG dropped",
}


def base_kind(kind):
    return kind.split(":", 1)[0]


def title_of(kind):
    return TITLES.get(base_kind(kind), kind)


def now():
    return datetime.now(timezone.utc)


def parse_time(text):
    if not text:
        return None
    return datetime.fromisoformat(re.sub(r"\.\d+", "", text.replace("Z", "+00:00")))


def reading(health, key, minutes=FRESH_MINUTES):
    block = (health or {}).get(key)
    if not isinstance(block, dict) or block.get("value") is None:
        return None, None
    at = parse_time(block.get("time"))
    if not at or now() - at > timedelta(minutes=minutes):
        return None, at
    return block["value"], at


def fahrenheit(celsius):
    return round(celsius * 9 / 5 + 32)


def psi(kpa):
    return round(kpa * 0.145)


def tire_name(key):
    words = re.sub(r"(?<!^)(?=[A-Z])", " ", re.sub(r"(?i)tire|pressure|kpa", "", key)).strip().lower()
    return words or "tire"


def duration(minutes):
    hours, mins = divmod(int(minutes), 60)
    return f"{hours} h {mins} min" if hours else f"{mins} min"


def checks(truck):
    health = truck["health"] or {}
    found = {}
    clear = set()
    rpm, rpm_at = reading(health, "engineRpm", 20)
    state = (health.get("engineState") or {}).get("value")
    state_at = parse_time((health.get("engineState") or {}).get("time"))
    running = rpm is not None and rpm > RUNNING_RPM
    parked_off = state == "Off" and not running

    volts, _ = reading(health, "batteryMilliVolts", 60)
    if volts is not None:
        if parked_off and volts < BATTERY_LOW_MV:
            found["battery_low"] = (volts / 1000, f"{volts / 1000:.1f} V with the engine off. It may not start.")
        elif volts >= BATTERY_OK_MV or running:
            clear.add("battery_low")
        if running and volts < CHARGING_LOW_MV:
            found["not_charging"] = (volts / 1000, f"{volts / 1000:.1f} V with the engine running. Check the alternator and belt.")
        elif volts >= CHARGING_OK_MV or parked_off:
            clear.add("not_charging")

    coolant, _ = reading(health, "engineCoolantTemperatureMilliC")
    if coolant is not None:
        celsius = coolant / 1000
        if running and celsius >= COOLANT_HOT_C:
            found["coolant_hot"] = (fahrenheit(celsius), f"Coolant {fahrenheit(celsius)}°F. Watch the gauge and stop if it keeps rising.")
        elif celsius < COOLANT_OK_C or not running:
            clear.add("coolant_hot")

    oil, oil_at = reading(health, "engineOilPressureKPa")
    if oil is not None and running and rpm_at and oil_at and abs((oil_at - rpm_at).total_seconds()) <= OIL_SAME_MINUTES * 60:
        floor = OIL_LOW_IDLE_KPA if rpm < OIL_IDLE_RPM else OIL_LOW_KPA
        if oil < floor:
            found["oil_low"] = (psi(oil), f"{psi(oil)} psi at {int(rpm)} rpm. Stop safely and check the oil.")
        elif oil >= floor + OIL_MARGIN_KPA:
            clear.add("oil_low")
    elif not running:
        clear.add("oil_low")

    level, _ = reading(health, "defLevelMilliPercent", 24 * 60)
    if level is not None:
        pct = level / 1000
        if pct < DEF_LOW:
            tail = "The truck will slow down soon. Fill DEF now." if pct < DEF_EMPTY else "Fill DEF at the next stop."
            found["def_low"] = (round(pct), f"{pct:.0f}% left. {tail}")
        elif pct >= DEF_OK:
            clear.add("def_low")

    tires = health.get("tirePressure")
    tire_at = parse_time(tires.get("time")) if isinstance(tires, dict) else None
    if tire_at and now() - tire_at <= timedelta(minutes=TIRE_FRESH_MINUTES):
        readings = {key: value for key, value in tires.items()
                    if "pressure" in key.lower() and isinstance(value, (int, float)) and value > 0}
        low = {key: value for key, value in readings.items() if value < TIRE_LOW_KPA}
        if low:
            worst = min(low.values())
            names = ", ".join(f"{tire_name(key)} {psi(value)} psi" for key, value in sorted(low.items(), key=lambda kv: kv[1]))
            tail = "Stop and check it before driving on." if worst < TIRE_FLAT_KPA else "Check and air up at the next stop."
            found["tire_low"] = (psi(worst), f"{names}. {tail}")
        elif readings and min(readings.values()) >= TIRE_OK_KPA:
            clear.add("tire_low")

    live = truck["located_at"] and now() - truck["located_at"] < timedelta(minutes=FRESH_MINUTES)
    if state == "Idle" and state_at and live:
        minutes = (now() - state_at).total_seconds() / 60
        if minutes >= IDLE_MINUTES:
            found["idling"] = (round(minutes), f"Idling for {duration(minutes)}.")
    elif state:
        clear.add("idling")

    located = truck["located_at"]
    if located:
        silent = (now() - located).total_seconds() / 3600
        if SILENT_HOURS <= silent <= SILENT_MAX_HOURS:
            found["not_reporting"] = (round(silent), f"No signal from the ELD for {round(silent)} h. Check it is plugged in.")
        elif silent < SILENT_HOURS:
            clear.add("not_reporting")
    return found, clear


def message(truck, kind, detail, office):
    lines = [f"<b>{title_of(kind)}</b> · Unit {escape(unit_label(truck['unit_number']))}", escape(detail)]
    if truck.get("location"):
        lines.append(f"Near {escape(truck['location'])}")
    if office:
        if truck.get("company_name"):
            lines[0] += f" · {escape(truck['company_name'])}"
        lines.append(f"{config.APP_URL}/trucks/{truck['id']}")
    return "\n".join(lines)


def deliver(truck, kind, detail, office_too=True):
    sent = False
    if truck.get("telegram_chat_id") and base_kind(kind) not in OFFICE_ONLY:
        sent = bool(send(truck["telegram_chat_id"], message(truck, kind, detail, False)).get("ok")) or sent
    if office_too:
        from .alert_group import health_topic, office
        for result in office(truck["company_id"], health_topic(kind), message(truck, kind, detail, True)):
            sent = bool(result.get("ok")) or sent
    return sent


def open_alert(truck, kind, value, detail, dry=False):
    if one("select 1 from health_alerts where truck_id = %s and kind = %s and fault_id is null and cleared_at is null",
           (truck["id"], kind)):
        return False
    if one("""select 1 from health_alerts where truck_id = %s and kind = %s and fault_id is null
              and cleared_at > now() - make_interval(hours => %s)""",
           (truck["id"], kind, REOPEN.get(base_kind(kind), REOPEN_HOURS))):
        return False
    if dry:
        return True
    alert = insert(
        """insert into health_alerts (company_id, truck_id, kind, value, detail) values (%s, %s, %s, %s, %s)
           on conflict do nothing returning id""",
        (truck["company_id"], truck["id"], kind, value, detail),
    )
    if alert and deliver(truck, kind, detail):
        execute("update health_alerts set sent_at = now() where id = %s", (alert["id"],))
    return bool(alert)


TRUCKS = """select t.*, c.name as company_name from trucks t join companies c on c.id = t.company_id
            where c.status = 'active' and t.status = 'active'
              and (t.health_at > now() - interval '1 hour' or t.located_at > now() - interval '48 hours')"""


def fault_alerts(dry=False):
    fresh = rows(
        """select f.* from fault_events f
           left join health_alerts a on a.fault_id = f.id
           where a.id is null and f.cleared_at is null and f.severity in ('medium', 'high')
             and (f.lamp like '%%warning%%' or f.lamp like '%%stop%%')
             and f.first_seen_at > now() - interval '2 hours'
             and not exists (select 1 from fault_events p where p.truck_id = f.truck_id and p.code_key = f.code_key
                             and p.id <> f.id and p.first_seen_at < f.first_seen_at
                             and p.last_seen_at > f.first_seen_at - make_interval(days => %s))
           order by f.first_seen_at""",
        (FAULT_NEW_DAYS,),
    )
    sent = []
    for fault in fresh:
        truck = one("select t.*, c.name as company_name from trucks t join companies c on c.id = t.company_id where t.id = %s",
                    (fault["truck_id"],))
        code = fault["dtc_code"] or f"SPN {fault['spn']} / FMI {fault['fmi']}"
        detail = code + (f" · {fault['description']}" if fault["description"] else "")
        sent.append((truck["unit_number"], "check_engine", detail))
        if dry:
            continue
        alert = insert(
            """insert into health_alerts (company_id, truck_id, kind, detail, fault_id) values (%s, %s, 'check_engine', %s, %s)
               on conflict do nothing returning id""",
            (fault["company_id"], fault["truck_id"], detail, fault["id"]),
        )
        if alert and deliver(truck, "check_engine", detail, office_too=fault["severity"] != "high"):
            execute("update health_alerts set sent_at = now() where id = %s", (alert["id"],))
    execute("""update health_alerts a set cleared_at = f.cleared_at from fault_events f
               where a.fault_id = f.id and a.cleared_at is null and f.cleared_at is not null""")
    return sent


def apply(truck, found, clear, dry, sent):
    for kind in clear - set(found):
        if not dry:
            execute("""update health_alerts set cleared_at = now() where truck_id = %s and kind = %s
                       and fault_id is null and cleared_at is null""", (truck["id"], kind))
    for kind, (value, detail) in found.items():
        if open_alert(truck, kind, value, detail, dry):
            sent.append((truck["unit_number"], kind, detail))


def clock(ms):
    minutes = max(int(float(ms)) // 60_000, 0)
    return f"{minutes // 60}:{minutes % 60:02d}"


def hos_checks(row):
    found, clear = {}, set()
    working = row["duty_status"] in HOS_WORKING
    driving = row["duty_status"] == "DS_D"
    drive, shift, brk, cycle = (None if row[k] is None else float(row[k]) for k in
                                ("drive_remaining", "shift_remaining", "break_remaining", "cycle_remaining"))
    if driving and any(v is not None and v <= 0 for v in (drive, shift, brk)):
        found["hos_violation"] = (0, "Driving with no hours left. Stop and log off duty.")
    elif not driving:
        clear.add("hos_violation")
    rules = [("hos_drive", drive, HOUR_MS, 2 * HOUR_MS, "of driving left."),
             ("hos_shift", shift, HOUR_MS, 2 * HOUR_MS, "left on the 14-hour shift."),
             ("hos_break", brk, HOUR_MS / 2, 2 * HOUR_MS, "until the 30-minute break is due."),
             ("hos_cycle", cycle, 3 * HOUR_MS, 6 * HOUR_MS, "left on the 70-hour cycle.")]
    for kind, value, low, ok, words in rules:
        if value is None:
            continue
        if working and 0 < value < low:
            found[kind] = (round(value / 60_000), f"{clock(value)} {words}")
        elif value >= ok:
            clear.add(kind)
    return found, clear


def hos_run(dry, sent):
    for row in rows(
        """select distinct on (h.driver_id) h.*, t.id as truck_id from hos_status h
           join trucks t on t.driver_id = h.driver_id and t.status = 'active'
           join companies c on c.id = t.company_id and c.status = 'active'
           where h.driver_id is not null and h.updated_at > now() - make_interval(mins => %s)
           order by h.driver_id, h.updated_at desc""",
        (HOS_FRESH_MINUTES,),
    ):
        truck = one("select t.*, c.name as company_name from trucks t join companies c on c.id = t.company_id where t.id = %s",
                    (row["truck_id"],))
        found, clear = hos_checks(row)
        apply(truck, found, clear, dry, sent)


def service_run(dry, sent):
    from .queries import service_status, trucks_with_service
    for company in rows("select * from companies where status = 'active'"):
        for truck in trucks_with_service(company["id"]):
            if truck["status"] != "active":
                continue
            truck["company_name"] = company["name"]
            found, clear = {}, set()
            for item in service_status(truck):
                key = item.get("kind") or item["label"]
                soon, over = f"service_soon:{key}", f"service_over:{key}"
                if item["tone"] == "bad":
                    found[over] = (item.get("remaining"), f"{item['label']}: {item['detail']}.")
                    clear.add(soon)
                elif item["tone"] == "warn":
                    found[soon] = (item.get("remaining"), f"{item['label']}: {item['detail']}.")
                    clear.add(over)
                elif item["tone"] == "ok":
                    clear.update({soon, over})
            apply(truck, found, clear, dry, sent)


def mpg_of(report):
    miles = (report.get("distanceTraveledMeters") or 0) / M_PER_MILE
    gallons = (report.get("fuelConsumedMl") or 0) / ML_PER_GALLON
    return (miles / gallons if gallons > 1 else None), miles


def mpg_run(dry, sent):
    from .sync import client_for
    from .safety import iso
    today = datetime.now(timezone.utc).date()
    for company in rows(
        """select c.* from companies c join integrations i on i.company_id = c.id and i.provider = 'samsara'
           where c.status = 'active' and i.credential is not null"""
    ):
        if one("select 1 from mpg_checks where company_id = %s and day = %s", (company["id"], today)):
            continue
        client, _ = client_for(company["id"])
        end = now()
        split = end - timedelta(days=MPG_RECENT_DAYS)
        start = split - timedelta(days=MPG_BASE_DAYS)
        recent = client.get("/fleet/reports/vehicles/fuel-energy", {"startDate": iso(split), "endDate": iso(end)})
        base = client.get("/fleet/reports/vehicles/fuel-energy", {"startDate": iso(start), "endDate": iso(split)})
        before = {r["vehicle"]["id"]: r for r in (base.get("data") or {}).get("vehicleReports", [])}
        linked = {r["external_id"]: r["truck_id"] for r in rows(
            "select external_id, truck_id from vehicle_links where company_id = %s and truck_id is not null", (company["id"],))}
        for report in (recent.get("data") or {}).get("vehicleReports", []):
            truck_id = linked.get(report["vehicle"]["id"])
            old = before.get(report["vehicle"]["id"])
            if not truck_id or not old:
                continue
            now_mpg, now_miles = mpg_of(report)
            old_mpg, old_miles = mpg_of(old)
            if not dry:
                execute("""insert into mpg_checks values (%s, %s, %s, %s, %s, %s, %s) on conflict do nothing""",
                        (company["id"], truck_id, today, now_mpg, now_miles, old_mpg, old_miles))
            if not now_mpg or not old_mpg or now_miles < MPG_RECENT_MILES or old_miles < MPG_BASE_MILES:
                continue
            truck = one("select t.*, c.name as company_name from trucks t join companies c on c.id = t.company_id where t.id = %s",
                        (truck_id,))
            if truck["status"] != "active":
                continue
            drop = 1 - now_mpg / old_mpg
            found, clear = {}, set()
            if drop >= MPG_DROP:
                found["mpg_drop"] = (round(now_mpg, 2), f"{now_mpg:.1f} mpg this week, was {old_mpg:.1f} ({drop:.0%} lower). "
                                     "Check tires, air leaks, injectors and idling.")
            elif drop < MPG_OK:
                clear.add("mpg_drop")
            apply(truck, found, clear, dry, sent)


def run(dry=False, slow=True):
    sent = []
    for truck in rows(TRUCKS):
        found, clear = checks(truck)
        apply(truck, found, clear, dry, sent)
    sent += fault_alerts(dry)
    for step in (hos_run, service_run, mpg_run) if slow else (hos_run,):
        try:
            step(dry, sent)
        except Exception:
            log.exception("%s failed", step.__name__)
    return sent
