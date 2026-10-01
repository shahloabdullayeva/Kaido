import base64
import io
import json
from html import escape
from typing import List, Literal

from pydantic import BaseModel

from . import advisor, pti
from .config import config
from .db import execute, one, rows
from .logs import get
from .reminders import company_chats
from .telegram import send

log = get("pti-ai")

MODEL = config.AI_PHOTO_MODEL
PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-4-5": (1.0, 5.0)}
EDGE = 1024
MAX_IMAGES = 12

SYSTEM = (
    "You check photos a truck driver took during a DOT pre-trip or post-trip inspection (FMCSA 396.11/396.13) "
    "of a Class 8 tractor and trailer. Each photo is labelled with the checklist section or item it is meant "
    "to show and what the driver marked: OK or Defect. For every photo decide: "
    "'ok' if it shows that part and nothing looks wrong; "
    "'issue' if you can see a likely problem (flat or low tire, worn tread, sidewall damage, missing lug nuts, "
    "leaks, broken or out lights, cracked glass or mirror, damaged air lines, hanging parts, body damage, "
    "warning lights on the dash, and similar); "
    "'wrong_photo' if it does not show the labelled part at all (ground, sky, a different vehicle, a screen, "
    "a photo of a photo) — drivers sometimes do this to skip the check; "
    "'unclear' if it is too dark, blurry or far to judge. "
    "Only report what is visible. Do not guess about things you cannot see, and never call something "
    "unsafe unless the photo shows it. Notes are for a fleet manager: plain words, under 20 words each. "
    "Set 'summary' to one sentence for the manager. Set 'needs_attention' to true when any photo is "
    "'issue' on something the driver marked OK, or 'wrong_photo'."
)


class PhotoFinding(BaseModel):
    photo: int
    verdict: Literal["ok", "issue", "wrong_photo", "unclear"]
    note: str


class PhotoReview(BaseModel):
    findings: List[PhotoFinding]
    summary: str
    needs_attention: bool


def available():
    return advisor.available()


def _jpeg_b64(path):
    from PIL import Image
    image = Image.open(path)
    image.thumbnail((EDGE, EDGE))
    out = io.BytesIO()
    image.convert("RGB").save(out, "JPEG", quality=80)
    return base64.standard_b64encode(out.getvalue()).decode()


def _cost(usage):
    per_input, per_output = PRICES.get(MODEL, (5.0, 25.0))
    return (usage.input_tokens * per_input + usage.output_tokens * per_output) / 1_000_000


def _photos(inspection):
    results = inspection["results"] or {}
    photos = rows(
        "select * from inspection_photos where inspection_id = %s and kind = 'photo' order by id",
        (inspection["id"],),
    )
    picked = []
    for photo in photos:
        path = pti.photo_file(photo)
        if not path:
            continue
        key = photo["item"] or ""
        state = (results.get(key) or {}).get("state")
        marked = {"defect": "Defect", "ok": "OK", "na": "N/A"}.get(state, "section photo, items inside marked "
                  + ("with defects" if any((results.get(k) or {}).get("state") == "defect"
                                           for k in _section_items(key)) else "OK"))
        picked.append({"photo": photo, "path": path, "label": pti.media_label(key) if key else "Other photo",
                       "marked": marked, "note": (results.get(key) or {}).get("note")})
    return picked[:MAX_IMAGES]


def _section_items(key):
    for number, (_title, entries) in enumerate(pti.SECTIONS, 1):
        if key == f"section_{number}":
            return [item for item, _label in entries]
    return []


def review(inspection_id):
    inspection = one("select * from inspections where id = %s", (inspection_id,))
    if not inspection or inspection["ai_checked_at"]:
        return None
    picked = _photos(inspection)
    if not picked or not available():
        execute("update inspections set ai_status = %s, ai_checked_at = now() where id = %s",
                ("no_photos" if not picked else "no_key", inspection_id))
        return None
    if advisor.over_budget():
        execute("update inspections set ai_status = 'over_budget' where id = %s", (inspection_id,))
        return None
    content = []
    for number, item in enumerate(picked, 1):
        line = f"Photo {number}: {item['label']}. Driver marked: {item['marked']}."
        if item["note"]:
            line += f" Driver's note: {item['note']}"
        content.append({"type": "text", "text": line})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                     "data": _jpeg_b64(item["path"])}})
    content.append({"type": "text", "text": "Review every photo."})
    try:
        import anthropic
        response = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY).messages.parse(
            model=MODEL,
            max_tokens=4000,
            system=SYSTEM,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": content}],
            output_format=PhotoReview,
        )
    except Exception as err:
        log.warning("photo review for inspection %s failed: %s", inspection_id, err)
        execute("update inspections set ai_status = 'failed' where id = %s", (inspection_id,))
        return None
    execute(
        "insert into ai_usage (model, input_tokens, output_tokens, cost_usd) values (%s, %s, %s, %s)",
        (MODEL, response.usage.input_tokens, response.usage.output_tokens, _cost(response.usage)),
    )
    parsed = response.parsed_output
    if response.stop_reason == "refusal" or parsed is None:
        execute("update inspections set ai_status = 'failed', ai_checked_at = now() where id = %s", (inspection_id,))
        return None
    findings = []
    for finding in parsed.findings:
        if 1 <= finding.photo <= len(picked):
            item = picked[finding.photo - 1]
            findings.append({"photo_id": item["photo"]["id"], "label": item["label"], "marked": item["marked"],
                             "verdict": finding.verdict, "note": finding.note})
    result = {"summary": parsed.summary, "needs_attention": parsed.needs_attention, "findings": findings,
              "model": MODEL}
    execute(
        """update inspections set ai_status = %s, ai_result = %s::jsonb, ai_checked_at = now() where id = %s""",
        ("flagged" if parsed.needs_attention else "clear", json.dumps(result), inspection_id),
    )
    if parsed.needs_attention:
        _alert(inspection, result)
    return result


def _alert(inspection, result):
    truck = one("select unit_number from trucks where id = %s", (inspection["truck_id"],))
    flagged = [f for f in result["findings"] if f["verdict"] in ("issue", "wrong_photo")]
    lines = [f"<b>AI photo check</b> · Unit {escape(truck['unit_number'] if truck else '?')}",
             f"{pti.KINDS.get(inspection['kind'], 'Inspection')} by {escape(inspection['driver_name'] or 'driver')}",
             escape(result["summary"])]
    for finding in flagged[:8]:
        word = "wrong photo" if finding["verdict"] == "wrong_photo" else "possible issue"
        lines.append(f"• {escape(finding['label'])} ({word}, driver marked {escape(finding['marked'])}): {escape(finding['note'])}")
    lines += ["", f"{config.APP_URL}/pti/report/{inspection['id']}"]
    for chat in company_chats(inspection["company_id"]):
        send(chat, "\n".join(lines))


def run_pending(limit=5):
    pending = rows(
        """select id from inspections where source = 'kaido' and ai_checked_at is null
             and coalesce(ai_status, '') not in ('failed')
             and submitted_at > now() - interval '2 days'
           order by submitted_at limit %s""",
        (limit,),
    )
    done = 0
    for row in pending:
        if review(row["id"]) is not None:
            done += 1
    return done
