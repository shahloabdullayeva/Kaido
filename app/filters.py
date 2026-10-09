import json
import re
from datetime import date, datetime, timezone

from markupsafe import Markup, escape

from . import work_types

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


def json_attr(value):
    return Markup(escape(json.dumps(value)))


def shop_pins(found):
    pins = [{"name": shop["name"], "lat": shop["latitude"], "lon": shop["longitude"],
             "miles": shop["miles"], "open": shop["open_state"], "address": shop.get("address"),
             "phone": shop.get("phone"), "dial": shop.get("dial"), "maps": shop.get("maps"),
             "hours": shop.get("hours_text"), "saved": bool(shop.get("saved"))} for shop in found or []]
    return Markup(escape(json.dumps(pins)))


OSM_DAYS = {"Mo": "Mon", "Tu": "Tue", "We": "Wed", "Th": "Thu", "Fr": "Fri", "Sa": "Sat", "Su": "Sun", "PH": "holidays"}


def osm_hours(value):
    if not value:
        return ""
    text = str(value).strip()
    if text == "24/7":
        return "open 24 hours, every day"
    for short, full in OSM_DAYS.items():
        text = re.sub(rf"\b{short}\b", full, text)
    return text.replace(";", " ·").replace(",", ", ").replace("off", "closed")


def source(value):
    from .hos import SOURCES
    return SOURCES.get(value or "", "Entered by hand" if value is None else str(value))


def register(app):
    app.jinja_env.filters.update({
        "source": source,
        "money": money,
        "miles": miles,
        "number": number,
        "day": day,
        "stamp": stamp,
        "date_input": date_input,
        "ago": ago,
        "tone": tone,
        "label": label,
        "work": work_types.label,
        "shop_pins": shop_pins,
        "json_attr": json_attr,
        "osm_hours": osm_hours,
    })
