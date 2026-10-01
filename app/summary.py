import os
from html import escape

from .config import config
from .db import execute, one, rows
from .reminders import company_chats
from .telegram import send


def _size(path):
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def _since(company_id):
    row = one("select max(sent_at) as at from summaries where company_id = %s", (company_id,))
    return row["at"] if row and row["at"] else None


def build(company, backups):
    since = _since(company["id"])
    window = "coalesce(%s::timestamptz, now() - interval '4 days')"
    stats = one(
        f"""select count(*) as total,
                  count(*) filter (where defect_count > 0) as with_defects,
                  count(*) filter (where ai_status = 'flagged') as ai_flagged,
                  count(*) filter (where ai_status = 'clear') as ai_clear,
                  count(*) filter (where ai_status = 'over_budget') as ai_waiting,
                  count(*) filter (where review_status = 'approved') as approved,
                  count(*) filter (where review_status = 'rejected') as rejected
           from inspections where company_id = %s and source = 'kaido' and submitted_at > {window}""",
        (company["id"], since),
    )
    open_review = one(
        "select count(*) as n from inspections where company_id = %s and source = 'kaido' and review_status is null",
        (company["id"],),
    )["n"]
    unsigned = one(
        """select count(*) as n from inspections where company_id = %s and defect_count > 0 and certified_at is null""",
        (company["id"],),
    )["n"]
    spend = one(
        f"""select coalesce(sum(cost_usd), 0) as usd, count(*) as calls from ai_usage
            where created_at > {window}""",
        (since,),
    )
    capped_days = rows(
        f"""select date_trunc('day', created_at) as day from ai_usage where created_at > {window}
            group by 1 having sum(cost_usd) >= %s""",
        (since, config.AI_DAILY_USD),
    )
    lines = [f"<b>Twice-weekly summary</b> · {escape(company['name'])}", ""]
    saved = [f"{escape(os.path.basename(path))} ({_size(path)})" for path in backups if _size(path)]
    lines.append("<b>Backup</b>")
    lines.append("• Saved: " + ", ".join(saved) if saved else "• ⚠️ Backup files are missing — check the server.")
    lines.append("")
    lines.append("<b>PTIs since the last summary</b>")
    lines.append(f"• {stats['total']} sent, {stats['with_defects']} with defects")
    lines.append(f"• AI: {stats['ai_clear']} clear, {stats['ai_flagged']} flagged"
                 + (f", {stats['ai_waiting']} waiting on the daily cap" if stats["ai_waiting"] else ""))
    lines.append(f"• Reviewed: {stats['approved']} approved, {stats['rejected']} rejected")
    lines.append(f"• Still to review: {open_review} · defects not signed off: {unsigned}")
    lines.append("")
    lines.append("<b>AI spend</b> (all of Kaido)")
    lines.append(f"• ${float(spend['usd']):.2f} over {spend['calls']} calls · cap ${config.AI_DAILY_USD:.2f} a day"
                 + (f" · cap reached on {len(capped_days)} day{'' if len(capped_days) == 1 else 's'}" if capped_days else ""))
    lines += ["", f"{config.APP_URL}/pti?show=review"]
    return "\n".join(lines)


def run(backups):
    sent = []
    for company in rows("select * from companies where status = 'active' order by id"):
        text = build(company, backups)
        chats = company_chats(company["id"], admins_only=True)
        for chat in chats:
            send(chat, text)
        execute("insert into summaries (company_id, recipients, body) values (%s, %s, %s)",
                (company["id"], len(chats), text))
        sent.append((company["name"], len(chats)))
    return sent
