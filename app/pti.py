import io
import uuid
from datetime import datetime, timedelta, timezone
from html import escape

from .config import ROOT, config
from .db import execute, insert, one, rows
from .reminders import company_chats, zone_for
from .security import random_token
from .telegram import send

PHOTO_DIR = ROOT / "uploads" / "pti"
MAX_PHOTOS = 12
PHOTO_EDGE = 1600

SECTIONS = [
    ("In the cab", [
        ("gauges", "Gauges, warning lights, air pressure builds"),
        ("horn", "Horn"),
        ("wipers", "Windshield wipers and washer"),
        ("windshield", "Windshield and windows"),
        ("mirrors", "Mirrors"),
        ("heater_defroster", "Heater and defroster"),
        ("steering", "Steering, free play"),
        ("emergency_equipment", "Fire extinguisher, triangles, spare fuses"),
        ("seat_belt", "Seat belt"),
    ]),
    ("Brakes and air", [
        ("service_brakes", "Service brakes"),
        ("parking_brake", "Parking brake"),
        ("air_lines", "Air lines and glad hands, no leaks"),
        ("trailer_brakes", "Trailer brake connections"),
    ]),
    ("Engine compartment", [
        ("fluid_levels", "Oil, coolant, power steering levels"),
        ("belts_hoses", "Belts and hoses"),
        ("leaks", "No oil, fuel or coolant leaks"),
    ]),
    ("Outside the truck", [
        ("lights", "Headlights, turn signals, brake lights, markers"),
        ("reflectors", "Reflectors and reflective tape"),
        ("tires", "Tires: tread, inflation, damage"),
        ("wheels_rims", "Wheels, rims, lug nuts"),
        ("suspension", "Springs, airbags, shocks"),
        ("exhaust", "Exhaust system"),
        ("frame_body", "Frame, body, doors"),
        ("fuel_tanks", "Fuel tanks and caps"),
    ]),
    ("Coupling and trailer", [
        ("fifth_wheel", "Fifth wheel, kingpin, locking jaws"),
        ("coupling", "Coupling devices, safety chains"),
        ("trailer_lights", "Trailer lights"),
        ("trailer_tires", "Trailer tires, wheels, rims"),
        ("landing_gear", "Landing gear"),
        ("trailer_doors", "Trailer doors, roof, seal"),
    ]),
]
ITEMS = {key: label for _section, entries in SECTIONS for key, label in entries}
KINDS = {"pre_trip": "Pre-trip", "post_trip": "Post-trip", "mechanic": "Mechanic", "unspecified": "Inspection"}
CERTIFICATIONS = {"repaired": "Repaired", "not_needed": "Repair not needed for safe operation"}


def item_label(key):
    return ITEMS.get(key) or (key or "").replace("_", " ").capitalize()


def truck_by_token(token):
    if not token or len(token) < 20:
        return None
    return one(
        """select t.*, c.name as company_name, c.timezone as company_timezone, d.name as driver_name
           from trucks t join companies c on c.id = t.company_id
           left join drivers d on d.id = t.driver_id
           where t.pti_token = %s and c.status = 'active' and t.status <> 'sold'""",
        (token,),
    )


def ensure_token(truck):
    if truck.get("pti_token"):
        return truck["pti_token"]
    token = random_token(24)
    execute("update trucks set pti_token = %s where id = %s and pti_token is null", (token, truck["id"]))
    row = one("select pti_token from trucks where id = %s", (truck["id"],))
    return row["pti_token"]


def new_token(truck_id):
    token = random_token(24)
    execute("update trucks set pti_token = %s, updated_at = now() where id = %s", (token, truck_id))
    return token


def link_for(token):
    return f"{config.APP_URL}/pti/{token}"


def qr_svg(url):
    import segno
    out = io.BytesIO()
    segno.make(url, error="m").save(out, kind="svg", scale=6, border=2, xmldecl=False, svgns=True, omitsize=True)
    return out.getvalue().decode()


def previous_with_defects(truck_id):
    last = one(
        "select * from inspections where truck_id = %s order by submitted_at desc limit 1",
        (truck_id,),
    )
    if not last or not last["defect_count"]:
        return None
    return last


def defects_of(inspection):
    out = []
    for key, value in (inspection.get("results") or {}).items():
        if isinstance(value, dict) and value.get("state") == "defect":
            out.append({"key": key, "label": item_label(key), "note": value.get("note") or ""})
    return out


def save_photo(company_id, inspection_id, item, upload):
    from PIL import Image, ImageOps
    try:
        image = Image.open(upload.stream)
        image = ImageOps.exif_transpose(image)
        image.thumbnail((PHOTO_EDGE, PHOTO_EDGE))
        image = image.convert("RGB")
    except Exception:
        return False
    folder = PHOTO_DIR / str(company_id)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.jpg"
    image.save(folder / name, "JPEG", quality=82)
    execute(
        """insert into inspection_photos (company_id, inspection_id, item, path)
           values (%s, %s, %s, %s)""",
        (company_id, inspection_id, item if item in ITEMS else None, f"{company_id}/{name}"),
    )
    return True


def photo_file(photo):
    path = (PHOTO_DIR / photo["path"]).resolve()
    if PHOTO_DIR.resolve() not in path.parents or not path.is_file():
        return None
    return path


def create(truck, values, created_by=None, ip=None):
    defects = sum(1 for value in values["results"].values() if value.get("state") == "defect")
    return insert(
        """insert into inspections (company_id, truck_id, driver_id, driver_name, kind, source, odometer,
             results, defect_count, safe_to_drive, notes, signed_name, reviewed_previous_id,
             submitted_ip, created_by)
           values (%s, %s, %s, %s, %s, 'kaido', %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s) returning *""",
        (
            truck["company_id"], truck["id"], values.get("driver_id"), values.get("driver_name"),
            values["kind"], values.get("odometer"), _json(values["results"]), defects,
            values.get("safe_to_drive"), values.get("notes"), values.get("signed_name"),
            values.get("reviewed_previous_id"), ip, created_by,
        ),
    )


def _json(value):
    import json
    return json.dumps(value)


def alert(inspection_id):
    item = one(
        """select i.*, t.unit_number, t.location, c.name as company_name
           from inspections i join trucks t on t.id = i.truck_id join companies c on c.id = i.company_id
           where i.id = %s and i.alerted_at is null and i.submitted_at > now() - interval '6 hours'""",
        (inspection_id,),
    )
    if not item or not item["defect_count"]:
        return 0
    found = defects_of(item)
    lines = [
        f"<b>{'UNSAFE — ' if item['safe_to_drive'] is False else ''}PTI defect</b> · {escape(item['company_name'])}",
        f"Unit {escape(item['unit_number'])} · {KINDS.get(item['kind'], 'Inspection')} by {escape(item['driver_name'] or 'unknown driver')}",
    ]
    for defect in found[:8]:
        lines.append(f"• {escape(defect['label'])}" + (f" — {escape(defect['note'][:120])}" if defect["note"] else ""))
    if len(found) > 8:
        lines.append(f"  and {len(found) - 8} more")
    if item["location"]:
        lines.append(f"Near {escape(item['location'])}")
    lines += ["", f"{config.APP_URL}/pti/report/{item['id']}"]
    text = "\n".join(lines)
    for chat in company_chats(item["company_id"]):
        send(chat, text)
    execute("update inspections set alerted_at = now() where id = %s", (inspection_id,))
    return 1


def certify(company_id, inspection_id, certification, note, name, user_id):
    return execute(
        """update inspections set certification = %s, certified_note = %s, certified_name = %s,
             certified_by = %s, certified_at = now()
           where id = %s and company_id = %s and defect_count > 0 and certified_at is null""",
        (certification, note, name, user_id, inspection_id, company_id),
    )


def local_day_bounds(company, day=None):
    tz = zone_for(company.get("timezone"))
    day = day or datetime.now(tz).date()
    start = datetime.combine(day, datetime.min.time(), tzinfo=tz)
    return day, start, start + timedelta(days=1)


def today_board(company, day=None):
    day, start, end = local_day_bounds(company, day)
    trucks = rows(
        """select t.id, t.unit_number, t.status, d.name as driver_name,
                  (select max(miles) - min(miles) from odometer_readings o
                    where o.truck_id = t.id and o.read_at >= %s and o.read_at < %s) as moved,
                  (select count(*) from inspections i where i.truck_id = t.id and i.kind = 'pre_trip'
                    and i.submitted_at >= %s and i.submitted_at < %s) as pre_trips,
                  (select max(i.submitted_at) from inspections i where i.truck_id = t.id) as last_at
           from trucks t left join drivers d on d.id = t.driver_id
           where t.company_id = %s and not t.is_outside and t.status <> 'sold'
           order by lower(t.unit_number)""",
        (start, end, start, end, company["id"]),
    )
    for truck in trucks:
        truck["moved"] = truck["moved"] or 0
        truck["missing"] = truck["moved"] >= 10 and not truck["pre_trips"]
    return day, trucks


def open_defects(company_id):
    return rows(
        """select i.*, t.unit_number from inspections i join trucks t on t.id = i.truck_id
           where i.company_id = %s and i.defect_count > 0 and i.certified_at is null
           order by i.submitted_at desc""",
        (company_id,),
    )


def store_samsara(company_id, truck_id, dvir, defects):
    kind = {"preTrip": "pre_trip", "postTrip": "post_trip", "mechanic": "mechanic"}.get(dvir.get("type"), "unspecified")
    results = {}
    for number, defect in enumerate(defects, 1):
        results[f"samsara_{number}"] = {
            "state": "defect",
            "note": " — ".join(part for part in [defect.get("defectType") or "", defect.get("comment") or ""] if part),
            "resolved": bool(defect.get("isResolved")),
        }
    signature = dvir.get("authorSignature") or {}
    signer = signature.get("signatoryUser") or {}
    status = dvir.get("safetyStatus")
    resolved = status == "resolved" or (defects and all(d.get("isResolved") for d in defects))
    submitted = dvir.get("dvirSubmissionTime") or dvir.get("updatedAtTime")
    odometer = dvir.get("odometerMeters")
    row = insert(
        """insert into inspections (company_id, truck_id, driver_name, kind, source, external_id, odometer, results,
             defect_count, safe_to_drive, notes, signed_name, submitted_at, raw, certification, certified_note,
             certified_name, certified_at)
           values (%s, %s, %s, %s, 'samsara', %s, %s, %s::jsonb, %s, %s, %s, %s, coalesce(%s::timestamptz, now()), %s::jsonb,
                   %s, %s, %s, %s)
           on conflict (company_id, source, external_id) do update set
             results = excluded.results, defect_count = excluded.defect_count, safe_to_drive = excluded.safe_to_drive,
             notes = excluded.notes, raw = excluded.raw,
             certification = coalesce(inspections.certification, excluded.certification),
             certified_note = coalesce(inspections.certified_note, excluded.certified_note),
             certified_name = coalesce(inspections.certified_name, excluded.certified_name),
             certified_at = coalesce(inspections.certified_at, excluded.certified_at)
           returning id, (xmax = 0) as inserted""",
        (
            company_id, truck_id, signer.get("name"), kind, str(dvir.get("id")),
            int(round(float(odometer) / 1609.344)) if odometer else None, _json(results), len(defects),
            None if status in (None, "unknown") else status != "unsafe", dvir.get("mechanicNotes"),
            signer.get("name"), submitted, _json(dvir),
            "repaired" if resolved and defects else None,
            "Resolved in Samsara" if resolved and defects else None,
            "Samsara" if resolved and defects else None,
            datetime.now(timezone.utc) if resolved and defects else None,
        ),
    )
    return row
