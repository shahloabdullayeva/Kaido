from flask import Blueprint, flash, g, redirect, render_template, request

from .. import forms
from ..audit import audit
from ..auth import login_required
from ..db import execute, insert, one, rows
from ..security import hash_password, random_token
from ..tenancy import ROLES, ROLE_LABELS, company_required, role_required

bp = Blueprint("company", __name__)


@bp.post("/company/switch")
@login_required
def switch():
    company_id = forms.integer(request.form.get("company_id"))
    allowed = any(item["id"] == company_id for item in g.companies)
    if allowed:
        execute("update sessions set company_id = %s where id = %s", (company_id, g.session["id"]))
        audit("company.switched", "company", company_id)
    return redirect(request.referrer if request.referrer and request.referrer.startswith(request.host_url) else "/")


@bp.get("/company")
@login_required
@role_required("admin")
def index():
    company = one("select * from companies where id = %s", (g.company["id"],))
    members = rows(
        """select u.id, u.name, u.email, u.status, u.telegram_chat_id, u.last_login_at, m.role
           from memberships m join users u on u.id = m.user_id
           where m.company_id = %s order by lower(u.name)""",
        (g.company["id"],),
    )
    log = rows(
        """select a.*, u.name as user_name from audit_log a left join users u on u.id = a.user_id
           where a.company_id = %s order by a.created_at desc limit 50""",
        (g.company["id"],),
    )
    return render_template("company/index.html", title="Company", active="/company",
                           company=company, members=members, log=log, roles=ROLES, role_labels=ROLE_LABELS)


@bp.post("/company")
@login_required
@role_required("admin")
def update():
    execute(
        """update companies set name = %s, legal_name = %s, dot_number = %s, mc_number = %s,
             contact_name = %s, contact_phone = %s, contact_email = %s, timezone = %s, updated_at = now()
           where id = %s""",
        (
            forms.required(request.form.get("name"), 160) or g.company["name"],
            forms.text(request.form.get("legal_name"), 160),
            forms.text(request.form.get("dot_number"), 20),
            forms.text(request.form.get("mc_number"), 20),
            forms.text(request.form.get("contact_name"), 120),
            forms.text(request.form.get("contact_phone"), 40),
            forms.text(request.form.get("contact_email"), 200),
            forms.text(request.form.get("timezone"), 60) or "America/Chicago",
            g.company["id"],
        ),
    )
    audit("company.updated", "company", g.company["id"])
    flash("Company details saved.", "ok")
    return redirect("/company")


@bp.post("/company/members")
@login_required
@role_required("admin")
def add_member():
    email = (forms.text(request.form.get("email"), 200) or "").lower()
    name = forms.required(request.form.get("name"), 120)
    role = forms.pick(request.form.get("role"), ROLES, "viewer")
    if not email or "@" not in email or not name:
        flash("A name and a valid email are required.", "bad")
        return redirect("/company")
    user = one("select * from users where lower(email) = lower(%s)", (email,))
    temporary = None
    if not user:
        temporary = random_token(9)
        user = insert(
            "insert into users (email, name, password_hash) values (%s, %s, %s) returning *",
            (email, name, hash_password(temporary)),
        )
    existing = one("select id from memberships where user_id = %s and company_id = %s", (user["id"], g.company["id"]))
    if existing:
        flash(f"{name} is already a member.", "warn")
        return redirect("/company")
    execute(
        "insert into memberships (user_id, company_id, role) values (%s, %s, %s)",
        (user["id"], g.company["id"], role),
    )
    audit("member.added", "user", user["id"], {"role": role, "email": email})
    if temporary:
        flash(f"{name} added. Temporary password: {temporary} — give it to them in person and have them change it.", "ok")
    else:
        flash(f"{name} added to this company as {ROLE_LABELS[role]}.", "ok")
    return redirect("/company")


@bp.post("/company/members/<int:user_id>/role")
@login_required
@role_required("admin")
def change_role(user_id):
    role = forms.pick(request.form.get("role"), ROLES, None)
    if not role:
        flash("Pick a valid role.", "bad")
        return redirect("/company")
    if user_id == g.session["user_id"]:
        flash("You cannot change your own role.", "bad")
        return redirect("/company")
    execute("update memberships set role = %s where user_id = %s and company_id = %s", (role, user_id, g.company["id"]))
    audit("member.role_changed", "user", user_id, {"role": role})
    flash("Role updated.", "ok")
    return redirect("/company")


@bp.post("/company/members/<int:user_id>/remove")
@login_required
@role_required("admin")
def remove_member(user_id):
    if user_id == g.session["user_id"]:
        flash("You cannot remove yourself.", "bad")
        return redirect("/company")
    execute("delete from memberships where user_id = %s and company_id = %s", (user_id, g.company["id"]))
    execute("update sessions set revoked_at = now() where user_id = %s and company_id = %s and revoked_at is null",
            (user_id, g.company["id"]))
    audit("member.removed", "user", user_id)
    flash("Member removed from this company.", "ok")
    return redirect("/company")
