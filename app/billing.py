from datetime import date, timedelta
from urllib.parse import urlparse

from .config import ROOT, config
from .db import execute, insert, one, rows

DUE_DAYS = 14
FONTS = ROOT / "app" / "fonts"
SELECT = """select i.*, c.name as company_name, c.legal_name, c.dot_number, c.mc_number,
                   c.contact_name, c.contact_email, u.name as paid_by_name
            from invoices i join companies c on c.id = i.company_id
            left join users u on u.id = i.paid_by"""


def month_start(day=None):
    return (day or date.today()).replace(day=1)


def rate_for(company):
    rate = company.get("billing_rate")
    return float(config.BILLING_RATE if rate is None else rate)


def truck_count(company_id):
    row = one(
        "select count(*) as n from trucks where company_id = %s and status <> 'sold' and not is_outside",
        (company_id,),
    )
    return row["n"]


def amount_for(count, rate):
    return max(round(count * rate, 2), float(config.BILLING_MINIMUM))


def issue(company, period=None):
    period = period or month_start()
    existing = one("select id from invoices where company_id = %s and period = %s", (company["id"], period))
    if existing:
        return existing["id"]
    rate = rate_for(company)
    count = truck_count(company["id"])
    if rate <= 0 or count == 0:
        return None
    today = date.today()
    row = insert(
        """insert into invoices (company_id, number, period, truck_count, unit_price, minimum, amount, issued_on, due_on)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
           on conflict (company_id, period) do nothing returning id""",
        (company["id"], f"KD-{period:%Y%m}-{company['id']:03d}", period, count, rate,
         config.BILLING_MINIMUM, amount_for(count, rate), today, today + timedelta(days=DUE_DAYS)),
    )
    return row["id"] if row else None


def issue_missing():
    created = 0
    for company in rows("select * from companies where status = 'active'"):
        before = one("select id from invoices where company_id = %s and period = %s", (company["id"], month_start()))
        if not before and issue(company):
            created += 1
    return created


def recalculate(invoice, company):
    rate = rate_for(company)
    count = truck_count(company["id"])
    execute(
        "update invoices set truck_count = %s, unit_price = %s, minimum = %s, amount = %s where id = %s and status = 'due'",
        (count, rate, config.BILLING_MINIMUM, amount_for(count, rate), invoice["id"]),
    )


def for_company(company_id):
    return rows(SELECT + " where i.company_id = %s order by i.period desc", (company_id,))


def everything():
    return rows(SELECT + " order by i.period desc, lower(c.name)")


def find(invoice_id, company_id=None):
    if company_id is None:
        return one(SELECT + " where i.id = %s", (invoice_id,))
    return one(SELECT + " where i.id = %s and i.company_id = %s", (invoice_id, company_id))


def overdue(invoice):
    return invoice["status"] == "due" and invoice["due_on"] < date.today()


def state(invoice):
    if invoice["status"] == "paid":
        return "paid"
    return "overdue" if overdue(invoice) else "due"


def minimum_applies(invoice):
    return float(invoice["amount"]) > round(invoice["truck_count"] * float(invoice["unit_price"]), 2)


def seller():
    return urlparse(config.APP_URL).hostname or "Kaido"


def money(value):
    return "${:,.2f}".format(float(value))


def pdf(invoice):
    from fpdf import FPDF
    from fpdf.fonts import FontFace

    doc = FPDF(orientation="P", unit="mm", format="Letter")
    doc.add_font("dejavu", "", str(FONTS / "DejaVuSansCondensed.ttf"))
    doc.add_font("dejavu", "B", str(FONTS / "DejaVuSansCondensed-Bold.ttf"))
    doc.set_margins(18, 18, 18)
    doc.set_auto_page_break(True, margin=18)
    doc.set_title(f"Invoice {invoice['number']}")
    doc.add_page()

    doc.set_font("dejavu", "B", 22)
    doc.set_text_color(31, 58, 138)
    doc.cell(90, 10, "KAIDO")
    doc.set_text_color(0, 0, 0)
    doc.cell(0, 10, "INVOICE", align="R", new_x="LMARGIN", new_y="NEXT")
    doc.set_font("dejavu", "", 9)
    doc.set_text_color(100, 100, 100)
    doc.cell(90, 5, f"Fleet maintenance platform · {seller()}")
    doc.cell(0, 5, invoice["number"], align="R", new_x="LMARGIN", new_y="NEXT")
    doc.set_text_color(0, 0, 0)
    doc.ln(10)

    top = doc.get_y()
    doc.set_font("dejavu", "B", 8)
    doc.set_text_color(100, 100, 100)
    doc.cell(0, 5, "BILL TO", new_x="LMARGIN", new_y="NEXT")
    doc.set_text_color(0, 0, 0)
    doc.set_font("dejavu", "B", 12)
    doc.cell(0, 6, invoice["legal_name"] or invoice["company_name"], new_x="LMARGIN", new_y="NEXT")
    doc.set_font("dejavu", "", 9.5)
    lines = [
        f"DOT {invoice['dot_number']}" if invoice["dot_number"] else None,
        f"MC {invoice['mc_number']}" if invoice["mc_number"] else None,
        invoice["contact_name"], invoice["contact_email"],
    ]
    for line in filter(None, lines):
        doc.cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")
    bottom = doc.get_y()

    doc.set_y(top)
    facts = [
        ("Billing period", f"{invoice['period']:%B %Y}"),
        ("Issued", f"{invoice['issued_on']:%d %b %Y}"),
        ("Due", f"{invoice['due_on']:%d %b %Y}"),
        ("Status", "Paid" if invoice["status"] == "paid" else ("Overdue" if overdue(invoice) else "Due")),
    ]
    for label, value in facts:
        doc.set_x(120)
        doc.set_font("dejavu", "", 9.5)
        doc.set_text_color(100, 100, 100)
        doc.cell(35, 6, label)
        doc.set_text_color(0, 0, 0)
        doc.set_font("dejavu", "B", 9.5)
        doc.cell(0, 6, value, align="R", new_x="LMARGIN", new_y="NEXT")
    doc.set_y(max(bottom, doc.get_y()) + 10)

    doc.set_font("dejavu", "", 9.5)
    bold = FontFace(emphasis="BOLD", fill_color=(238, 238, 238))
    with doc.table(col_widths=(96, 24, 28, 32), line_height=7, text_align=("LEFT", "RIGHT", "RIGHT", "RIGHT"),
                   headings_style=bold, borders_layout="HORIZONTAL_LINES") as table:
        head = table.row()
        for text in ("Description", "Trucks", "Per truck", "Amount"):
            head.cell(text)
        line = table.row()
        line.cell(f"Kaido fleet platform, {invoice['period']:%B %Y}")
        line.cell(str(invoice["truck_count"]))
        line.cell(money(invoice["unit_price"]))
        line.cell(money(invoice["truck_count"] * float(invoice["unit_price"])))
        if minimum_applies(invoice):
            extra = table.row()
            extra.cell(f"Monthly minimum of {money(invoice['minimum'])}")
            extra.cell("")
            extra.cell("")
            extra.cell(money(float(invoice["amount"]) - invoice["truck_count"] * float(invoice["unit_price"])))
    doc.ln(6)
    doc.set_x(120)
    doc.set_font("dejavu", "B", 13)
    doc.cell(35, 9, "Total paid" if invoice["status"] == "paid" else "Total due")
    doc.cell(0, 9, f"{money(invoice['amount'])} USD", align="R", new_x="LMARGIN", new_y="NEXT")
    if invoice["status"] == "paid" and invoice["paid_at"]:
        doc.set_x(120)
        doc.set_font("dejavu", "", 9.5)
        doc.set_text_color(23, 112, 58)
        doc.cell(0, 6, f"Paid on {invoice['paid_at']:%d %b %Y}", align="R", new_x="LMARGIN", new_y="NEXT")
        doc.set_text_color(0, 0, 0)

    doc.ln(14)
    doc.set_font("dejavu", "", 8.5)
    doc.set_text_color(110, 110, 110)
    doc.multi_cell(0, 4.5, "Trucks are counted on the day the invoice is issued. Sold trucks and trucks "
                           "from outside the fleet are not counted.")
    return bytes(doc.output())
