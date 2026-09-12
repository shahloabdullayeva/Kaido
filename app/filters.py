import json
from datetime import date, datetime, timezone

from markupsafe import Markup, escape

TONES = {
    "active": "ok", "done": "ok", "resolved": "ok", "connected": "ok",
    "shop": "warn", "in_progress": "warn", "towing": "warn", "in_shop": "warn",
    "scheduled": "info", "medium": "warn", "low": "info",
    "out_of_service": "bad", "open": "bad", "high": "bad", "error": "bad",
    "sold": "muted", "inactive": "muted", "disconnected": "muted", "unknown": "muted",
}


def money(value):
    if value is None or value == "":
        return "—"
    return "${:,.2f}".format(float(value))


def miles(value):
    if value is None or value == "":
        return "—"
    return "{:,} mi".format(int(value))


def number(value, digits=0):
    if value is None or value == "":
        return "—"
    return "{:,.{d}f}".format(float(value), d=digits)


def day(value):
    if not value:
        return "—"
    if isinstance(value, datetime):
        value = value.date()
    return value.strftime("%d %b %Y")


def stamp(value):
    if not value:
        return "—"
    return value.strftime("%d %b %Y %H:%M")


def date_input(value):
    if not value:
        return ""
    if isinstance(value, datetime):
        value = value.date()
    return value.isoformat()


def ago(value):
    if not value:
        return "—"
    now = datetime.now(timezone.utc) if value.tzinfo else datetime.now()
    seconds = (now - value).total_seconds()
    if seconds < 60:
        return "just now"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 30:
        return f"{days}d ago"
    return day(value)


def tone(value):
    return TONES.get(str(value or "").lower(), "muted")


def label(value):
    return str(value or "").replace("_", " ")


def shop_pins(found):
    pins = [{"name": shop["name"], "lat": shop["latitude"], "lon": shop["longitude"],
             "miles": shop["miles"], "open": shop["open_state"]} for shop in found or []]
    return Markup(escape(json.dumps(pins)))


def register(app):
    app.jinja_env.filters.update({
        "money": money,
        "miles": miles,
        "number": number,
        "day": day,
        "stamp": stamp,
        "date_input": date_input,
        "ago": ago,
        "tone": tone,
        "label": label,
        "shop_pins": shop_pins,
    })
