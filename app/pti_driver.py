from datetime import datetime, timezone
from html import escape

from . import pti
from .db import execute, one, rows
from .reminders import zone_for
from .security import random_token
from .telegram import send

WINDOW_HOURS = 3
WEEKDAYS = [(1, "Mon"), (2, "Tue"), (3, "Wed"), (4, "Thu"), (5, "Fri"), (6, "Sat"), (7, "Sun")]

TRUCK_SQL = """select t.id, t.unit_number, t.pti_token, t.company_id, t.driver_id, t.telegram_chat_id,
                      t.telegram_chat_title, d.name as driver_name, d.telegram_username, d.telegram_user_id,
                      exists (select 1 from inspections i where i.truck_id = t.id and i.defect_count > 0
                              and i.certified_at is null) as open_defect
               from trucks t left join drivers d on d.id = t.driver_id"""


def link_code(truck):
    if truck.get("telegram_link_code"):
        return truck["telegram_link_code"]
    execute("update trucks set telegram_link_code = %s where id = %s and telegram_link_code is null",
            (random_token(9), truck["id"]))
    return one("select telegram_link_code from trucks where id = %s", (truck["id"],))["telegram_link_code"]


def claim_group(code, chat):
    truck = one(
        """select t.*, c.name as company_name from trucks t join companies c on c.id = t.company_id
           where t.telegram_link_code = %s and c.status = 'active' and t.status <> 'sold'""",
        (code,),
    )
    if not truck:
        return None
    execute(
        """update trucks set telegram_chat_id = %s, telegram_chat_title = %s, telegram_link_code = null,
             updated_at = now() where id = %s""",
        (chat["id"], chat.get("title"), truck["id"]),
    )
    return truck


def forget_group(chat_id):
    return execute(
        "update trucks set telegram_chat_id = null, telegram_chat_title = null, updated_at = now() where telegram_chat_id = %s",
        (chat_id,),
    )


def move_group(old_id, new_id):
    return execute("update trucks set telegram_chat_id = %s, updated_at = now() where telegram_chat_id = %s",
                   (new_id, old_id))


def disconnect(company_id, truck_id):
    return execute(
        """update trucks set telegram_chat_id = null, telegram_chat_title = null, updated_at = now()
           where id = %s and company_id = %s""",
        (truck_id, company_id),
    )


def group_trucks(chat_id):
    return rows(TRUCK_SQL + " where t.telegram_chat_id = %s and t.status <> 'sold' order by lower(t.unit_number)",
                (chat_id,))


def connected(company_id):
    return rows(TRUCK_SQL + """ where t.company_id = %s and t.telegram_chat_id is not null and t.status <> 'sold'
                                order by lower(t.unit_number)""", (company_id,))


def one_truck(company_id, truck_id):
    return one(TRUCK_SQL + " where t.id = %s and t.company_id = %s", (truck_id, company_id))


def mention(truck):
    if truck.get("telegram_username"):
        return "@" + escape(truck["telegram_username"])
    if truck.get("telegram_user_id"):
        return f"<a href=\"tg://user?id={int(truck['telegram_user_id'])}\">{escape(truck['driver_name'] or 'driver')}</a>"
    return ""


def unit_key(value):
    return "".join(ch for ch in (value or "").split(" ")[0].lower() if ch.isalnum())


def claim_unit(chat_id, user, typed):
    trucks = group_trucks(chat_id)
    if not trucks:
        return None, "This group is not connected to a truck yet. Ask the office for the /truck code."
    if typed:
        wanted = unit_key(typed)
        trucks = [t for t in trucks if unit_key(t["unit_number"]) == wanted
                  or unit_key(t["unit_number"]).lstrip("0") == wanted.lstrip("0")]
        if not trucks:
            return None, "That unit is not connected to this group."
    if len(trucks) > 1:
        return None, "This group has more than one truck. Send /unit with your truck number."
    truck = trucks[0]
    name = " ".join(part for part in [user.get("first_name"), user.get("last_name")] if part) or user.get("username") or "Driver"
    execute("update drivers set telegram_user_id = null where company_id = %s and telegram_user_id = %s",
            (truck["company_id"], user["id"]))
    if truck["driver_id"]:
        execute(
            """update drivers set telegram_user_id = %s, telegram_username = coalesce(%s, telegram_username), updated_at = now()
               where id = %s""",
            (user["id"], user.get("username"), truck["driver_id"]),
        )
        name = truck["driver_name"]
    else:
        driver = one(
            """insert into drivers (company_id, name, telegram_username, telegram_user_id, status)
               values (%s, %s, %s, %s, 'active') returning id""",
            (truck["company_id"], name, user.get("username"), user["id"]),
        )
        execute("update trucks set driver_id = %s, updated_at = now() where id = %s", (driver["id"], truck["id"]))
    return truck, f"Got it — {escape(name)} drives Unit {escape(truck['unit_number'])}. PTI reminders here will tag you."


def unit_block(truck, label):
    tag = mention(truck)
    line = f"<b>Unit {escape(truck['unit_number'])}</b>" + (f" — {tag}" if tag else "")
    lines = [line, f"<a href=\"{escape(pti.link_for(pti.ensure_token(truck)))}\">{label}</a>"]
    if truck["open_defect"]:
        lines.append("⚠️ The last report has a defect that is not signed off. Check it before you drive.")
    return lines


def morning(truck):
    return "\n".join(["<b>Pre-trip before you drive</b>"] + unit_block(truck, "Open your pre-trip") + [
        "", "Check the truck and send the PTI before the first mile. If the last report has a defect, read the repair sign-off first."])


def evening(truck):
    return "\n".join(["<b>End of the day — post-trip</b>"] + unit_block(truck, "Open your post-trip") + [
        "", "Before you go off duty, report anything wrong so it is fixed before the next trip. Nothing wrong? Mark all OK and sign."])


def nudge(truck):
    return "\n".join(["<b>Driving today with no pre-trip</b>"] + unit_block(truck, "Do the PTI at your next safe stop") + [
        "", "A pre-trip is required before driving each day (FMCSA 396.13)."])


def completed(inspection):
    truck = one(TRUCK_SQL + " where t.id = %s", (inspection["truck_id"],))
    if not truck or not truck["telegram_chat_id"]:
        return False
    kind = pti.KINDS.get(inspection["kind"], "Inspection").lower()
    who = mention(truck) if truck["driver_id"] and inspection["driver_id"] == truck["driver_id"] else ""
    lines = [f"✅ <b>Unit {escape(truck['unit_number'])}</b> — {kind} done by {escape(inspection['driver_name'] or 'driver')}"
             + (f" {who}" if who else "")]
    found = pti.defects_of(inspection)
    if not found:
        lines.append("No defects.")
    else:
        lines.append(f"{'🛑 NOT SAFE TO DRIVE — ' if inspection['safe_to_drive'] is False else ''}"
                     f"{len(found)} defect{'' if len(found) == 1 else 's'} reported:")
        lines += [f"• {escape(d['label'])}" + (f" — {escape(d['note'][:120])}" if d["note"] else "") for d in found]
        lines.append("The office has it and will sign off the repair.")
    return bool(send(truck["telegram_chat_id"], "\n".join(lines)).get("ok"))


def rejected(inspection, reason):
    truck = one(TRUCK_SQL + " where t.id = %s", (inspection["truck_id"],))
    if not truck or not truck["telegram_chat_id"]:
        return False
    kind = pti.KINDS.get(inspection["kind"], "Inspection").lower()
    tag = mention(truck)
    zone = zone_for(one("select timezone from companies where id = %s", (truck["company_id"],))["timezone"])
    when = inspection["submitted_at"].astimezone(zone).strftime("%d %b %H:%M")
    lines = [f"❌ <b>Unit {escape(truck['unit_number'])}</b>" + (f" {tag}" if tag else ""),
             f"Your {kind} from {when} was done wrong, so it was not accepted.",
             f"What was wrong: {escape(reason)}",
             "",
             f"Please <a href=\"{escape(pti.link_for(pti.ensure_token(truck)))}\">do the PTI again</a>. "
             "This time take each photo of the truck itself, close and in good light, so it goes through."]
    return bool(send(truck["telegram_chat_id"], "\n".join(lines)).get("ok"))


BUILDERS = {"morning": morning, "evening": evening, "nudge": nudge}


def already(company_id, day, kind, truck_id):
    return one(
        "select ok from pti_messages where company_id = %s and local_day = %s and kind = %s and truck_id = %s",
        (company_id, day, kind, truck_id),
    )


def deliver(truck, kind, day=None):
    result = send(truck["telegram_chat_id"], BUILDERS[kind](truck))
    if day is not None:
        execute(
            """insert into pti_messages (company_id, local_day, kind, truck_id, ok, chat_id, message_ids)
               values (%s, %s, %s, %s, %s, %s, %s)
               on conflict (company_id, local_day, kind, truck_id) do update set ok = excluded.ok,
                 chat_id = excluded.chat_id, message_ids = excluded.message_ids, sent_at = now()""",
            (truck["company_id"], day, kind, truck["id"], bool(result.get("ok")), truck["telegram_chat_id"],
             [result["message_id"]] if result.get("message_id") else None),
        )
    return bool(result.get("ok"))


def run(now=None):
    now = now or datetime.now(timezone.utc)
    sent = []
    companies = rows("select * from companies where status = 'active' and pti_messages_enabled order by id")
    for company in companies:
        trucks = connected(company["id"])
        if not trucks:
            continue
        local = now.astimezone(zone_for(company["timezone"]))
        day = local.date()
        scheduled_day = local.isoweekday() in (company["pti_days"] or [])
        _day, board = pti.today_board(company, day)
        missing = {t["id"] for t in board if t["missing"]}
        for truck in trucks:
            for kind, hour in (("morning", company["pti_morning_hour"]), ("evening", company["pti_evening_hour"])):
                if scheduled_day and hour <= local.hour < hour + WINDOW_HOURS and not already(company["id"], day, kind, truck["id"]):
                    sent.append((truck["unit_number"], kind, deliver(truck, kind, day)))
            if truck["id"] in missing and not already(company["id"], day, "nudge", truck["id"]):
                sent.append((truck["unit_number"], "nudge", deliver(truck, "nudge", day)))
    return sent
