from flask import Blueprint, Response, abort, flash, g, redirect, render_template, request

from .. import billing, forms
from ..audit import audit
from ..auth import login_required
from ..config import config
from ..db import execute, one, rows, unscoped
from ..tenancy import is_platform, platform_required, role_required

bp = Blueprint("billing", __name__)


def is_owner():
    return g.session["platform_role"] == "owner"


def visible(invoice_id):
    if is_platform():
        with unscoped():
            return billing.find(invoice_id)
    if not g.company or g.role != "admin":
        return None
    return billing.find(invoice_id, g.company["id"])


@bp.get("/billing")
@login_required
@role_required("admin")
def index():
    company = one("select * from companies where id = %s", (g.company["id"],))
    billing.issue(company)
    invoices = billing.for_company(company["id"])
    current = next((item for item in invoices if item["period"] == billing.month_start()), None)
    return render_template(
        "billing/index.html", title="Billing", active="/billing", invoices=invoices, current=current,
        rate=billing.rate_for(company), minimum=config.BILLING_MINIMUM, state=billing.state,
        trucks=billing.truck_count(company["id"]), owner=is_owner(),
    )


@bp.get("/billing/<int:invoice_id>")
@login_required
def invoice(invoice_id):
    row = visible(invoice_id)
    if not row:
        abort(404)
    return render_template(
        "billing/invoice.html", title=f"Invoice {row['number']}", active="/billing", invoice=row,
        state=billing.state(row), minimum_applies=billing.minimum_applies(row), seller=billing.seller(),
        owner=is_owner(),
    )


@bp.get("/billing/<int:invoice_id>/invoice.pdf")
@login_required
def invoice_pdf(invoice_id):
    row = visible(invoice_id)
    if not row:
        abort(404)
    response = Response(billing.pdf(row), mimetype="application/pdf")
    response.headers["Content-Disposition"] = f'attachment; filename="Kaido-{row["number"]}.pdf"'
    return response


@bp.get("/platform/billing")
@login_required
@platform_required
def platform():
    with unscoped():
        billing.issue_missing()
        invoices = billing.everything()
        companies = rows(
            """select c.*, (select count(*) from trucks t where t.company_id = c.id and t.status <> 'sold'
                              and not t.is_outside) as truck_count
               from companies c where c.status = 'active' order by lower(c.name)"""
        )
    for company in companies:
        company["rate"] = billing.rate_for(company)
    due = sum(float(item["amount"]) for item in invoices if item["status"] == "due")
    paid = sum(float(item["amount"]) for item in invoices
               if item["status"] == "paid" and item["period"] == billing.month_start())
    return render_template(
        "billing/platform.html", title="Billing", active="/billing", invoices=invoices, companies=companies,
        due=due, paid=paid, state=billing.state, default_rate=config.BILLING_RATE, minimum=config.BILLING_MINIMUM,
        owner=is_owner(), month=billing.month_start(),
    )


def back():
    target = request.form.get("back") or ""
    return redirect(target if target.startswith("/billing") else "/platform/billing")


@bp.post("/platform/billing/<int:invoice_id>/status")
@login_required
@platform_required
def set_status(invoice_id):
    if not is_owner():
        flash("Only the platform owner can change an invoice.", "bad")
        return back()
    status = forms.pick(request.form.get("status"), ["paid", "due"], "paid")
    with unscoped():
        row = billing.find(invoice_id)
        if not row:
            abort(404)
        if status == "paid":
            execute(
                "update invoices set status = 'paid', paid_at = now(), paid_by = %s, paid_note = %s where id = %s",
                (g.session["user_id"], forms.text(request.form.get("note"), 200), invoice_id),
            )
        else:
            execute(
                "update invoices set status = 'due', paid_at = null, paid_by = null, paid_note = null where id = %s",
                (invoice_id,),
            )
        audit("invoice." + status, "invoice", invoice_id, {"number": row["number"], "amount": float(row["amount"])},
              company_id=row["company_id"])
    flash(f"{row['number']} marked {'paid' if status == 'paid' else 'not paid'}.", "ok")
    return back()


@bp.post("/platform/billing/<int:invoice_id>/recalculate")
@login_required
@platform_required
def recalculate(invoice_id):
    if not is_owner():
        flash("Only the platform owner can change an invoice.", "bad")
        return back()
    with unscoped():
        row = billing.find(invoice_id)
        if not row:
            abort(404)
        if row["status"] != "due":
            flash("A paid invoice is not recounted. Mark it not paid first.", "bad")
            return back()
        company = one("select * from companies where id = %s", (row["company_id"],))
        billing.recalculate(row, company)
        audit("invoice.recalculated", "invoice", invoice_id, {"number": row["number"]}, company_id=row["company_id"])
    flash(f"{row['number']} recounted with today's trucks and price.", "ok")
    return back()


@bp.post("/platform/billing/companies/<int:company_id>/rate")
@login_required
@platform_required
def set_rate(company_id):
    if not is_owner():
        flash("Only the platform owner can change a price.", "bad")
        return back()
    rate = forms.decimal(request.form.get("rate"))
    if rate is not None and (rate < 0 or rate > 1000):
        flash("That price does not look right.", "bad")
        return back()
    with unscoped():
        execute("update companies set billing_rate = %s, updated_at = now() where id = %s",
                (None if rate is None else round(rate, 2), company_id))
        audit("company.billing_rate", "company", company_id, {"rate": rate}, company_id=company_id)
    flash("Price saved. It applies to invoices from now on; use Recount to apply it to one that is still due.", "ok")
    return back()
