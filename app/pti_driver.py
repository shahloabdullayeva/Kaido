from datetime import datetime, timezone
from html import escape

from . import pti
from .db import execute, one, rows
from .reminders import zone_for
from .security import random_token
from .telegram import send

WINDOW_HOURS = 3
WEEKDAYS = [(1, "Mon"), (2, "Tue"), (3, "Wed"), (4, "Thu"), (5, "Fri"), (6, "Sat"), (7, "Sun")]
LIMIT = 3800


def link_code(company):
    if company.get("driver_link_code"):
        return company["driver_link_code"]
    code = random_token(9)
    execute("update companies set driver_link_code = %s where id = %s and driver_link_code is null", (code, company["id"]))
    return one("select driver_link_code from companies where id = %s", (company["id"],))["driver_link_code"]


def claim_group(code, chat):
    company = one("select * from companies where driver_link_code = %s and status = 'active'", (code,))
    if not company:
        return None
    execute(
        """update companies set driver_chat_id = %s, driver_chat_title = %s, driver_link_code = null, updated_at = now()
           where id = %s""",
        (chat["id"], chat.get("title"), company["id"]),
    )
    return company


def forget_group(chat_id):
    return execute(
        "update companies set driver_chat_id = null, driver_chat_title = null, updated_at = now() where driver_chat_id = %s",
        (chat_id,),
    )


def move_group(old_id, new_id):
    return execute("update companies set driver_chat_id = %s, updated_at = now() where driver_chat_id = %s", (new_id, old_id))


def fleet(company_id):
    trucks = rows(
        """select t.id, t.unit_number, t.pti_token, t.company_id, d.name as driver_name,
                  d.telegram_username, d.telegram_user_id,
                  exists (select 1 from inspections i where i.truck_id = t.id and i.defect_count > 0
                          and i.certified_at is null) as open_defect
           from trucks t left join drivers d on d.id = t.driver_id
           where t.company_id = %s and t.status = 'active' and not t.is_outside
           order by lower(t.unit_number)""",
        (company_id,),
    )
    for truck in trucks:
        truck["url"] = pti.link_for(pti.ensure_token(truck))
    return trucks


def mention(truck):
    if truck.get("telegram_username"):
        return "@" + escape(truck["telegram_username"])
    if truck.get("telegram_user_id"):
        return f"<a href=\"tg://user?id={int(truck['telegram_user_id'])}\">{escape(truck['driver_name'] or 'driver')}</a>"
    return ""


def unit_key(value):
    return "".join(ch for ch in (value or "").split(" ")[0].lower() if ch.isalnum())


def find_unit(company_id, typed):
    wanted = unit_key(typed)
    if not wanted:
        return []
    trucks = rows(
        "select id, unit_number, driver_id from trucks where company_id = %s and status <> 'sold' and not is_outside",
        (company_id,),
    )
    exact = [t for t in trucks if unit_key(t["unit_number"]) == wanted]
    if exact:
        return exact
    return [t for t in trucks if unit_key(t["unit_number"]).lstrip("0") == wanted.lstrip("0")]


def claim_unit(chat_id, user, typed):
    company = one("select * from companies where driver_chat_id = %s and status = 'active'", (chat_id,))
    if not company:
        return None, "This group is not connected to a company in Kaido yet."
    found = find_unit(company["id"], typed)
    if not found:
        return None, f"No truck {typed} at {company['name']}. Check the unit number and send /unit again."
    if len(found) > 1:
        return None, "More than one truck matches: " + ", ".join(t["unit_number"] for t in found) + ". Send the full unit."
    truck = found[0]
    name = " ".join(part for part in [user.get("first_name"), user.get("last_name")] if part) or user.get("username") or "Driver"
    execute("update drivers set telegram_user_id = null where company_id = %s and telegram_user_id = %s",
            (company["id"], user["id"]))
    if truck["driver_id"]:
        execute(
            """update drivers set telegram_user_id = %s, telegram_username = coalesce(%s, telegram_username), updated_at = now()
               where id = %s""",
            (user["id"], user.get("username"), truck["driver_id"]),
        )
        driver = one("select name from drivers where id = %s", (truck["driver_id"],))
        name = driver["name"]
    else:
        driver = one(
            """insert into drivers (company_id, name, telegram_username, telegram_user_id, status)
               values (%s, %s, %s, %s, 'active') returning id""",
            (company["id"], name, user.get("username"), user["id"]),
        )
        execute("update trucks set driver_id = %s, updated_at = now() where id = %s", (driver["id"], truck["id"]))
    return truck, f"Got it — {escape(name)} drives Unit {escape(truck['unit_number'])}. PTI reminders for this truck will tag you."


def unit_lines(trucks):
    lines = []
    for truck in trucks:
        line = f"• <a href=\"{escape(truck['url'])}\">Unit {escape(truck['unit_number'])}</a>"
        tag = mention(truck)
        if tag:
            line += f" — {tag}"
        elif truck["driver_name"]:
            line += f" — {escape(truck['driver_name'])}"
        if truck["open_defect"]:
            line += " ⚠️ defect not signed off, check it"
        lines.append(line)
    return lines


def chunks(head, lines, tail):
    out, current = [], head
    for line in lines:
        if len(current) + len(line) + len(tail) + 2 > LIMIT:
            out.append(current)
            current = ""
        current += ("\n" if current else "") + line
    out.append(current + "\n\n" + tail)
    return out


def morning(company):
    head = ("<b>Pre-trip before you drive</b>\n"
            "Check your truck and send the PTI before the first mile today. "
            "If the last report has a defect, read the repair sign-off first.\n")
    tail = "Tap your unit. Mark anything wrong as Defect with a photo — the shop sees it right away."
    return chunks(head, unit_lines(fleet(company["id"])), tail)


def evening(company):
    head = ("<b>End of the day — post-trip</b>\n"
            "Before you go off duty, do the post-trip and report anything wrong so it is fixed before the next trip.\n")
    tail = "Tap your unit. Nothing wrong? Mark all OK and sign — it takes a minute."
    return chunks(head, unit_lines(fleet(company["id"])), tail)


def nudge(trucks):
    head = ("<b>Driving today with no pre-trip</b>\n"
            "Do the PTI at your next safe stop:\n")
    return chunks(head, unit_lines(trucks), "A pre-trip is required before driving each day (FMCSA 396.13).")


def already(company_id, day, kind, truck_id=0):
    return one(
        "select ok from pti_messages where company_id = %s and local_day = %s and kind = %s and truck_id = %s",
        (company_id, day, kind, truck_id),
    )


def record(company_id, day, kind, ok, truck_id=0):
    execute(
        """insert into pti_messages (company_id, local_day, kind, truck_id, ok) values (%s, %s, %s, %s, %s)
           on conflict (company_id, local_day, kind, truck_id) do update set ok = excluded.ok, sent_at = now()""",
        (company_id, day, kind, truck_id, ok),
    )


def deliver(chat_id, messages):
    ok = True
    for text in messages:
        ok = send(chat_id, text).get("ok") and ok
    return bool(ok)


def run(now=None):
    now = now or datetime.now(timezone.utc)
    sent = []
    companies = rows(
        """select * from companies where status = 'active' and pti_messages_enabled and driver_chat_id is not null
           order by id"""
    )
    for company in companies:
        local = now.astimezone(zone_for(company["timezone"]))
        day = local.date()
        chat = company["driver_chat_id"]
        scheduled_day = local.isoweekday() in (company["pti_days"] or [])
        for kind, hour, build in (("morning", company["pti_morning_hour"], morning),
                                  ("evening", company["pti_evening_hour"], evening)):
            if scheduled_day and hour <= local.hour < hour + WINDOW_HOURS and not already(company["id"], day, kind):
                ok = deliver(chat, build(company))
                record(company["id"], day, kind, ok)
                sent.append((company["name"], kind, ok))
        _day, board = pti.today_board(company, day)
        missing = {t["id"] for t in board if t["missing"]}
        if not missing:
            continue
        due = [t for t in fleet(company["id"])
               if t["id"] in missing and not already(company["id"], day, "nudge", t["id"])]
        if due:
            ok = deliver(chat, nudge(due))
            for truck in due:
                record(company["id"], day, "nudge", ok, truck["id"])
            sent.append((company["name"], "nudge " + ", ".join(t["unit_number"] for t in due), ok))
    return sent
