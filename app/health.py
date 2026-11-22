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
IDLE_MINUTES = 60
SILENT_HOURS = 6
SILENT_MAX_HOURS = 48
REOPEN_HOURS = 6
FAULT_NEW_DAYS = 30
OFFICE_ONLY = {"idling", "not_reporting"}

TITLES = {
    "battery_low": "Battery low",
    "not_charging": "Battery not charging",
    "coolant_hot": "Engine running hot",
    "oil_low": "Low oil pressure",
    "def_low": "DEF low",
    "idling": "Idling",
    "not_reporting": "Not reporting",
    "check_engine": "Check engine",
}


def now():
    return datetime.now(timezone.utc)


def parse_time(text):
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


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
    lines = [f"<b>{TITLES[kind]}</b> · Unit {escape(unit_label(truck['unit_number']))}", escape(detail)]
    if truck.get("location"):
        lines.append(f"Near {escape(truck['location'])}")
    if office:
        if truck.get("company_name"):
            lines[0] += f" · {escape(truck['company_name'])}"
        lines.append(f"{config.APP_URL}/trucks/{truck['id']}")
    return "\n".join(lines)


def deliver(truck, kind, detail, office_too=True):
    sent = False
    if truck.get("telegram_chat_id") and kind not in OFFICE_ONLY:
        sent = bool(send(truck["telegram_chat_id"], message(truck, kind, detail, False)).get("ok")) or sent
    if office_too:
        for chat in company_chats(truck["company_id"]):
            sent = bool(send(chat, message(truck, kind, detail, True)).get("ok")) or sent
    return sent


def open_alert(truck, kind, value, detail, dry=False):
    if one("select 1 from health_alerts where truck_id = %s and kind = %s and fault_id is null and cleared_at is null",
           (truck["id"], kind)):
        return False
    if one("""select 1 from health_alerts where truck_id = %s and kind = %s and fault_id is null
              and cleared_at > now() - make_interval(hours => %s)""", (truck["id"], kind, REOPEN_HOURS)):
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


def run(dry=False):
    sent = []
    for truck in rows(TRUCKS):
        found, clear = checks(truck)
        for kind in clear - set(found):
            if not dry:
                execute("""update health_alerts set cleared_at = now() where truck_id = %s and kind = %s
                           and fault_id is null and cleared_at is null""", (truck["id"], kind))
        for kind, (value, detail) in found.items():
            if open_alert(truck, kind, value, detail, dry):
                sent.append((truck["unit_number"], kind, detail))
    sent += fault_alerts(dry)
    return sent
