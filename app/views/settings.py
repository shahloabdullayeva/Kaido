import socket
import ssl
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from flask import Blueprint, flash, g, redirect, render_template, request

from .. import advisor, forms
from ..audit import audit
from ..auth import login_required
from ..config import config
from ..db import execute
from ..tenancy import is_platform

bp = Blueprint("settings", __name__)

THEMES = {"auto": "Same as my device", "light": "Light", "dark": "Dark"}
BACKUP_DIR = Path("/root/backups/fleet")


def certificate_expires(host):
    try:
        context = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=3) as sock:
            with context.wrap_socket(sock, server_hostname=host) as tls:
                stamp = tls.getpeercert()["notAfter"]
        return datetime.strptime(stamp, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def last_backup():
    try:
        files = sorted(BACKUP_DIR.glob("fleet-*.sql.gz"), key=lambda path: path.stat().st_mtime)
    except OSError:
        return None
    if not files:
        return None
    return datetime.fromtimestamp(files[-1].stat().st_mtime, tz=timezone.utc)


def website():
    host = urlparse(config.APP_URL).hostname or ""
    total, calls = advisor.spent_total()
    return {
        "url": config.APP_URL,
        "certificate": certificate_expires(host) if host and config.APP_URL.startswith("https") else None,
        "bot": config.TELEGRAM_BOT_USERNAME,
        "ai_on": advisor.available(),
        "ai_cap": config.AI_DAILY_USD,
        "ai_today": advisor.spent_today(),
        "ai_total": total,
        "ai_calls": calls,
        "ai_model": config.AI_MODEL,
        "ai_photo_model": config.AI_PHOTO_MODEL,
        "last_backup": last_backup(),
    }


@bp.get("/settings")
@login_required
def index():
    return render_template("settings/index.html", title="Settings", active="/settings", themes=THEMES,
                           site=website() if is_platform() else None)


@bp.post("/settings/appearance")
@login_required
def appearance():
    theme = forms.pick(request.form.get("theme"), list(THEMES), "auto")
    execute("update users set theme = %s, updated_at = now() where id = %s", (theme, g.session["user_id"]))
    audit("settings.theme", "user", g.session["user_id"], {"theme": theme})
    flash(f"Appearance set to {THEMES[theme].lower()}.", "ok")
    return redirect("/settings")


@bp.post("/settings/default-company")
@login_required
def default_company():
    company_id = forms.integer(request.form.get("company_id"))
    if company_id not in {company["id"] for company in g.companies}:
        flash("Pick one of your companies.", "bad")
        return redirect("/settings")
    execute("update users set default_company_id = %s, updated_at = now() where id = %s",
            (company_id, g.session["user_id"]))
    audit("settings.default_company", "user", g.session["user_id"], {"company_id": company_id})
    flash("Saved. Kaido will open on that company next time you sign in.", "ok")
    return redirect("/settings")
