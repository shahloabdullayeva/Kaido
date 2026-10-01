from datetime import datetime, timedelta, timezone
from html import escape

from . import work_types
from .config import config
from .db import execute, one, rows
from .pti import open_defects
from .queries import expiring_documents, service_status, trucks_with_service
from .reminders import company_chats, describe, zone_for
from .telegram import send

WINDOW_HOURS = 3
LIST_LIMIT = 6


def _unit_line(unit, detail):
    return f"• Unit {escape(str(unit))} — {escape(detail)}"


def _section(title, lines, total=None):
    if not lines:
        return []
    shown = lines[:LIST_LIMIT]
    extra = (total or len(lines)) - len(shown)
    out = [f"<b>{escape(title)}</b>"] + shown
    if extra > 0:
        out.append(f"  and {extra} more")
    return out + [""]


def build(company, today):
    company_id = company["id"]
    fleet = [t for t in trucks_with_service(company_id) if not t.get("is_outside") and t["status"] != "sold"]
    overdue, soon, no_baseline = [], [], 0
    for truck in fleet:
        for item in service_status(truck):
            if item["label"] == "Oil service" and item["due"] is None:
                no_baseline += 1
            elif item["tone"] == "bad":
                overdue.append(_unit_line(truck["unit_number"], f"{item['label']}: {item['detail']}"))
            elif item["tone"] == "warn":
                soon.append(_unit_line(truck["unit_number"], f"{item['label']}: {item['detail']}"))

    breakdowns = rows(
        """select b.id, b.status, b.occurred_at, t.unit_number from breakdowns b join trucks t on t.id = b.truck_id
           where b.company_id = %s and b.status <> 'resolved' order by b.occurred_at""",
        (company_id,),
    )
    work = rows(
        """select m.id, m.kind, m.scheduled_for, t.unit_number from maintenance_orders m
           join trucks t on t.id = m.truck_id
           where m.company_id = %s and m.status <> 'done' and m.scheduled_for <= %s
           order by m.scheduled_for""",
        (company_id, today),
    )
    faults = rows(
        """select f.id, f.dtc_code, f.spn, f.fmi, f.severity, f.description, t.unit_number
           from fault_events f join trucks t on t.id = f.truck_id
           where f.company_id = %s and f.cleared_at is null and f.first_seen_at > now() - interval '24 hours'
             and not exists (select 1 from fault_events p where p.truck_id = f.truck_id and p.code_key = f.code_key
                             and p.id <> f.id and p.first_seen_at < f.first_seen_at
                             and p.last_seen_at > f.first_seen_at - interval '7 days')
           order by (f.severity = 'high') desc, f.first_seen_at desc""",
        (company_id,),
    )
    tz = zone_for(company.get("timezone"))
    day_end = datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=tz)
    due_reminders = rows(
        """select * from reminders where company_id = %s and done_at is null and remind_at < %s
           order by remind_at""",
        (company_id, day_end),
    )
    documents = [d for d in expiring_documents(company_id, days=30)]

    lines = [f"<b>Follow-up</b> · {escape(company['name'])} · {today.strftime('%a %d %b')}", ""]
    lines += _section("Breakdowns still open", [
        _unit_line(b["unit_number"], f"{b['status'].replace('_', ' ')}, since {b['occurred_at'].astimezone(tz).strftime('%d %b')}")
        for b in breakdowns])
    lines += _section("PTI defects not signed off", [
        _unit_line(p["unit_number"], f"{p['defect_count']} defect{'' if p['defect_count'] == 1 else 's'}"
                   + (", driver said NOT safe" if p["safe_to_drive"] is False else "")
                   + f", {p['submitted_at'].astimezone(tz).strftime('%d %b')} — {config.APP_URL}/pti/report/{p['id']}")
        for p in open_defects(company_id)])
    lines += _section("Service overdue", overdue)
    lines += _section("Work scheduled for today or earlier, not done", [
        _unit_line(w["unit_number"], f"{work_types.label(w['kind'])}, #{w['id']}, set for {w['scheduled_for'].strftime('%d %b')}")
        for w in work])
    lines += _section("Reminders due", [
        f"• {escape((describe(company_id, r['entity'], r['entity_id']) or ('Record', ''))[0])}: {escape(r['note'][:120])}"
        for r in due_reminders])
    high = [f for f in faults if f["severity"] == "high"]
    fault_lines = [
        _unit_line(f["unit_number"], f"{f['dtc_code'] or 'SPN %s / FMI %s' % (f['spn'], f['fmi'])}"
                   + (f" ({f['description'][:60]})" if f["description"] else "")
                   + (" — STOP LAMP" if f["severity"] == "high" else ""))
        for f in faults]
    lines += _section(f"New fault codes in the last 24 hours: {len(faults)}, {len(high)} serious", fault_lines)
    lines += _section("Service due soon", soon)
    lines += _section("Papers expired or expiring within 30 days", [
        f"• {escape(d['kind'])} — {escape(d['who'])}, {d['on'].strftime('%d %b')}" for d in documents])
    if no_baseline:
        lines += [f"{no_baseline} {'truck has' if no_baseline == 1 else 'trucks have'} no oil change on record, so no oil reminder can go out. "
                  f"Add them at {config.APP_URL}/trucks/baselines", ""]
    if len(lines) <= 2 + (2 if no_baseline else 0):
        lines.insert(2, "Nothing needs doing today.")
        lines.insert(3, "")
    lines.append(f"{config.APP_URL}/")
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3950].rsplit("\n", 1)[0] + f"\n…\n{config.APP_URL}/"
    return text


def run(now=None, force_company=None):
    now = now or datetime.now(timezone.utc)
    sent = []
    companies = rows("select * from companies where status = 'active' order by id")
    for company in companies:
        if force_company is None:
            if not company["followup_enabled"]:
                continue
            local_now = now.astimezone(zone_for(company["timezone"]))
            start = company["followup_hour"]
            if not (start <= local_now.hour < start + WINDOW_HOURS):
                continue
        elif company["id"] != force_company:
            continue
        local_now = now.astimezone(zone_for(company["timezone"]))
        today = local_now.date()
        if force_company is None and one(
            "select id from followups where company_id = %s and local_day = %s", (company["id"], today)
        ):
            continue
        chats = company_chats(company["id"])
        text = build(company, today)
        for chat in chats:
            send(chat, text)
        execute(
            """insert into followups (company_id, local_day, recipients, body) values (%s, %s, %s, %s)
               on conflict (company_id, local_day) do update set recipients = excluded.recipients,
                 body = excluded.body, sent_at = now()""",
            (company["id"], today, len(chats), text),
        )
        sent.append((company["name"], len(chats)))
    return sent


def send_fault_alerts():
    fresh = rows(
        """select f.*, t.unit_number, t.make, t.model, t.location, c.name as company_name
           from fault_events f
           join trucks t on t.id = f.truck_id
           join companies c on c.id = f.company_id
           left join fault_alerts a on a.fault_id = f.id
           where a.fault_id is null and f.severity = 'high' and f.cleared_at is null
             and f.first_seen_at > now() - interval '2 hours' and c.status = 'active'
             and not exists (select 1 from fault_events p where p.truck_id = f.truck_id and p.code_key = f.code_key
                             and p.id <> f.id and p.first_seen_at < f.first_seen_at
                             and p.last_seen_at > f.first_seen_at - interval '7 days')
           order by f.first_seen_at"""
    )
    for fault in fresh:
        code = fault["dtc_code"] or f"SPN {fault['spn']} / FMI {fault['fmi']}"
        text = "\n".join(part for part in [
            f"<b>Stop-lamp fault</b> · {escape(fault['company_name'])}",
            f"Unit {escape(fault['unit_number'])} · {escape(code)}",
            escape(fault["description"]) if fault["description"] else None,
            f"Near {escape(fault['location'])}" if fault["location"] else None,
            "",
            f"{config.APP_URL}/faults/{fault['id']}",
        ] if part is not None)
        for chat in company_chats(fault["company_id"]):
            send(chat, text)
        execute("insert into fault_alerts (fault_id, company_id) values (%s, %s) on conflict do nothing",
                (fault["id"], fault["company_id"]))
    return len(fresh)
