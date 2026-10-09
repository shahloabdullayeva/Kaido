import uuid

from . import forms
from .config import ROOT
from .db import execute, insert, one, rows

FILE_DIR = ROOT / "uploads" / "maintenance"
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_FILES = 20
MAX_PARTS = 60
PAYMENT_METHODS = [
    ("company_card", "Company card"),
    ("efs", "EFS card / check"),
    ("comdata", "Comdata / Comchek"),
    ("driver_paid", "Driver paid, to reimburse"),
    ("invoice", "Invoice, net terms"),
    ("cash", "Cash"),
    ("warranty", "Warranty, no charge"),
    ("other", "Other"),
]
PAYMENT_LABELS = dict(PAYMENT_METHODS)


def parts_from(form):
    names = form.getlist("part_name")
    numbers = form.getlist("part_number")
    quantities = form.getlist("part_qty")
    prices = form.getlist("part_price")
    parts = []
    for index, raw_name in enumerate(names[:MAX_PARTS]):
        name = forms.text(raw_name, 200)
        number = forms.text(numbers[index] if index < len(numbers) else None, 60)
        quantity = forms.decimal(quantities[index] if index < len(quantities) else None)
        price = forms.decimal(prices[index] if index < len(prices) else None)
        if not name and not number and price is None:
            continue
        quantity = quantity if quantity is not None and quantity > 0 else 1
        parts.append({"name": name or number, "part_number": number, "quantity": round(quantity, 2),
                      "unit_price": round(price, 2) if price is not None and price >= 0 else None})
    return parts


def parts_total(parts):
    return round(sum(part["quantity"] * (part["unit_price"] or 0) for part in parts), 2)


def money_from(form):
    parts = parts_from(form)
    labor = forms.decimal(form.get("labor_cost"))
    tax = forms.decimal(form.get("tax"))
    labor = round(labor, 2) if labor is not None and labor >= 0 else None
    tax = round(tax, 2) if tax is not None and tax >= 0 else None
    itemized = any(part["unit_price"] is not None for part in parts) or labor is not None or tax is not None
    if itemized:
        total = round(parts_total(parts) + (labor or 0) + (tax or 0), 2)
    else:
        total = forms.decimal(form.get("cost"))
    return parts, labor, tax, total


def save_parts(company_id, order_id, parts):
    execute("delete from maintenance_parts where order_id = %s and company_id = %s", (order_id, company_id))
    for position, part in enumerate(parts):
        execute(
            """insert into maintenance_parts (company_id, order_id, position, name, part_number, quantity, unit_price)
               values (%s, %s, %s, %s, %s, %s, %s)""",
            (company_id, order_id, position, part["name"], part["part_number"], part["quantity"], part["unit_price"]),
        )


def parts_of(order_id):
    return rows("select * from maintenance_parts where order_id = %s order by position, id", (order_id,))


def files_of(order_id):
    return rows(
        """select f.*, u.name as uploaded_by_name from maintenance_files f
           left join users u on u.id = f.uploaded_by
           where f.order_id = %s order by f.created_at, f.id""",
        (order_id,),
    )


def sniff(head):
    if head.startswith(b"%PDF-"):
        return ".pdf", "application/pdf"
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp", "image/webp"
    if head[4:8] == b"ftyp" and head[8:12] in (b"heic", b"heix", b"mif1", b"msf1", b"hevc"):
        return ".heic", "image/heic"
    return None


def save_files(company_id, order_id, uploads, user_id):
    saved, problems = [], []
    count = one("select count(*) as n from maintenance_files where order_id = %s", (order_id,))["n"]
    folder = FILE_DIR / str(company_id)
    for upload in uploads:
        if not upload or not upload.filename:
            continue
        label = forms.text(upload.filename.replace("\\", "/").rsplit("/", 1)[-1], 160) or "invoice"
        if count >= MAX_FILES:
            problems.append(f"{label}: this work order already has {MAX_FILES} files.")
            continue
        head = upload.stream.read(16)
        upload.stream.seek(0)
        kind = sniff(head)
        if not kind:
            problems.append(f"{label}: only PDF or photo files (JPG, PNG, WEBP, HEIC) can be attached.")
            continue
        suffix, content_type = kind
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex}{suffix}"
        target = folder / name
        size = 0
        too_big = False
        with open(target, "wb") as out:
            while True:
                block = upload.stream.read(1024 * 1024)
                if not block:
                    break
                size += len(block)
                if size > MAX_FILE_BYTES:
                    too_big = True
                    break
                out.write(block)
        if too_big:
            target.unlink(missing_ok=True)
            problems.append(f"{label}: larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")
            continue
        row = insert(
            """insert into maintenance_files (company_id, order_id, name, path, content_type, bytes, uploaded_by)
               values (%s, %s, %s, %s, %s, %s, %s) returning *""",
            (company_id, order_id, label, f"{company_id}/{name}", content_type, size, user_id),
        )
        saved.append(row)
        count += 1
    return saved, problems


def file_path(item):
    path = (FILE_DIR / item["path"]).resolve()
    if FILE_DIR.resolve() not in path.parents or not path.is_file():
        return None
    return path


def delete_file(item):
    path = file_path(item)
    if path:
        path.unlink(missing_ok=True)
    execute("delete from maintenance_files where id = %s", (item["id"],))
