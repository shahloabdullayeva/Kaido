from datetime import datetime, time, timedelta, timezone
from html import escape
from zoneinfo import ZoneInfo

from .config import config
from .db import execute, insert, one, rows
from .telegram import send

ENTITIES = {
    "truck": "Truck",
    "driver": "Driver",
    "maintenance_order": "Work order",
    "breakdown": "Breakdown",
    "fault_event": "Fault",
    "fuel_transaction": "Fuel entry",
}
AUDIENCES = {"me": "Just me", "admins": "Every admin in this company"}


def zone_for(name):
    try:
        return ZoneInfo(name or config.TIMEZONE)
    except Exception:
        return ZoneInfo("America/Chicago")


def default_when(company):
    tz = zone_for(company.get("timezone"))
    tomorrow = datetime.now(tz).date() + timedelta(days=1)
    return datetime.combine(tomorrow, time(9, 0))


def to_utc(local_value, company):
    if local_value is None:
        return None
    return local_value.replace(tzinfo=zone_for(company.get("timezone"))).astimezone(timezone.utc)


def local(value, company):
    if value is None:
        return None
    return value.astimezone(zone_for(company.get("timezone")))


def describe(company_id, entity, entity_id):
    if entity == "truck":
        row = one("select unit_number from trucks where id = %s and company_id = %s", (entity_id, company_id))
        return (f"Unit {row['unit_number']}", f"/trucks/{entity_id}") if row else None
    if entity == "driver":
        row = one("select name from drivers where id = %s and company_id = %s", (entity_id, company_id))
        return (row["name"], f"/drivers/{entity_id}") if row else None
    if entity == "maintenance_order":
        row = one(
            """select m.kind, t.unit_number from maintenance_orders m join trucks t on t.id = m.truck_id
               where m.id = %s and m.company_id = %s""",
            (entity_id, company_id),
        )
        if not row:
            return None
        return (f"Work order #{entity_id} · unit {row['unit_number']} · {row['kind'].replace('_', ' ')}",
                f"/maintenance/{entity_id}")
    if entity == "breakdown":
        row = one(
            """select t.unit_number from breakdowns b join trucks t on t.id = b.truck_id
               where b.id = %s and b.company_id = %s""",
            (entity_id, company_id),
        )
        return (f"Breakdown #{entity_id} · unit {row['unit_number']}", f"/breakdowns/{entity_id}") if row else None
    if entity == "fault_event":
        row = one(
            """select f.dtc_code, f.spn, f.fmi, t.unit_number from fault_events f join trucks t on t.id = f.truck_id
               where f.id = %s and f.company_id = %s""",
            (entity_id, company_id),
        )
        if not row:
            return None
        code = row["dtc_code"] or f"SPN {row['spn']} / FMI {row['fmi']}"
        return (f"Fault {code} · unit {row['unit_number']}", f"/faults/{entity_id}")
    if entity == "fuel_transaction":
        row = one(
            """select t.id, t.unit_number from fuel_transactions f join trucks t on t.id = f.truck_id
               where f.id = %s and f.company_id = %s""",
            (entity_id, company_id),
        )
        return (f"Fuel entry · unit {row['unit_number']}", f"/fuel?truck_id={row['id']}") if row else None
    return None


def for_entity(company_id, entity, entity_id):
    return rows(
        """select r.*, u.name as author, d.name as done_name from reminders r
           left join users u on u.id = r.created_by
           left join users d on d.id = r.done_by
           where r.company_id = %s and r.entity = %s and r.entity_id = %s
           order by r.done_at is not null, r.remind_at""",
        (company_id, entity, entity_id),
    )


def open_for_company(company_id, limit=200):
    return rows(
        """select r.*, u.name as author from reminders r
           left join users u on u.id = r.created_by
           where r.company_id = %s and r.done_at is null
           order by r.remind_at limit %s""",
        (company_id, limit),
    )


def create(company_id, entity, entity_id, note, remind_at, audience, user_id):
    return insert(
        """insert into reminders (company_id, entity, entity_id, note, remind_at, audience, created_by)
           values (%s, %s, %s, %s, %s, %s, %s) returning *""",
        (company_id, entity, entity_id, note, remind_at, audience, user_id),
    )


def finish(company_id, reminder_id, user_id):
    return execute(
        "update reminders set done_at = now(), done_by = %s where id = %s and company_id = %s and done_at is null",
        (user_id, reminder_id, company_id),
    )


def company_chats(company_id, admins_only=False):
    clause = " and m.role = 'admin'" if admins_only else ""
    return [row["telegram_chat_id"] for row in rows(
        f"""select distinct u.telegram_chat_id from memberships m join users u on u.id = m.user_id
            where m.company_id = %s and u.status = 'active' and u.telegram_chat_id is not null{clause}""",
        (company_id,),
    )]


def reminder_chats(reminder):
    if reminder["audience"] == "admins":
        return company_chats(reminder["company_id"], admins_only=True)
    row = one("select telegram_chat_id from users where id = %s and status = 'active'", (reminder["created_by"],))
    return [row["telegram_chat_id"]] if row and row["telegram_chat_id"] else []


def send_due():
    due = rows(
        """select r.*, c.name as company_name, c.timezone, u.name as author from reminders r
           join companies c on c.id = r.company_id
           left join users u on u.id = r.created_by
           where r.sent_at is null and r.done_at is null and r.remind_at <= now()
             and c.status = 'active'
           order by r.remind_at limit 100"""
    )
    sent = 0
    for reminder in due:
        about = describe(reminder["company_id"], reminder["entity"], reminder["entity_id"])
        label, href = about if about else (ENTITIES.get(reminder["entity"], "Record"), "/reminders")
        text = "\n".join([
            f"<b>Reminder</b> · {escape(reminder['company_name'])}",
            escape(label),
            "",
            escape(reminder["note"]),
            "",
            f"Set by {escape(reminder['author'] or 'someone')}",
            f"{config.APP_URL}{href}",
        ])
        for chat in reminder_chats(reminder):
            send(chat, text)
        execute("update reminders set sent_at = now() where id = %s", (reminder["id"],))
        sent += 1
    return sent
