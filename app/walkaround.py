import base64
import io
import json
import uuid
from datetime import datetime, timedelta, timezone
from html import escape
from typing import List, Literal, Optional

from pydantic import BaseModel

from . import advisor, pti
from .config import config
from .db import execute, insert, one, rows
from .fuel import haversine
from .logs import get

log = get("walkaround")

MODEL = config.AI_PHOTO_MODEL
PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.1, 0.5)}
LANGS = ("en", "ru", "uz")
ARROWS = ("up", "left", "right", "down", "none")
CHECK_EDGE = 768
FRAME_EDGE = 1280
MAX_CHECKS = 60
MAX_FRAMES = 40
MAX_FRAME_BYTES = 8 * 1024 * 1024
MAX_VOICE_BYTES = 15 * 1024 * 1024
OLD_MEDIA_HOURS = 4
MISMATCH_MILES = 1.0
TRUCK_FIX_HOURS = 3
FLAG_TEXT = {
    "uploaded": "Uploaded",
    "old_media": "Old media",
    "location_mismatch": "Location mismatch",
    "no_metadata": "No metadata",
    "no_gps": "No phone location",
}

DEFAULT_STEPS = [
    {"key": "front", "arrow": "up", "look": "the front of a semi truck with headlights on, bumper, grille and windshield",
     "title": {"en": "Front of the truck", "ru": "Перед грузовика", "uz": "Mashinaning old qismi"},
     "say": {"en": "Stand in front of the truck with the lights on. Show the whole front.",
             "ru": "Встаньте перед грузовиком с включёнными фарами. Покажите весь перед.",
             "uz": "Chiroqlarni yoqib, mashina oldida turing. Butun old qismini ko'rsating."}},
    {"key": "left_steer", "arrow": "left", "look": "the driver side front steer tire and wheel of a truck",
     "title": {"en": "Left steer tire", "ru": "Левое переднее колесо", "uz": "Chap old g'ildirak"},
     "say": {"en": "Walk to the driver side front tire. Show the whole tire and wheel.",
             "ru": "Подойдите к переднему колесу со стороны водителя. Покажите всё колесо и диск.",
             "uz": "Haydovchi tomonidagi old g'ildirakka boring. G'ildirak va diskni to'liq ko'rsating."}},
    {"key": "left_side", "arrow": "left", "look": "the driver side of a tractor: fuel tank, steps and the drive axle tires",
     "title": {"en": "Left side and drive tires", "ru": "Левая сторона и ведущие колёса", "uz": "Chap tomon va yetakchi g'ildiraklar"},
     "say": {"en": "Walk down the driver side. Show the fuel tank and the drive tires.",
             "ru": "Пройдите вдоль стороны водителя. Покажите бак и ведущие колёса.",
             "uz": "Haydovchi tomoni bo'ylab yuring. Yoqilg'i bakini va yetakchi g'ildiraklarni ko'rsating."}},
    {"key": "left_trailer", "arrow": "left", "look": "the trailer tires and wheels on the driver side, or the rear of the tractor if there is no trailer",
     "title": {"en": "Left trailer tires", "ru": "Левые колёса прицепа", "uz": "Tirkamaning chap g'ildiraklari"},
     "say": {"en": "Keep walking. Show the trailer tires on the driver side.",
             "ru": "Идите дальше. Покажите колёса прицепа со стороны водителя.",
             "uz": "Yurishda davom eting. Haydovchi tomonidagi tirkama g'ildiraklarini ko'rsating."}},
    {"key": "rear", "arrow": "down", "look": "the rear of a trailer (doors, bumper, tail lights) or the rear of the tractor, with lights on",
     "title": {"en": "Rear with lights", "ru": "Задняя часть с фонарями", "uz": "Orqa qism va chiroqlar"},
     "say": {"en": "At the back, show the doors and the lights on.",
             "ru": "Сзади покажите двери и включённые фонари.",
             "uz": "Orqada eshiklarni va yoniq chiroqlarni ko'rsating."}},
    {"key": "right_side", "arrow": "right", "look": "the passenger side of the truck or trailer with its tires",
     "title": {"en": "Right side tires", "ru": "Колёса правой стороны", "uz": "O'ng tomon g'ildiraklari"},
     "say": {"en": "Walk up the passenger side. Show the trailer and drive tires.",
             "ru": "Пройдите вдоль пассажирской стороны. Покажите колёса прицепа и ведущие колёса.",
             "uz": "Yo'lovchi tomoni bo'ylab yuring. Tirkama va yetakchi g'ildiraklarni ko'rsating."}},
    {"key": "right_steer", "arrow": "right", "look": "the passenger side front steer tire and wheel of a truck",
     "title": {"en": "Right steer tire", "ru": "Правое переднее колесо", "uz": "O'ng old g'ildirak"},
     "say": {"en": "Show the passenger side front tire and wheel.",
             "ru": "Покажите переднее колесо и диск со стороны пассажира.",
             "uz": "Yo'lovchi tomonidagi old g'ildirak va diskni ko'rsating."}},
    {"key": "dash", "arrow": "none", "look": "the instrument cluster of a running truck: gauges, warning lights and the odometer",
     "title": {"en": "Dash, engine running", "ru": "Приборная панель, двигатель запущен", "uz": "Asboblar paneli, dvigatel ishlayapti"},
     "say": {"en": "Get in, start the engine, and show the dash with the odometer.",
             "ru": "Сядьте в кабину, заведите двигатель и покажите приборную панель с одометром.",
             "uz": "Kabinaga chiqing, dvigatelni yoqing va odometr bilan asboblar panelini ko'rsating."}},
]


def steps_for(company_id):
    row = one("select walkaround_steps from companies where id = %s", (company_id,))
    steps = (row or {}).get("walkaround_steps") or DEFAULT_STEPS
    return [step for step in steps if step.get("key")]


def step_title(steps, key):
    for step in steps:
        if step["key"] == key:
            return step["title"].get("en") or key
    return "Not matched to a step" if not key else key


def clean_steps(raw):
    steps, seen = [], set()
    for item in raw or []:
        title = {lang: str((item.get("title") or {}).get(lang) or "").strip()[:80] for lang in LANGS}
        if not title["en"]:
            continue
        key = str(item.get("key") or "").strip().lower()[:40] or "step"
        base, n = key, 2
        while key in seen:
            key, n = f"{base}_{n}", n + 1
        seen.add(key)
        say = {lang: str((item.get("say") or {}).get(lang) or "").strip()[:300] for lang in LANGS}
        for lang in LANGS:
            title[lang] = title[lang] or title["en"]
            say[lang] = say[lang] or say["en"] or title[lang]
        steps.append({"key": key, "arrow": item.get("arrow") if item.get("arrow") in ARROWS else "none",
                      "look": str(item.get("look") or title["en"]).strip()[:300], "title": title, "say": say})
    return steps[:20]


def session_for(truck, key):
    if not key or len(key) < 16:
        return None
    return one("select * from walk_sessions where key = %s and truck_id = %s", (key, truck["id"]))


def _num(value, low, high):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if low <= number <= high else None


def _moment(value):
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def start(truck, form, ip):
    key = (form.get("key") or "").strip()
    if not (16 <= len(key) <= 64) or not key.isalnum():
        return None
    found = one("select * from walk_sessions where key = %s", (key,))
    if found:
        return found if found["truck_id"] == truck["id"] else None
    driver_id = None
    driver_name = (form.get("driver_name") or "").strip()[:120] or truck.get("link_driver_name")
    try:
        picked = int(form.get("driver_id") or 0)
    except ValueError:
        picked = 0
    if not picked and truck.get("link_driver_id") and (not form.get("driver_name")
                                                       or form.get("driver_name").strip().lower() == (truck.get("link_driver_name") or "").lower()):
        picked = truck["link_driver_id"]
    driver = None
    if picked:
        driver = one("select id, name from drivers where id = %s and company_id = %s", (picked, truck["company_id"]))
    elif driver_name:
        driver = one("""select id, name from drivers where company_id = %s and lower(name) = lower(%s)
                        order by (status = 'active') desc limit 1""", (truck["company_id"], driver_name))
    if driver:
        driver_id, driver_name = driver["id"], driver["name"]
    try:
        meta = json.loads(form.get("meta") or "{}")
    except ValueError:
        meta = {}
    return insert(
        """insert into walk_sessions (key, company_id, truck_id, driver_id, driver_name, kind, mode, lang, latitude,
             longitude, accuracy_m, meta, ip, started_at)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, coalesce(%s, now()))
           on conflict (key) do nothing returning *""",
        (key, truck["company_id"], truck["id"], driver_id, driver_name,
         form.get("kind") if form.get("kind") in ("pre_trip", "post_trip") else "pre_trip",
         form.get("mode") if form.get("mode") in ("live", "upload") else "live",
         form.get("lang") if form.get("lang") in LANGS else "en",
         _num(form.get("lat"), -90, 90), _num(form.get("lon"), -180, 180),
         int(_num(form.get("acc"), 0, 100000) or 0) or None, json.dumps(meta if isinstance(meta, dict) else {}),
         ip, _moment(form.get("started_at"))),
    )


class LiveCheck(BaseModel):
    in_frame: Literal["yes", "no", "unclear"]
    problem: str
    severity: Literal["none", "minor", "major", "critical"]
    odometer: Optional[int]


LIVE_SYSTEM = (
    "You check one camera frame from a truck driver's walkaround inspection. Say whether the frame shows the "
    "part the step asks for: 'yes' if it clearly does, 'no' if it shows something else (ground, sky, cab "
    "interior when outside is asked, another vehicle, a screen), 'unclear' if too dark, blurry or far. "
    "If you can see an obvious problem on that part (flat or low tire, tire damage, missing mudflap, broken or "
    "dark light, body damage, cracked glass, leak, warning lights lit on a dash), describe it in under 12 "
    "plain words in 'problem' and rate 'severity'; otherwise problem is '' and severity 'none'. "
    "Only report what is visible. If it is a dash and the odometer is readable, put the miles in 'odometer', "
    "else null."
)


def available():
    return advisor.available() and not advisor.over_budget()


def _cost(usage):
    per_input, per_output = PRICES.get(MODEL, (5.0, 25.0))
    return (usage.input_tokens * per_input + usage.output_tokens * per_output) / 1_000_000


def _remember(usage):
    execute("insert into ai_usage (model, input_tokens, output_tokens, cost_usd) values (%s, %s, %s, %s)",
            (MODEL, usage.input_tokens, usage.output_tokens, _cost(usage)))
    return _cost(usage)


def _jpeg(data, edge):
    from PIL import Image, ImageOps
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    image.thumbnail((edge, edge))
    out = io.BytesIO()
    image.convert("RGB").save(out, "JPEG", quality=80)
    return out.getvalue()


def live_check(session, step_key, data):
    if session["finished_at"] or session["checks"] >= MAX_CHECKS:
        return {"in_frame": "unknown"}
    if not available():
        return {"in_frame": "unknown"}
    step = next((s for s in steps_for(session["company_id"]) if s["key"] == step_key), None)
    if not step:
        return {"in_frame": "unknown"}
    try:
        image = base64.standard_b64encode(_jpeg(data, CHECK_EDGE)).decode()
    except Exception:
        return {"in_frame": "unknown"}
    execute("update walk_sessions set checks = checks + 1 where id = %s", (session["id"],))
    try:
        import anthropic
        response = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, timeout=20, max_retries=0).messages.parse(
            model=MODEL,
            max_tokens=1500,
            system=LIVE_SYSTEM,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": [
                {"type": "text", "text": f"Step: {step['title']['en']}. It should show {step['look']}."},
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image}},
            ]}],
            output_format=LiveCheck,
        )
    except Exception as err:
        log.warning("live check failed for walk %s: %s", session["id"], err)
        return {"in_frame": "unknown"}
    _remember(response.usage)
    parsed = response.parsed_output
    if response.stop_reason == "refusal" or parsed is None:
        return {"in_frame": "unknown"}
    return parsed.model_dump()


def _photo_dir(company_id):
    folder = pti.PHOTO_DIR / str(company_id)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def save_frame(session, form, upload):
    client_id = (form.get("client_id") or "").strip()[:64]
    if not client_id or not upload:
        return False
    if one("select id from walk_frames where session_id = %s and client_id = %s", (session["id"], client_id)):
        return True
    if one("select count(*) as n from walk_frames where session_id = %s", (session["id"],))["n"] >= MAX_FRAMES:
        return True
    data = upload.stream.read(MAX_FRAME_BYTES + 1)
    if len(data) > MAX_FRAME_BYTES:
        return True
    try:
        jpeg = _jpeg(data, FRAME_EDGE)
    except Exception:
        return True
    name = f"{uuid.uuid4().hex}.jpg"
    (_photo_dir(session["company_id"]) / name).write_bytes(jpeg)
    try:
        check = json.loads(form.get("check") or "null")
    except ValueError:
        check = None
    steps = {s["key"] for s in steps_for(session["company_id"])}
    frame = insert(
        """insert into walk_frames (session_id, client_id, step, path, bytes, taken_at, latitude, longitude, live_check)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb) on conflict (session_id, client_id) do nothing returning *""",
        (session["id"], client_id, form.get("step") if form.get("step") in steps else None,
         f"{session['company_id']}/{name}", len(jpeg), _moment(form.get("taken_at")),
         _num(form.get("lat"), -90, 90), _num(form.get("lon"), -180, 180),
         json.dumps(check) if isinstance(check, dict) else None),
    )
    if frame and session["inspection_id"]:
        _attach(session, frame)
    return True


def save_voice(session, form, upload):
    text = (form.get("text") or "").strip()[:2000]
    if upload:
        data = upload.stream.read(MAX_VOICE_BYTES + 1)
        if 0 < len(data) <= MAX_VOICE_BYTES:
            kind = (upload.mimetype or "audio/webm").split(";")[0]
            suffix = {"audio/mp4": ".m4a", "audio/ogg": ".ogg", "audio/mpeg": ".mp3"}.get(kind, ".webm")
            name = f"{uuid.uuid4().hex}{suffix}"
            (_photo_dir(session["company_id"]) / name).write_bytes(data)
            meta = dict(session["meta"] or {})
            meta["voice"] = {"path": f"{session['company_id']}/{name}", "type": kind, "bytes": len(data)}
            execute("update walk_sessions set meta = %s::jsonb where id = %s", (json.dumps(meta), session["id"]))
    if text:
        meta = dict((one("select meta from walk_sessions where id = %s", (session["id"],)) or {}).get("meta") or {})
        meta["voice_text"] = text
        execute("update walk_sessions set meta = %s::jsonb where id = %s", (json.dumps(meta), session["id"]))
    return True


def _attach(session, frame):
    photo = insert(
        """insert into inspection_photos (company_id, inspection_id, item, step, path, content_type, bytes, taken_at,
             latitude, longitude, live_check)
           values (%s, %s, %s, %s, %s, 'image/jpeg', %s, %s, %s, %s, %s::jsonb) returning id""",
        (session["company_id"], session["inspection_id"], frame["step"], frame["step"], frame["path"], frame["bytes"],
         frame["taken_at"], frame["latitude"], frame["longitude"],
         json.dumps(frame["live_check"]) if frame["live_check"] is not None else None),
    )
    execute("update walk_frames set photo_id = %s where id = %s", (photo["id"], frame["id"]))


def _truck_fix(truck_id, moment):
    point = one(
        """select latitude, longitude, recorded_at from truck_positions where truck_id = %s
             and recorded_at between %s - make_interval(hours => %s) and %s + make_interval(hours => %s)
           order by abs(extract(epoch from recorded_at - %s)) limit 1""",
        (truck_id, moment, TRUCK_FIX_HOURS, moment, TRUCK_FIX_HOURS, moment),
    )
    if point:
        return point
    truck = one("select latitude, longitude, located_at as recorded_at from trucks where id = %s", (truck_id,))
    if truck and truck["latitude"] is not None and truck["recorded_at"] and \
            abs((truck["recorded_at"] - moment).total_seconds()) <= TRUCK_FIX_HOURS * 3600:
        return truck
    return None


def flags_for(session, frames, now):
    flags = []
    distance = None
    if session["mode"] == "upload":
        flags.append("uploaded")
        meta_frames = [f for f in frames if f["taken_at"] or f["latitude"] is not None]
        if not meta_frames:
            flags.append("no_metadata")
        times = [f["taken_at"] for f in frames if f["taken_at"]]
        if times and min(times) < now - timedelta(hours=OLD_MEDIA_HOURS):
            flags.append("old_media")
        for frame in frames:
            if frame["latitude"] is None:
                continue
            fix = _truck_fix(session["truck_id"], frame["taken_at"] or now)
            if fix:
                miles = haversine(frame["latitude"], frame["longitude"], fix["latitude"], fix["longitude"])
                distance = miles if distance is None else max(distance, miles)
    else:
        if session["latitude"] is None:
            flags.append("no_gps")
        else:
            fix = _truck_fix(session["truck_id"], session["started_at"])
            if fix:
                distance = haversine(session["latitude"], session["longitude"], fix["latitude"], fix["longitude"])
    if distance is not None and distance > MISMATCH_MILES:
        flags.append("location_mismatch")
    return flags, distance


def finish(truck, session, form):
    if session["inspection_id"]:
        return session["inspection_id"]
    now = datetime.now(timezone.utc)
    frames = rows("select * from walk_frames where session_id = %s order by id", (session["id"],))
    flags, distance = flags_for(session, frames, now)
    meta = session["meta"] or {}
    odometer = None
    for frame in frames:
        reading = (frame["live_check"] or {}).get("odometer")
        if frame["step"] == "dash" and isinstance(reading, int) and reading > 0:
            odometer = reading
    item = insert(
        """insert into inspections (company_id, truck_id, driver_id, driver_name, kind, source, odometer, results,
             defect_count, notes, signed_name, submitted_ip, mode, media_flags, gps_lat, gps_lon, gps_miles,
             started_at, voice_text, lang)
           values (%s, %s, %s, %s, %s, 'kaido', %s, '{}'::jsonb, 0, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           returning *""",
        (truck["company_id"], truck["id"], session["driver_id"], session["driver_name"], session["kind"],
         odometer or truck.get("odometer"), meta.get("voice_text"), session["driver_name"], session["ip"],
         session["mode"], flags, session["latitude"], session["longitude"],
         round(distance, 2) if distance is not None else None, session["started_at"], meta.get("voice_text"),
         session["lang"]),
    )
    execute("update walk_sessions set finished_at = now(), inspection_id = %s where id = %s", (item["id"], session["id"]))
    session = {**session, "inspection_id": item["id"]}
    for frame in frames:
        _attach(session, frame)
    voice = meta.get("voice")
    if voice:
        execute(
            """insert into inspection_photos (company_id, inspection_id, item, path, content_type, kind, bytes)
               values (%s, %s, 'voice', %s, %s, 'audio', %s)""",
            (truck["company_id"], item["id"], voice["path"], voice["type"], voice["bytes"]),
        )
    try:
        from . import pti_driver
        pti_driver.completed(item)
    except Exception:
        log.warning("group notice for walkaround %s failed", item["id"], exc_info=True)
    return item["id"]


class FrameFinding(BaseModel):
    frame: int
    step: str
    verdict: Literal["ok", "issue", "wrong_photo", "unclear"]
    severity: Literal["none", "minor", "major", "critical"]
    note: str


class WalkReview(BaseModel):
    findings: List[FrameFinding]
    odometer: Optional[int]
    summary: str
    needs_attention: bool


REVIEW_SYSTEM = (
    "You review the frames of a truck driver's camera walkaround inspection (DOT pre-trip or post-trip of a "
    "Class 8 tractor and trailer). The steps and what each should show are listed first. Each frame says which "
    "step it was taken for, or 'unknown' when the driver uploaded it from the gallery: then set 'step' to the "
    "key of the step it shows best, or 'none'. For a known step, copy its key. For every frame: 'ok' if it shows "
    "that part and nothing looks wrong; 'issue' if you can see a likely problem (flat or low tire, worn tread, "
    "sidewall damage, missing lug nuts, missing mudflap, leaks, broken or dark lights, cracked glass or mirror, "
    "damaged air lines, hanging parts, body damage, warning lights lit on the dash); 'wrong_photo' if it does "
    "not show the part at all (ground, sky, another vehicle, a screen, a photo of a photo); 'unclear' if too "
    "dark, blurry or far. Rate severity: critical = should not be driven (flat or badly damaged tire, "
    "missing lug nuts, red stop warning on the dash), major = fix today, minor = fix soon, none = nothing wrong. "
    "Only report what is visible; never call something unsafe unless the frame shows it. Notes are for a fleet "
    "manager, plain words, under 20 words. Read the odometer from a dash frame if you can, else null. "
    "'summary' is one sentence. 'needs_attention' is true when any frame is 'issue' or 'wrong_photo'."
)
MAX_REVIEW_FRAMES = 20


def review(inspection):
    steps = steps_for(inspection["company_id"])
    photos = rows(
        "select * from inspection_photos where inspection_id = %s and kind = 'photo' order by id",
        (inspection["id"],),
    )
    picked = []
    for photo in photos:
        path = pti.photo_file(photo)
        if path:
            picked.append((photo, path))
    if not picked:
        execute("update inspections set ai_status = 'no_photos', ai_checked_at = now() where id = %s", (inspection["id"],))
        return None
    if not advisor.available():
        execute("update inspections set ai_status = 'no_key', ai_checked_at = now() where id = %s", (inspection["id"],))
        return None
    if advisor.over_budget():
        execute("update inspections set ai_status = 'over_budget' where id = %s", (inspection["id"],))
        return None
    if len(picked) > MAX_REVIEW_FRAMES:
        stride = len(picked) / MAX_REVIEW_FRAMES
        picked = [picked[int(i * stride)] for i in range(MAX_REVIEW_FRAMES)]
    listing = "\n".join(f"- {s['key']}: {s['title']['en']}, should show {s['look']}" for s in steps)
    content = [{"type": "text", "text": "Steps:\n" + listing}]
    for number, (photo, path) in enumerate(picked, 1):
        content.append({"type": "text", "text": f"Frame {number}: step {photo['step'] or 'unknown'}."})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                     "data": base64.standard_b64encode(_jpeg(path.read_bytes(), 1024)).decode()}})
    if inspection["voice_text"]:
        content.append({"type": "text", "text": f"The driver's voice note: {inspection['voice_text']}"})
    content.append({"type": "text", "text": "Review every frame."})
    try:
        import anthropic
        response = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY).messages.parse(
            model=MODEL,
            max_tokens=6000,
            system=REVIEW_SYSTEM,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": content}],
            output_format=WalkReview,
        )
    except Exception as err:
        log.warning("walkaround review %s failed: %s", inspection["id"], err)
        execute("update inspections set ai_status = 'failed' where id = %s", (inspection["id"],))
        return None
    cost = _remember(response.usage)
    parsed = response.parsed_output
    if response.stop_reason == "refusal" or parsed is None:
        execute("update inspections set ai_status = 'failed', ai_checked_at = now() where id = %s", (inspection["id"],))
        return None
    keys = {s["key"] for s in steps}
    findings = []
    for finding in parsed.findings:
        if not 1 <= finding.frame <= len(picked):
            continue
        photo = picked[finding.frame - 1][0]
        step = photo["step"] or (finding.step if finding.step in keys else None)
        if step and not photo["step"]:
            execute("update inspection_photos set step = %s, item = %s where id = %s", (step, step, photo["id"]))
        findings.append({"photo_id": photo["id"], "label": step_title(steps, step), "marked": "walkaround",
                         "step": step, "verdict": finding.verdict, "severity": finding.severity, "note": finding.note})
    covered = {f["step"] for f in findings if f["step"] and f["verdict"] in ("ok", "issue")}
    missing = [s["title"]["en"] for s in steps if s["key"] not in covered]
    result = {"summary": parsed.summary, "needs_attention": parsed.needs_attention, "findings": findings,
              "model": MODEL, "cost_usd": round(cost, 4), "missing_steps": missing, "odometer": parsed.odometer}
    execute("update inspections set ai_status = %s, ai_result = %s::jsonb, ai_checked_at = now() where id = %s",
            ("flagged" if parsed.needs_attention else "clear", json.dumps(result), inspection["id"]))
    if parsed.odometer and parsed.odometer > 0:
        execute("update inspections set odometer = %s where id = %s", (parsed.odometer, inspection["id"]))
    order_id = open_work_order(inspection, result)
    _alert(inspection, result, order_id)
    return result


PRIORITY = {"critical": "urgent", "major": "high", "minor": "medium", "none": "medium"}
RANK = ["none", "minor", "major", "critical"]


def open_work_order(inspection, result):
    flagged = [f for f in result["findings"] if f["verdict"] == "issue"]
    voice = (inspection["voice_text"] or "").strip()
    has_voice = voice or one("select 1 from inspection_photos where inspection_id = %s and kind = 'audio'",
                             (inspection["id"],))
    if inspection["maintenance_order_id"] or not inspection["truck_id"] or not (flagged or has_voice):
        return inspection["maintenance_order_id"]
    worst = max((f["severity"] for f in flagged), key=RANK.index, default="none")
    parts = [f"{f['label']}: {f['note']}" for f in flagged]
    if voice:
        parts.append(f"Driver's voice note: {voice}")
    elif has_voice:
        parts.append("Driver left a voice note (attached)")
    description = ("Walkaround PTI, AI suggestions to check (not a safety guarantee): " + "; ".join(parts))[:2000]
    order = insert(
        """insert into maintenance_orders (company_id, asset_type, truck_id, driver_id, kind, status, priority,
             reported_at, description, odometer)
           values (%s, 'truck', %s, %s, 'repair', 'open', %s, now(), %s, %s) returning id""",
        (inspection["company_id"], inspection["truck_id"], inspection["driver_id"], PRIORITY[worst], description,
         inspection["odometer"]),
    )
    execute("update inspections set maintenance_order_id = %s where id = %s", (order["id"], inspection["id"]))
    _copy_files(inspection, order["id"], [f["photo_id"] for f in flagged])
    from . import work_orders
    work_orders.add_comment(inspection["company_id"], order["id"], "event",
                            f"opened from walkaround PTI #{inspection['id']}", None, "Kaido")
    return order["id"]


def _copy_files(inspection, order_id, photo_ids):
    import shutil
    from . import work_orders
    wanted = rows(
        """select * from inspection_photos where inspection_id = %s and (id = any(%s) or kind = 'audio')
           order by id limit 12""",
        (inspection["id"], photo_ids or [0]),
    )
    folder = work_orders.FILE_DIR / str(inspection["company_id"])
    folder.mkdir(parents=True, exist_ok=True)
    for photo in wanted:
        source = pti.photo_file(photo)
        if not source:
            continue
        name = f"{uuid.uuid4().hex}{source.suffix}"
        shutil.copyfile(source, folder / name)
        label = "voice-note" if photo["kind"] == "audio" else f"pti-{photo['step'] or 'frame'}"
        execute(
            """insert into maintenance_files (company_id, order_id, name, path, content_type, bytes)
               values (%s, %s, %s, %s, %s, %s)""",
            (inspection["company_id"], order_id, f"{label}{source.suffix}", f"{inspection['company_id']}/{name}",
             photo["content_type"], photo["bytes"]),
        )


def _alert(inspection, result, order_id):
    flags = inspection["media_flags"] or []
    flagged = [f for f in result["findings"] if f["verdict"] in ("issue", "wrong_photo")]
    if not flagged and not order_id and not [f for f in flags if f != "uploaded"]:
        return
    truck = one("select unit_number from trucks where id = %s", (inspection["truck_id"],))
    lines = [f"<b>Walkaround PTI</b> · Unit {escape(truck['unit_number'] if truck else '?')}",
             f"{pti.KINDS.get(inspection['kind'], 'Inspection')} by {escape(inspection['driver_name'] or 'driver')}"
             + (" · " + ", ".join(FLAG_TEXT.get(f, f) for f in flags) if flags else ""),
             "AI suggestions to check: " + escape(result["summary"])]
    for finding in flagged[:6]:
        lines.append(f"- {escape(finding['label'])}: {escape(finding['note'])}")
    if inspection["voice_text"]:
        lines.append("Voice note: " + escape(inspection["voice_text"][:300]))
    if order_id:
        lines.append(f"Work order opened: {config.APP_URL}/maintenance/{order_id}")
    lines.append(f"{config.APP_URL}/pti/report/{inspection['id']}")
    from .alert_group import office
    office(inspection["company_id"], "pti", "\n".join(lines))


def run_pending(limit=5):
    pending = rows(
        """select * from inspections where mode <> 'form' and ai_checked_at is null
             and coalesce(ai_status, '') not in ('failed', 'over_budget') and submitted_at > now() - interval '2 days'
             and submitted_at < now() - interval '1 minute' order by submitted_at limit %s""",
        (limit,),
    )
    done = 0
    for item in pending:
        if review(item) is not None:
            done += 1
    return done


def estimate():
    per_check = (CHECK_EDGE * CHECK_EDGE * 0.75 / 750 + 250) / 1e6 * PRICES.get(MODEL, (5, 25))[0] \
        + 120 / 1e6 * PRICES.get(MODEL, (5, 25))[1]
    review_cost = (len(DEFAULT_STEPS) * 1.3 * 1024 * 768 / 750 + 1200) / 1e6 * PRICES.get(MODEL, (5, 25))[0] \
        + 900 / 1e6 * PRICES.get(MODEL, (5, 25))[1]
    typical = per_check * len(DEFAULT_STEPS) * 1.5 + review_cost
    return {"per_check": per_check, "review": review_cost, "typical": typical}
