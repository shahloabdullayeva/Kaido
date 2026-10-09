from datetime import date, timedelta

from flask import Blueprint, Response, g, render_template, request

from .. import forms, reports, work_orders
from ..audit import audit
from ..auth import login_required
from ..db import one, rows
from ..tenancy import active_drivers, active_trucks, company_required

bp = Blueprint("reports", __name__)

TYPES = {
    "pdf": ("application/pdf", "pdf"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    "csv": ("text/csv; charset=utf-8", "csv"),
}


def read_filters(source):
    today = date.today()
    start = forms.day(source.get("start")) or today.replace(day=1)
    end = forms.day(source.get("end")) or today
    if end < start:
        start, end = end, start
    return {
        "company_id": g.company["id"],
        "kind": forms.pick(source.get("kind"), list(reports.REPORTS), "maintenance"),
        "start": start,
        "end": end,
        "truck_id": forms.integer(source.get("truck_id")),
        "driver_id": forms.integer(source.get("driver_id")),
        "fleet": forms.pick(source.get("fleet"), ["all", "own", "outside"], "all"),
    }


def describe(filters):
    bits = [g.company["name"]]
    if filters["kind"] != "fleet":
        bits.append(f"{filters['start']:%d %b %Y} to {filters['end']:%d %b %Y}")
    else:
        bits.append(f"as of {date.today():%d %b %Y}")
    if filters["truck_id"]:
        truck = one("select unit_number from trucks where id = %s and company_id = %s", (filters["truck_id"], g.company["id"]))
        if truck:
            bits.append(f"unit {truck['unit_number']}")
    if filters["driver_id"]:
        driver = one("select name from drivers where id = %s and company_id = %s", (filters["driver_id"], g.company["id"]))
        if driver:
            bits.append(driver["name"])
    if filters["fleet"] == "own":
        bits.append("own trucks only")
    elif filters["fleet"] == "outside":
        bits.append("outside trucks only")
    return " · ".join(bits)


@bp.get("/reports")
@login_required
@company_required
def index():
    filters = read_filters(request.args)
    columns, data, totals = reports.build(filters["kind"], filters)
    presets = []
    today = date.today()
    first = today.replace(day=1)
    last_month_end = first - timedelta(days=1)
    presets = [
        ("This month", first, today),
        ("Last month", last_month_end.replace(day=1), last_month_end),
        ("Last 90 days", today - timedelta(days=90), today),
        ("This year", today.replace(month=1, day=1), today),
    ]
    return render_template("reports/index.html", title="Reports", active="/reports", filters=filters, wide=True,
                           kinds=reports.REPORTS, columns=columns, data=data[:300], count=len(data),
                           totals=totals, cell=reports.cell_text, subtitle=describe(filters),
                           trucks=active_trucks(), drivers=active_drivers(), presets=presets)


@bp.get("/reports/download")
@login_required
@company_required
def download():
    filters = read_filters(request.args)
    fmt = forms.pick(request.args.get("format"), list(TYPES), "pdf")
    columns, data, totals = reports.build(filters["kind"], filters)
    title = reports.REPORTS[filters["kind"]]
    subtitle = describe(filters)
    if fmt == "pdf":
        body = reports.to_pdf(title, subtitle, columns, data, totals)
    elif fmt == "xlsx":
        body = reports.to_xlsx(title, subtitle, columns, data, totals)
    else:
        body = reports.to_csv(columns, data, totals)
    mime, ext = TYPES[fmt]
    name = f"kaido-{filters['kind']}-{filters['start']:%Y%m%d}-{filters['end']:%Y%m%d}.{ext}"
    audit("report.downloaded", "report", filters["kind"], {"format": fmt, "rows": len(data)})
    return Response(body, mimetype=mime, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@bp.get("/maintenance/<int:order_id>/pdf")
@login_required
@company_required
def order_pdf(order_id):
    order = one(
        """select m.*, t.unit_number, t.vin, t.make, t.model, t.year, t.engine, t.is_outside, t.outside_carrier,
             d.name as driver_name, d.phone as driver_phone, u.name as author
           from maintenance_orders m join trucks t on t.id = m.truck_id
           left join drivers d on d.id = m.driver_id left join users u on u.id = m.created_by
           where m.id = %s and m.company_id = %s""",
        (order_id, g.company["id"]),
    )
    if not order:
        return render_template("errors/404.html"), 404
    cell = reports.cell_text
    fields = [
        ("Truck", f"Unit {order['unit_number']}" + (f" ({order['outside_carrier'] or 'outside truck'})" if order["is_outside"] else "")),
        ("Vehicle", " ".join(str(p) for p in [order["year"], order["make"], order["model"]] if p)),
        ("Engine", order["engine"]), ("VIN", order["vin"]),
        ("Driver", " · ".join(p for p in [order["driver_name"], order["driver_contact"] or order["driver_phone"]] if p)),
        ("Work", reports.KIND_LABELS.get(order["kind"], order["kind"])),
        ("Status", order["status"].replace("_", " ")),
        ("Scheduled", cell(order["scheduled_for"], "date")), ("Done on", cell(order["performed_on"], "date")),
        ("Odometer", cell(order["odometer"], "int")),
        ("Shop", " · ".join(p for p in [order["vendor"], order["shop_phone"]] if p)), ("Shop address", order["shop_address"]),
        ("Invoice", order["invoice_no"]),
        ("Labor", cell(order["labor_cost"], "money")), ("Tax and fees", cell(order["tax"], "money")),
        ("Total amount", cell(order["cost"], "money")),
        ("Paid with", work_orders.PAYMENT_LABELS.get(order["paid_with"] or "", "")),
        ("Attached", ", ".join(item["name"] for item in work_orders.files_of(order_id))),
        ("Next due", " · ".join(p for p in [cell(order["next_due_on"], "date"),
                                             (cell(order["next_due_odometer"], "int") + " mi") if order["next_due_odometer"] else ""] if p)),
        ("Opened by", order["author"]),
    ]
    parts = [(part["name"], part["part_number"], f"{float(part['quantity']):g}", cell(part["unit_price"], "money"),
              cell(float(part["quantity"]) * float(part["unit_price"]), "money") if part["unit_price"] is not None else "")
             for part in work_orders.parts_of(order_id)]
    body = reports.record_pdf(f"Work order #{order_id}", g.company["name"], fields,
                              [("What was done", order["description"])],
                              tables=[("Parts", (70, 40, 20, 30, 30), ("Part", "Part number", "Qty", "Unit price", "Amount"), parts)])
    audit("report.downloaded", "maintenance_order", order_id, {"format": "pdf"})
    return Response(body, mimetype="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="work-order-{order_id}.pdf"'})


@bp.get("/breakdowns/<int:breakdown_id>/pdf")
@login_required
@company_required
def breakdown_pdf(breakdown_id):
    item = one(
        """select b.*, t.unit_number, t.make, t.model, t.year, d.name as driver_name, d.phone as driver_phone
           from breakdowns b join trucks t on t.id = b.truck_id left join drivers d on d.id = b.driver_id
           where b.id = %s and b.company_id = %s""",
        (breakdown_id, g.company["id"]),
    )
    if not item:
        return render_template("errors/404.html"), 404
    updates = rows(
        """select u.created_at, u.note, u.status, us.name as author from breakdown_updates u
           left join users us on us.id = u.created_by where u.breakdown_id = %s order by u.created_at""",
        (breakdown_id,),
    )
    cell = reports.cell_text
    fields = [
        ("Truck", f"Unit {item['unit_number']} · " + " ".join(str(p) for p in [item["year"], item["make"], item["model"]] if p)),
        ("Driver", " · ".join(p for p in [item["driver_name"], item["driver_phone"]] if p)),
        ("Reported", cell(item["occurred_at"], "datetime")), ("Resolved", cell(item["resolved_at"], "datetime")),
        ("Severity", item["severity"]), ("Status", item["status"].replace("_", " ")),
        ("Where", item["location"]), ("Load", item["load_number"]),
        ("Towing", cell(item["towing_cost"], "money")), ("Repair", cell(item["repair_cost"], "money")),
    ]
    timeline = "\n".join(f"{u['created_at']:%d %b %Y %H:%M} · {u['author'] or 'system'}: {u['note']}" for u in updates)
    body = reports.record_pdf(f"Breakdown #{breakdown_id}", g.company["name"], fields, [
        ("What happened", item["description"]), ("Cause", item["cause"]),
        ("What fixed it", item["resolution"]), ("Timeline", timeline)])
    audit("report.downloaded", "breakdown", breakdown_id, {"format": "pdf"})
    return Response(body, mimetype="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="breakdown-{breakdown_id}.pdf"'})
