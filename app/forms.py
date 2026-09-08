from datetime import datetime


def text(value, limit=300):
    if value is None:
        return None
    trimmed = str(value).strip()
    return trimmed[:limit] if trimmed else None


def required(value, limit=300):
    return text(value, limit) or ""


def integer(value):
    raw = text(value, 20)
    if raw is None:
        return None
    cleaned = "".join(ch for ch in raw if ch.isdigit() or ch == "-")
    try:
        return int(cleaned)
    except ValueError:
        return None


def decimal(value):
    raw = text(value, 24)
    if raw is None:
        return None
    cleaned = "".join(ch for ch in raw if ch.isdigit() or ch in ".-")
    try:
        return float(cleaned)
    except ValueError:
        return None


def day(value):
    raw = text(value, 10)
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def moment(value):
    raw = text(value, 32)
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def pick(value, allowed, fallback=None):
    raw = text(value, 40)
    return raw if raw in allowed else fallback


def checkbox(value):
    return str(value).lower() in ("1", "on", "true", "yes")
