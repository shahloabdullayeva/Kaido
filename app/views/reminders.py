from flask import Blueprint, flash, g, redirect, render_template, request

from .. import forms, reminders
from ..audit import audit
from ..auth import login_required
from ..tenancy import at_least, company_required

bp = Blueprint("reminders", __name__)


def safe_back(value, fallback="/reminders"):
    value = value or ""
    return value if value.startswith("/") and not value.startswith("//") else fallback


@bp.get("/reminders")
@login_required
@company_required
def index():
    items = reminders.open_for_company(g.company["id"])
    for item in items:
        about = reminders.describe(g.company["id"], item["entity"], item["entity_id"])
        item["label"], item["href"] = about if about else (reminders.ENTITIES.get(item["entity"], "Record"), None)
        item["local"] = reminders.local(item["remind_at"], g.company)
    return render_template("reminders/list.html", title="Reminders", active="/reminders", items=items)


@bp.post("/reminders")
@login_required
@company_required
def create():
    back = safe_back(request.form.get("back"))
    entity = forms.pick(request.form.get("entity"), list(reminders.ENTITIES), None)
    entity_id = forms.integer(request.form.get("entity_id"))
    note = forms.required(request.form.get("note"), 1000)
    when = forms.moment(request.form.get("remind_at"))
    audience = forms.pick(request.form.get("audience"), list(reminders.AUDIENCES), "me")
    if audience == "admins" and not at_least(g.role, "admin"):
        audience = "me"
    if not entity or not entity_id or not reminders.describe(g.company["id"], entity, entity_id):
        flash("That record could not be found.", "bad")
        return redirect(back)
    if not note or not when:
        flash("Write what to remind about and pick a date and time.", "bad")
        return redirect(back)
    item = reminders.create(g.company["id"], entity, entity_id, note,
                            reminders.to_utc(when, g.company), audience, g.session["user_id"])
    audit("reminder.created", "reminder", item["id"], {"entity": entity, "entity_id": entity_id})
    flash(f"Reminder set for {when.strftime('%d %b %Y %H:%M')}. It will come to Telegram.", "ok")
    return redirect(back)


@bp.post("/reminders/<int:reminder_id>/done")
@login_required
@company_required
def done(reminder_id):
    if reminders.finish(g.company["id"], reminder_id, g.session["user_id"]):
        audit("reminder.done", "reminder", reminder_id)
        flash("Reminder marked done.", "ok")
    return redirect(safe_back(request.form.get("back")))
