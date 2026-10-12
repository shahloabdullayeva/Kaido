from html import escape

from flask import Blueprint, Response, flash, redirect, render_template, request, send_from_directory

from .. import forms
from ..auth import client_ip
from ..db import insert, one, rows
from ..logs import get
from ..telegram import send

bp = Blueprint("site", __name__)
log = get("site")
PER_HOUR = 3


def landing():
    return render_template("landing.html")


@bp.post("/contact")
def contact():
    back = redirect("/#contact")
    if request.form.get("website"):
        return back
    name = forms.text(request.form.get("name"), 120)
    reach = forms.text(request.form.get("reach"), 160)
    if not name or not reach:
        flash("Tell us your name and how to reach you.", "bad")
        return back
    ip = client_ip()
    recent = one("select count(*) as n from contact_requests where ip = %s and created_at > now() - interval '1 hour'", (ip,))
    if recent["n"] >= PER_HOUR:
        flash("We already have your message. We will be in touch.", "info")
        return back
    item = insert(
        """insert into contact_requests (name, company, trucks, reach, message, ip)
           values (%s, %s, %s, %s, %s, %s) returning *""",
        (name, forms.text(request.form.get("company"), 160), forms.text(request.form.get("trucks"), 20), reach,
         forms.text(request.form.get("message"), 1500), ip),
    )
    lines = ["<b>Kaido · someone wants to talk</b>", escape(item["name"])]
    if item["company"]:
        lines.append(escape(item["company"]) + (f" · {escape(item['trucks'])} trucks" if item["trucks"] else ""))
    elif item["trucks"]:
        lines.append(f"{escape(item['trucks'])} trucks")
    lines.append(f"Reach: {escape(item['reach'])}")
    if item["message"]:
        lines += ["", escape(item["message"])]
    for owner in rows("select telegram_chat_id from users where platform_role = 'owner' and status = 'active' and telegram_chat_id is not null"):
        send(owner["telegram_chat_id"], "\n".join(lines))
    log.info("contact request %s from %s", item["id"], ip)
    flash("Thank you. We will get back to you soon.", "ok")
    return back


@bp.get("/robots.txt")
def robots():
    body = "User-agent: *\nAllow: /$\nAllow: /static/\nDisallow: /\n"
    return Response(body, mimetype="text/plain")


@bp.get("/favicon.ico")
def favicon():
    return send_from_directory(bp.root_path + "/../static", "favicon.png", mimetype="image/png")
