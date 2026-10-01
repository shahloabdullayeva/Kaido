from flask import Flask, g, redirect, render_template, request, url_for

from . import filters, logs, reminders
from .auth import ANON_CSRF_COOKIE, SESSION_COOKIE, load_session
from .config import IS_PROD, config
from .security import csrf_matches, random_token
from .tenancy import ROLE_LABELS, at_least, is_platform, resolve_company


def anon_csrf():
    token = request.cookies.get(ANON_CSRF_COOKIE)
    if not token or len(token) < 20:
        token = getattr(g, "new_anon_csrf", None) or random_token(24)
        g.new_anon_csrf = token
    return token


def create_app():
    logs.setup("web")
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.secret_key = config.SECRET_KEY
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=IS_PROD,
        MAX_CONTENT_LENGTH=300 * 1024 * 1024,
    )
    filters.register(app)

    @app.before_request
    def load_context():
        g.session = load_session(request.cookies.get(SESSION_COOKIE))
        g.company = None
        g.companies = []
        g.role = None
        if g.session:
            resolve_company()
        if request.method == "POST":
            submitted = request.form.get("csrf")
            if g.session:
                if not csrf_matches(g.session["csrf_secret"], submitted):
                    return render_template("errors/expired.html"), 403
            else:
                cookie = request.cookies.get(ANON_CSRF_COOKIE)
                if not cookie or not submitted or cookie != submitted:
                    return render_template("errors/expired.html"), 403

    @app.after_request
    def finish(response):
        if getattr(g, "google_map", False):
            # Google's documented allowlist for the Maps JavaScript API, on the work-order pages only.
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' https://*.googleapis.com https://*.gstatic.com https://*.google.com; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; "
                "img-src 'self' data: blob: https://*.googleapis.com https://*.gstatic.com https://*.google.com "
                "https://*.ggpht.com https://*.googleusercontent.com "
                "https://tile.openstreetmap.org https://*.tile.openstreetmap.org; "
                "connect-src 'self' https://*.googleapis.com https://*.google.com https://*.gstatic.com; "
                "frame-src https://*.google.com; worker-src blob:; "
                "form-action 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'"
            )
        else:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data: https://tile.openstreetmap.org https://*.tile.openstreetmap.org; "
                "form-action 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'"
            )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=(), payment=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        if IS_PROD:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        new_token = getattr(g, "new_anon_csrf", None)
        if new_token:
            response.set_cookie(
                ANON_CSRF_COOKIE, new_token, max_age=3600, httponly=True,
                samesite="Lax", secure=IS_PROD, path="/",
            )
        return response

    def reminder_panel(entity, entity_id):
        company = getattr(g, "company", None)
        if not company:
            return {"rows": [], "default": None, "zone": ""}
        items = reminders.for_entity(company["id"], entity, entity_id)
        for item in items:
            item["local"] = reminders.local(item["remind_at"], company)
        return {"rows": items, "default": reminders.default_when(company),
                "zone": company.get("timezone") or config.TIMEZONE}

    @app.context_processor
    def context():
        return {
            "session": getattr(g, "session", None),
            "company": getattr(g, "company", None),
            "companies": getattr(g, "companies", []),
            "role": getattr(g, "role", None),
            "is_platform": is_platform(),
            "role_labels": ROLE_LABELS,
            "at_least": at_least,
            "anon_csrf": anon_csrf,
            "app_config": config,
            "reminder_panel": reminder_panel,
            "audiences": reminders.AUDIENCES,
        }

    from .views.auth import bp as auth_bp
    from .views.breakdowns import bp as breakdowns_bp
    from .views.company import bp as company_bp
    from .views.dashboard import bp as dashboard_bp
    from .views.drivers import bp as drivers_bp
    from .views.faults import bp as faults_bp
    from .views.fuel import bp as fuel_bp
    from .views.integrations import bp as integrations_bp
    from .views.maintenance import bp as maintenance_bp
    from .views.platform import bp as platform_bp
    from .views.reminders import bp as reminders_bp
    from .views.assistant import bp as assistant_bp
    from .views.reports import bp as reports_bp
    from .views.trucks import bp as trucks_bp
    from .views.pti import bp as pti_bp
    from .views.settings import bp as settings_bp

    for blueprint in (auth_bp, dashboard_bp, trucks_bp, drivers_bp, fuel_bp,
                      maintenance_bp, breakdowns_bp, faults_bp, integrations_bp,
                      company_bp, platform_bp, reminders_bp, assistant_bp, reports_bp, pti_bp, settings_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(404)
    def not_found(err):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(err):
        return render_template("errors/500.html"), 500

    return app
