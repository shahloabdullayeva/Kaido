import secrets
from datetime import date
from html import escape
from pathlib import Path

from . import config
from .db import execute, one, rows
from .logs import get
from .reminders import company_chats
from .telegram import send

log = get("documents")

ROOT = Path(__file__).resolve().parent.parent
FILE_DIR = ROOT / "uploads" / "documents"
ALLOWED = {"pdf": "application/pdf", "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
           "heic": "image/heic", "webp": "image/webp"}
STAGES = [30, 14, 7, 1, 0]
SOON_DAYS = 30

KINDS = {
    "driver": [
        ("cdl", "CDL"), ("medical", "Medical card"), ("mvr", "MVR (yearly)"), ("clearinghouse", "Clearinghouse query (yearly)"),
        ("drug_test", "Drug test"), ("hazmat", "Hazmat endorsement"), ("twic", "TWIC card"), ("passport", "Passport"),
        ("application", "Employment application"), ("other", "Other"),
    ],
    "truck": [
        ("registration", "Registration (cab card)"), ("insurance", "Insurance card"), ("annual", "Annual DOT inspection"),
        ("ifta_decal", "IFTA decal / licence copy"), ("hvut", "Form 2290 (HVUT)"), ("permit", "State permit (NY, KY, NM, OR)"),
        ("lease", "Lease agreement"), ("title", "Title"), ("other", "Other"),
    ],
    "trailer": [
        ("registration", "Registration"), ("annual", "Annual DOT inspection"), ("insurance", "Insurance"),
        ("lease", "Lease agreement"), ("title", "Title"), ("other", "Other"),
    ],
    "company": [
        ("mc_authority", "MC authority"), ("ucr", "UCR (yearly)"), ("boc3", "BOC-3"), ("insurance_policy", "Insurance policy"),
        ("ifta_licence", "IFTA licence"), ("irp", "IRP account"), ("mcs150", "MCS-150 update (every 2 years)"),
        ("w9", "W-9"), ("other", "Other"),
    ],
}
OWNERS = {"driver": "Driver", "truck": "Truck", "trailer": "Trailer", "company": "Company"}


def label(owner, kind):
    return dict(KINDS.get(owner, [])).get(kind, kind.replace("_", " ").capitalize())


def days_left(doc):
    return (doc["expires_on"] - date.today()).days if doc.get("expires_on") else None


def tone(doc):
    left = days_left(doc)
    if left is None:
        return "muted"
    return "bad" if left < 0 else ("warn" if left <= SOON_DAYS else "ok")


def status_text(doc):
    left = days_left(doc)
    if left is None:
        return "No expiry"
    if left < 0:
        return f"Expired {abs(left)} day{'s' if abs(left) != 1 else ''} ago"
    if left == 0:
        return "Expires today"
    return f"{left} day{'s' if left != 1 else ''} left"


LIST_SQL = """select d.*, dr.name as driver_name, t.unit_number as truck_unit, tr.unit_number as trailer_unit
              from documents d
              left join drivers dr on dr.id = d.driver_id
              left join trucks t on t.id = d.truck_id
              left join trailers tr on tr.id = d.trailer_id"""


def shape(doc):
    doc = dict(doc)
    doc["label"] = doc["title"] or label(doc["owner"], doc["kind"])
    doc["tone"] = tone(doc)
    doc["status"] = status_text(doc)
    doc["left"] = days_left(doc)
    if doc["owner"] == "driver":
        doc["who"], doc["href"] = doc["driver_name"], f"/drivers/{doc['driver_id']}"
    elif doc["owner"] == "truck":
        doc["who"], doc["href"] = f"Unit {doc['truck_unit']}", f"/trucks/{doc['truck_id']}"
    elif doc["owner"] == "trailer":
        doc["who"], doc["href"] = f"Trailer {doc['trailer_unit']}", f"/trailers/{doc['trailer_id']}"
    else:
        doc["who"], doc["href"] = "Company", "/documents?owner=company"
    return doc


def for_owner(company_id, owner, owner_id=None):
    column = {"driver": "driver_id", "truck": "truck_id", "trailer": "trailer_id"}.get(owner)
    clause = f" and d.{column} = %s" if column else ""
    params = (company_id, owner) + ((owner_id,) if column else ())
    found = rows(LIST_SQL + f" where d.company_id = %s and d.owner = %s{clause} order by d.expires_on nulls last, d.id", params)
    return [shape(d) for d in found]


def listing(company_id, owner="all", status="all", kind="all"):
    clause, params = "", [company_id]
    if owner != "all":
        clause += " and d.owner = %s"
        params.append(owner)
    if kind != "all":
        clause += " and d.kind = %s"
        params.append(kind)
    if status == "expired":
        clause += " and d.expires_on < current_date"
    elif status == "soon":
        clause += f" and d.expires_on between current_date and current_date + {SOON_DAYS}"
    elif status == "ok":
        clause += f" and (d.expires_on > current_date + {SOON_DAYS} or d.expires_on is null)"
    found = rows(LIST_SQL + f" where d.company_id = %s{clause} order by d.expires_on nulls last, d.id limit 1000", tuple(params))
    return [shape(d) for d in found]


def missing(company_id):
    out = []
    for driver in rows("select id, name from drivers where company_id = %s and status = 'active' order by name", (company_id,)):
        have = {r["kind"] for r in rows("select kind from documents where driver_id = %s", (driver["id"],))}
        lacks = [label("driver", k) for k in ("cdl", "medical") if k not in have]
        if lacks:
            out.append({"who": driver["name"], "href": f"/drivers/{driver['id']}", "lacks": lacks})
    for truck in rows("select id, unit_number from trucks where company_id = %s and status = 'active' order by lower(unit_number)",
                      (company_id,)):
        have = {r["kind"] for r in rows("select kind from documents where truck_id = %s", (truck["id"],))}
        lacks = [label("truck", k) for k in ("registration", "insurance", "annual") if k not in have]
        if lacks:
            out.append({"who": f"Unit {truck['unit_number']}", "href": f"/trucks/{truck['id']}", "lacks": lacks})
    return out


def save_file(company_id, upload):
    if not upload or not upload.filename:
        return None
    ext = upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
    if ext not in ALLOWED:
        raise ValueError("Use a PDF or a photo (JPG, PNG, HEIC, WEBP).")
    folder = FILE_DIR / str(company_id)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{secrets.token_hex(12)}.{ext}"
    upload.save(folder / name)
    return {"file_path": f"{company_id}/{name}", "file_name": upload.filename[:200], "content_type": ALLOWED[ext]}


def file_of(doc):
    if not doc or not doc.get("file_path"):
        return None
    path = (FILE_DIR / doc["file_path"]).resolve()
    if FILE_DIR.resolve() not in path.parents or not path.is_file():
        return None
    return path


def remove_file(doc):
    path = file_of(doc)
    if path:
        path.unlink(missing_ok=True)


def stage_of(left):
    for stage in reversed(STAGES):
        if left <= stage:
            return stage
    return None


def message(doc, office):
    left = doc["left"]
    when = "expired today" if left == 0 else (f"expired {abs(left)} days ago" if left < 0 else f"expires in {left} day{'s' if left != 1 else ''}")
    head = f"<b>{escape(doc['label'])}</b> {when}"
    lines = [head, f"{escape(doc['who'] or '')} · {doc['expires_on'].strftime('%d %b %Y')}"]
    if office:
        lines.append(f"{config.APP_URL}{doc['href']}")
    return "\n".join(lines)


def run():
    sent = 0
    for doc in rows(LIST_SQL + """ join companies c on c.id = d.company_id
                                   where c.status = 'active' and c.document_alerts_enabled and d.expires_on is not null
                                     and d.expires_on <= current_date + 30"""):
        doc = shape(doc)
        stage = stage_of(doc["left"])
        if stage is None or (doc["notified_stage"] is not None and doc["notified_stage"] <= stage):
            continue
        execute("update documents set notified_stage = %s where id = %s", (stage, doc["id"]))
        for chat in company_chats(doc["company_id"]):
            send(chat, message(doc, True))
        if doc["owner"] == "driver" and stage in (30, 7, 0):
            truck = one("select telegram_chat_id from trucks where driver_id = %s and status = 'active' and telegram_chat_id is not null",
                        (doc["driver_id"],))
            if truck:
                send(truck["telegram_chat_id"], message(doc, False))
        sent += 1
    return sent
