from flask import Blueprint, flash, g, redirect, render_template, request

from .. import forms
from ..audit import audit
from ..auth import login_required
from ..db import execute, insert, one, rows, unscoped
from ..security import hash_password, random_token
from ..tenancy import platform_required

bp = Blueprint("platform", __name__)


@bp.get("/platform")
@login_required
@platform_required
def index():
    with unscoped():
        return _index()


def _index():
    companies = rows(
        """select c.*,
             (select count(*) from trucks t where t.company_id = c.id and t.status <> 'sold') as truck_count,
             (select count(*) from drivers d where d.company_id = c.id and d.status = 'active') as driver_count,
             (select count(*) from memberships m where m.company_id = c.id) as member_count,
             (select count(*) from breakdowns b where b.company_id = c.id and b.status <> 'resolved') as open_breakdowns,
             (select count(*) from fault_events f where f.company_id = c.id and f.cleared_at is null) as active_faults,
             (select status from integrations i where i.company_id = c.id and i.provider = 'samsara') as samsara_status,
             (select last_sync_at from integrations i where i.company_id = c.id and i.provider = 'samsara') as last_sync_at
           from companies c order by c.is_house desc, lower(c.name)"""
    )
    staff = rows(
        """select u.id, u.name, u.email, u.platform_role, u.status, u.last_login_at,
             coalesce(json_agg(json_build_object('company', c.name, 'role', m.role) order by lower(c.name))
                      filter (where c.id is not null), '[]') as access
           from users u
           left join memberships m on m.user_id = u.id
           left join companies c on c.id = m.company_id
           group by u.id
           order by u.platform_role is null, lower(u.name)"""
    )
    totals = one(
        """select (select count(*) from companies where status = 'active') as companies,
                  (select count(*) from trucks where status <> 'sold') as trucks,
                  (select count(*) from breakdowns where status <> 'resolved') as breakdowns,
                  (select count(*) from fault_events where cleared_at is null) as faults"""
    )
    return render_template("platform/index.html", title="Platform", active="/platform",
                           companies=companies, staff=staff, totals=totals)


@bp.post("/platform/companies")
@login_required
@platform_required
def add_company():
    name = forms.required(request.form.get("name"), 160)
    if not name:
        flash("A company name is required.", "bad")
        return redirect("/platform")
    company = insert(
        """insert into companies (name, legal_name, dot_number, mc_number, contact_name, contact_phone,
             contact_email, timezone, is_house)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s) returning *""",
        (
            name, forms.text(request.form.get("legal_name"), 160),
            forms.text(request.form.get("dot_number"), 20), forms.text(request.form.get("mc_number"), 20),
            forms.text(request.form.get("contact_name"), 120), forms.text(request.form.get("contact_phone"), 40),
            forms.text(request.form.get("contact_email"), 200),
            forms.text(request.form.get("timezone"), 60) or "America/Chicago",
            forms.checkbox(request.form.get("is_house")),
        ),
    )
    audit("company.created", "company", company["id"], {"name": name}, company_id=company["id"])
    flash(f"{name} added. Switch to it from the company menu to set it up.", "ok")
    return redirect("/platform")


@bp.post("/platform/companies/<int:company_id>/status")
@login_required
@platform_required
def set_status(company_id):
    status = forms.pick(request.form.get("status"), ["active", "suspended"], "active")
    execute("update companies set status = %s, updated_at = now() where id = %s", (status, company_id))
    if status == "suspended":
        execute(
            """update sessions set revoked_at = now()
               where company_id = %s and revoked_at is null
                 and user_id in (select user_id from memberships where company_id = %s)""",
            (company_id, company_id),
        )
    audit("company.status", "company", company_id, {"status": status}, company_id=company_id)
    flash(f"Company {status}.", "ok")
    return redirect("/platform")


@bp.post("/platform/staff")
@login_required
@platform_required
def add_staff():
    if g.session["platform_role"] != "owner":
        flash("Only a platform owner can add staff.", "bad")
        return redirect("/platform")
    email = (forms.text(request.form.get("email"), 200) or "").lower()
    name = forms.required(request.form.get("name"), 120)
    role = forms.pick(request.form.get("platform_role"), ["owner", "staff"], "staff")
    if not email or "@" not in email or not name:
        flash("A name and a valid email are required.", "bad")
        return redirect("/platform")
    existing = one("select id from users where lower(email) = lower(%s)", (email,))
    if existing:
        execute("update users set platform_role = %s, updated_at = now() where id = %s", (role, existing["id"]))
        audit("platform.staff_promoted", "user", existing["id"], {"platform_role": role})
        flash(f"{name} is now platform {role}.", "ok")
        return redirect("/platform")
    temporary = random_token(9)
    user = insert(
        "insert into users (email, name, password_hash, platform_role) values (%s, %s, %s, %s) returning *",
        (email, name, hash_password(temporary), role),
    )
    audit("platform.staff_added", "user", user["id"], {"platform_role": role})
    flash(f"{name} added as platform {role}. Temporary password: {temporary}", "ok")
    return redirect("/platform")
