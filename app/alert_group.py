import re
import subprocess
import sys
import time
from html import escape
from pathlib import Path

from .db import execute, one, rows
from .logs import get
from .telegram import call, send, send_photo, send_video

log = get("alert-group")

ROOT = Path(__file__).resolve().parent.parent

TOPICS = {
    "check_engine": "Check engine",
    "stop_lamp": "Stop-lamp faults",
    "battery": "Battery",
    "charging": "Charging",
    "coolant": "Engine temperature",
    "oil": "Oil pressure",
    "def": "DEF",
    "tires": "Tire pressure",
    "idling": "Idling",
    "not_reporting": "ELD not reporting",
    "hours": "Hours of service",
    "service": "Service due",
    "mpg": "MPG",
    "speeding": "Speeding",
    "safety": "Harsh driving and camera",
    "videos": "Safety event videos",
    "fuel": "Fuel checks",
    "fuel_reports": "Fuel reports",
    "pti": "PTI",
    "documents": "Documents",
    "reminders": "Reminders",
    "followup": "Daily follow-up",
    "summary": "Summary",
}

HEALTH_TOPICS = {
    "battery_low": "battery",
    "not_charging": "charging",
    "coolant_hot": "coolant",
    "oil_low": "oil",
    "def_low": "def",
    "tire_low": "tires",
    "idling": "idling",
    "not_reporting": "not_reporting",
    "check_engine": "check_engine",
    "service_soon": "service",
    "service_over": "service",
    "mpg_drop": "mpg",
}

GAP_SECONDS = 3.2


def health_topic(kind):
    base = kind.split(":", 1)[0]
    if base.startswith("hos_"):
        return "hours"
    return HEALTH_TOPICS.get(base, "check_engine")


def safety_topic(kind):
    return "speeding" if kind.startswith("speeding") else "safety"


def chat_of(company_id):
    row = one("select chat_id from alert_groups where company_id = %s", (company_id,))
    return row["chat_id"] if row else None


def chat_of_any(chat_id):
    return bool(one("select 1 from alert_groups where chat_id = %s", (chat_id,)))


def create_topic(chat_id, topic):
    result = call("createForumTopic", {"chat_id": chat_id, "name": TOPICS[topic]})
    thread = (result.get("result") or {}).get("message_thread_id") if result.get("ok") else None
    if not thread:
        log.warning("topic %s in %s not created: %s", topic, chat_id, result.get("reason"))
        return None
    execute("""insert into alert_topics (chat_id, topic, thread_id) values (%s, %s, %s)
               on conflict (chat_id, topic) do update set thread_id = excluded.thread_id, created_at = now()""",
            (chat_id, topic, thread))
    return thread


def thread_of(chat_id, topic, fresh=False):
    if not fresh:
        row = one("select thread_id from alert_topics where chat_id = %s and topic = %s", (chat_id, topic))
        if row:
            return row["thread_id"]
    return create_topic(chat_id, topic)


def ensure_topics(chat_id):
    made = 0
    for topic in TOPICS:
        if not one("select 1 from alert_topics where chat_id = %s and topic = %s", (chat_id, topic)):
            made += bool(create_topic(chat_id, topic))
            time.sleep(1)
    return made


def lost_thread(result):
    reason = (result.get("reason") or "").lower()
    return "thread not found" in reason or "topic_deleted" in reason or "topic deleted" in reason


def deliver(chat_id, text, png=None, video=None, **extra):
    if video is not None:
        return send_video(chat_id, video, text, **extra)
    if png is not None:
        return send_photo(chat_id, png, text, **extra)
    return send(chat_id, text, **extra)


def post(chat_id, topic, text, png=None, video=None):
    for fresh in (False, True):
        thread = thread_of(chat_id, topic, fresh)
        if not thread:
            return deliver(chat_id, text, png, video)
        result = deliver(chat_id, text, png, video, message_thread_id=thread)
        if result.get("ok") or not lost_thread(result):
            return result
    return result


def office(company_id, topic, text, admins_only=False, fallback=None):
    chat = chat_of(company_id)
    if chat:
        return [post(chat, topic, text)]
    from .reminders import company_chats
    chats = fallback if fallback is not None else company_chats(company_id, admins_only)
    return [send(c, text) for c in chats]


def office_photo(company_id, topic, png, caption):
    chat = chat_of(company_id)
    return post(chat, topic, caption, png) if chat else None


def office_video(company_id, topic, video, caption):
    chat = chat_of(company_id)
    return post(chat, topic, caption, video=video) if chat else None


def simple(name):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).replace(" llc", " ").split())


def link(chat, user):
    mine = rows(
        """select c.id, c.name, g.chat_id from memberships m join companies c on c.id = m.company_id
           left join alert_groups g on g.company_id = c.id
           where m.user_id = %s and m.role = 'admin' and c.status = 'active' and c.alerts_group order by c.id""",
        (user["id"],),
    )
    title = simple(chat.get("title"))
    named = [c for c in mine if len(title) >= 3 and len(simple(c["name"])) >= 3 and (simple(c["name"]) in title or title in simple(c["name"]))]
    companies = named or [c for c in mine if c["chat_id"] in (None, chat["id"])]
    for company in companies:
        execute("""insert into alert_groups (company_id, chat_id, linked_by) values (%s, %s, %s)
                   on conflict (company_id) do update set chat_id = excluded.chat_id, linked_by = excluded.linked_by,
                     linked_at = now(), backfilled_at = null""",
                (company["id"], chat["id"], user["id"]))
    return companies


def kaido_user(sender):
    if not sender.get("id"):
        return None
    return one("select * from users where telegram_chat_id = %s and status = 'active'", (sender["id"],))


def handle(chat, sender, reply_to=None):
    user = kaido_user(sender)
    if not user:
        send(chat["id"], "Only a Kaido admin with Telegram linked can do this.", reply_to_message_id=reply_to)
        return
    if not chat.get("is_forum"):
        send(chat["id"], "Turn on Topics in the group settings first, then send /alerts again.", reply_to_message_id=reply_to)
        return
    companies = link(chat, user)
    if not companies:
        send(chat["id"], "No company of yours is set to use an alerts group.", reply_to_message_id=reply_to)
        return
    made = ensure_topics(chat["id"])
    if made == 0 and not one("select 1 from alert_topics where chat_id = %s", (chat["id"],)):
        send(chat["id"], "Could not create topics. Give the bot the \"Manage topics\" admin right and send /alerts again.")
        return
    names = ", ".join(escape(c["name"]) for c in companies)
    send(chat["id"], f"Alerts for {names} now come here, one topic per issue. Sending past alerts now, oldest first.")
    subprocess.Popen([sys.executable, str(ROOT / "manage.py"), "alerts-history", "--chat", str(chat["id"])],
                     cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def stamp(moment, zone):
    return moment.astimezone(zone).strftime("%d %b %H:%M")


def history(company):
    from . import config
    from .health import message as health_message
    from .reminders import zone_for
    from .safety import message as safety_message
    zone = zone_for(company["timezone"])
    items = []
    for alert in rows(
        """select a.*, t.id as tid, t.unit_number, t.telegram_chat_id from health_alerts a join trucks t on t.id = a.truck_id
           where a.company_id = %s order by a.opened_at""", (company["id"],)):
        truck = {"id": alert["tid"], "unit_number": alert["unit_number"], "company_name": company["name"]}
        items.append((alert["opened_at"], health_topic(alert["kind"]),
                      health_message(truck, alert["kind"], alert["detail"] or "", True)))
    for fault in rows(
        """select f.*, t.unit_number, a.sent_at from fault_alerts a join fault_events f on f.id = a.fault_id
           join trucks t on t.id = f.truck_id where a.company_id = %s""", (company["id"],)):
        code = fault["dtc_code"] or f"SPN {fault['spn']} / FMI {fault['fmi']}"
        text = "\n".join(p for p in [
            f"<b>Stop-lamp fault</b> · {escape(company['name'])}",
            f"Unit {escape(fault['unit_number'])} · {escape(code)}",
            escape(fault["description"]) if fault["description"] else None,
            f"{config.APP_URL}/faults/{fault['id']}"] if p)
        items.append((fault["sent_at"], "stop_lamp", text))
    for event in rows(
        """select e.*, t.unit_number, d.name as driver_name from safety_events e
           left join trucks t on t.id = e.truck_id left join drivers d on d.id = e.driver_id
           where e.company_id = %s and e.alerted_at is not null""", (company["id"],)):
        items.append((event["happened_at"], safety_topic(event["kind"]), safety_message(event, company)))
    for alert in rows(
        """select f.*, t.unit_number from fuel_alerts f left join trucks t on t.id = f.truck_id
           where f.company_id = %s""", (company["id"],)):
        from .fuel_guard import LABELS
        text = "\n".join(p for p in [
            f"<b>Fuel check: {LABELS.get(alert['kind'], alert['kind'])}</b> · {escape(company['name'])}",
            f"Unit {escape(alert['unit_number'])}" if alert["unit_number"] else None,
            escape(alert["summary"]),
            f"{config.APP_URL}/fuel/alerts"] if p)
        items.append((alert["happened_at"], "fuel", text))
    for item in rows(
        """select i.id, i.alerted_at, i.kind, i.driver_name, t.unit_number from inspections i
           join trucks t on t.id = i.truck_id where i.company_id = %s and i.alerted_at is not null""", (company["id"],)):
        text = "\n".join([f"<b>PTI defect</b> · {escape(company['name'])}",
                          f"Unit {escape(item['unit_number'])} · {escape(item['driver_name'] or 'unknown driver')}",
                          f"{config.APP_URL}/pti/report/{item['id']}"])
        items.append((item["alerted_at"], "pti", text))
    for reminder in rows("select r.* from reminders r where r.company_id = %s and r.sent_at is not null", (company["id"],)):
        text = "\n".join([f"<b>Reminder</b> · {escape(company['name'])}", escape(reminder["note"] or "")])
        items.append((reminder["sent_at"], "reminders", text))
    for row in rows("select sent_at, body from followups where company_id = %s and body is not null", (company["id"],)):
        items.append((row["sent_at"], "followup", row["body"]))
    for row in rows("select sent_at, body from summaries where company_id = %s and body is not null", (company["id"],)):
        items.append((row["sent_at"], "summary", row["body"]))
    return [(at, topic, f"<i>{stamp(at, zone)}</i>\n{text}") for at, topic, text in items if at]


def pieces(text, limit=3900):
    parts, current = [], ""
    for line in text.split("\n"):
        if current and len(current) + len(line) + 1 > limit:
            parts.append(current)
            current = ""
        current = f"{current}\n{line}" if current else line[:limit]
    return parts + [current] if current else parts


def send_history(chat_id):
    companies = rows("""select c.* from alert_groups g join companies c on c.id = g.company_id
                        where g.chat_id = %s and g.backfilled_at is null""", (chat_id,))
    items = []
    for company in companies:
        try:
            items += history(company)
        except Exception:
            log.exception("history for %s failed", company["id"])
    items.sort(key=lambda item: item[0])
    sent = 0
    for _, topic, text in items:
        ok = True
        for part in pieces(text):
            result = post(chat_id, topic, part)
            if not result.get("ok") and "retry after" in (result.get("reason") or "").lower():
                time.sleep(int("".join(ch for ch in result["reason"].split("after")[-1] if ch.isdigit()) or 30) + 1)
                result = post(chat_id, topic, part)
            ok = ok and bool(result.get("ok"))
            time.sleep(GAP_SECONDS)
        sent += ok
    for company in companies:
        execute("update alert_groups set backfilled_at = now() where company_id = %s", (company["id"],))
    send(chat_id, f"Past alerts done: {sent} of {len(items)} sent.")
    return sent, len(items)
