"""Google Maps Platform: Places Text Search, Geocoding, and reading Google Maps links.

Every billable request is written to `google_calls`; at GOOGLE_DAILY_CALLS the app stops
asking Google for the day and the shop finder falls back to OpenStreetMap. The default
cap keeps a month inside Google's free monthly allowance (see README → Google Maps).
"""
import json
import math
import re
from urllib.parse import parse_qs, unquote_plus, urljoin, urlparse

import requests

from .config import config
from .db import execute, one, rows
from .logs import get, redact

log = get("google")

TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

# Phone, hours, website and rating put Text Search on the Enterprise SKU:
# $35 per 1,000, first 1,000 a month free.
SHOP_FIELDS = ",".join("places." + field for field in (
    "id", "displayName", "formattedAddress", "location", "nationalPhoneNumber",
    "internationalPhoneNumber", "regularOpeningHours", "googleMapsUri", "websiteUri",
    "rating", "userRatingCount", "businessStatus", "types", "primaryType",
))
# Asking for the id alone is the "IDs Only" SKU, which Google does not charge for.
ID_FIELDS = "places.id"

PRICE_PER_CALL = {"text_search_enterprise": 0.035, "geocoding": 0.005}
FREE_PER_MONTH = {"text_search_enterprise": 1000, "geocoding": 10000}

GOOGLE_HOSTS = re.compile(r"^((www|maps)\.)?google\.[a-z.]{2,6}$|^(maps\.app\.)?goo\.gl$|^consent\.google\.[a-z.]{2,6}$")


class GoogleError(Exception):
    pass


def available():
    return bool(config.GOOGLE_MAPS_API_KEY)


def calls_today():
    row = one("select count(*) as n from google_calls where created_at >= date_trunc('day', now())")
    return int(row["n"]) if row else 0


def over_budget():
    return calls_today() >= config.GOOGLE_DAILY_CALLS


def usable():
    return available() and not over_budget()


def _record(sku):
    execute("insert into google_calls (sku) values (%s)", (sku,))


def month_usage():
    counts = {row["sku"]: int(row["n"]) for row in rows(
        "select sku, count(*) as n from google_calls where created_at >= date_trunc('month', now()) group by sku")}
    report = []
    for sku, price in PRICE_PER_CALL.items():
        used = counts.get(sku, 0)
        billable = max(0, used - FREE_PER_MONTH[sku])
        report.append({"sku": sku, "used": used, "free": FREE_PER_MONTH[sku], "cost": round(billable * price, 2)})
    return report


def _box(latitude, longitude, radius_m):
    dlat = radius_m / 111_320
    dlon = radius_m / (111_320 * max(math.cos(math.radians(latitude)), 0.01))
    return {"rectangle": {"low": {"latitude": latitude - dlat, "longitude": longitude - dlon},
                          "high": {"latitude": latitude + dlat, "longitude": longitude + dlon}}}


def _text_search(body, fields, sku):
    if not available():
        raise GoogleError("no GOOGLE_MAPS_API_KEY set")
    if sku and over_budget():
        raise GoogleError("today's Google Maps allowance is used up")
    try:
        response = requests.post(TEXT_SEARCH_URL, json=body, timeout=20, headers={
            "X-Goog-Api-Key": config.GOOGLE_MAPS_API_KEY,
            "X-Goog-FieldMask": fields,
        })
    except requests.RequestException as err:
        raise GoogleError("could not reach Google: " + redact(str(err))[:120]) from None
    if sku:
        _record(sku)
    if not response.ok:
        try:
            message = response.json().get("error", {}).get("message") or response.reason
        except ValueError:
            message = response.reason
        log.warning("Places Text Search answered %s: %s", response.status_code, message)
        raise GoogleError(f"Google answered {response.status_code}: {message[:120]}")
    return response.json().get("places") or []


def search_shops(text_query, latitude, longitude, radius_m):
    latitude, longitude = float(latitude), float(longitude)
    body = {
        "textQuery": text_query,
        "pageSize": 20,
        "locationRestriction": _box(latitude, longitude, min(radius_m, 200_000)),
    }
    return _text_search(body, SHOP_FIELDS, "text_search_enterprise")


def place_id_near(name, latitude, longitude):
    """The Google place id for a named spot. Free: only the id is requested."""
    body = {
        "textQuery": name,
        "pageSize": 1,
        "locationBias": {"circle": {"center": {"latitude": float(latitude), "longitude": float(longitude)},
                                    "radius": 400.0}},
    }
    found = _text_search(body, ID_FIELDS, None)
    return found[0] if found else None


def shop_details(name, latitude, longitude):
    """Phone, hours and rating for one known spot — one Enterprise Text Search."""
    body = {
        "textQuery": name,
        "pageSize": 1,
        "locationBias": {"circle": {"center": {"latitude": float(latitude), "longitude": float(longitude)},
                                    "radius": 400.0}},
    }
    found = _text_search(body, SHOP_FIELDS, "text_search_enterprise")
    return found[0] if found else None


def geocode(text):
    if not available():
        raise GoogleError("no GOOGLE_MAPS_API_KEY set")
    if over_budget():
        raise GoogleError("today's Google Maps allowance is used up")
    try:
        response = requests.get(GEOCODE_URL, timeout=20, params={
            "address": text, "components": "country:US|country:CA|country:MX",
            "key": config.GOOGLE_MAPS_API_KEY,
        })
        data = response.json()
    except (requests.RequestException, ValueError) as err:
        raise GoogleError("could not reach Google: " + redact(str(err))[:120]) from None
    _record("geocoding")
    status = data.get("status")
    if status == "ZERO_RESULTS":
        return None
    if status != "OK":
        log.warning("Geocoding answered %s: %s", status, data.get("error_message"))
        raise GoogleError(f"Google geocoding answered {status}")
    best = data["results"][0]
    where = best["geometry"]["location"]
    return {"latitude": float(where["lat"]), "longitude": float(where["lng"]),
            "label": best.get("formatted_address") or text}


# ---------------------------------------------------------------- opening hours

DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
WEEK = 7 * 1440


def _hhmm(minutes):
    return f"{minutes // 60 % 24:02d}:{minutes % 60:02d}"


def open_state(hours, now):
    """('open' | 'closed' | 'unknown', words) from Google regularOpeningHours at `now` (local)."""
    periods = (hours or {}).get("periods") or []
    if not periods:
        return "unknown", "hours not listed"
    if len(periods) == 1 and "close" not in periods[0]:
        return "open", "open 24/7"
    spans = []
    for period in periods:
        start, end = period.get("open"), period.get("close")
        if not start or not end:
            continue
        a = start["day"] * 1440 + start.get("hour", 0) * 60 + start.get("minute", 0)
        b = end["day"] * 1440 + end.get("hour", 0) * 60 + end.get("minute", 0)
        if b <= a:
            b += WEEK
        spans.append((a, b))
    if not spans:
        return "unknown", "hours not listed"
    weekday = (now.weekday() + 1) % 7  # Python Monday=0 → Google Sunday=0
    minute = weekday * 1440 + now.hour * 60 + now.minute
    for a, b in spans:
        for shift in (0, -WEEK):
            if a + shift <= minute < b + shift:
                return "open", f"open until {_hhmm(b % 1440)}"
    opens = min((a for a, _b in spans), key=lambda a: (a - minute) % WEEK) % WEEK
    days_ahead = (opens // 1440 - weekday) % 7
    if days_ahead == 0 and (opens - minute) % WEEK >= 1440:
        days_ahead = 7
    when = "today" if days_ahead == 0 else ("tomorrow" if days_ahead == 1 else DAY_NAMES[opens // 1440])
    return "closed", f"closed, opens {when} {_hhmm(opens % 1440)}"


# ---------------------------------------------------------------- Google Maps links

def _allowed(url):
    host = (urlparse(url).hostname or "").lower()
    return bool(GOOGLE_HOSTS.match(host))


def expand_link(url):
    """Follow a maps.app.goo.gl short link to the full Google Maps URL, never leaving Google."""
    url = url.strip()
    if not re.match(r"^https?://", url):
        url = "https://" + url
    if not _allowed(url):
        raise GoogleError("that is not a Google Maps link")
    for _hop in range(6):
        host = (urlparse(url).hostname or "").lower()
        if host.startswith("consent.google."):
            target = parse_qs(urlparse(url).query).get("continue", [""])[0]
            if not target or not _allowed(target):
                break
            url = target
            continue
        if "/maps" in urlparse(url).path or host.startswith("maps.google."):
            return url
        try:
            response = requests.get(url, allow_redirects=False, timeout=15,
                                    headers={"User-Agent": "Mozilla/5.0 (Kaido link reader)"})
        except requests.RequestException as err:
            raise GoogleError("could not open that link: " + redact(str(err))[:100]) from None
        target = response.headers.get("Location")
        if not target:
            break
        target = urljoin(url, target)
        if not _allowed(target):
            raise GoogleError("that link leads outside Google Maps")
        url = target
    return url


COORD_PAIR = re.compile(r"(-?\d{1,2}(?:\.\d+)?),\s*(-?\d{1,3}(?:\.\d+)?)")


def read_link(url):
    """Name, coordinates and place id out of a Google Maps URL — no API call.

    Returns {"name", "latitude", "longitude", "place_id", "url"}; any of the first four may be None.
    """
    full = expand_link(url)
    parsed = urlparse(full)
    path = unquote_plus(parsed.path)
    query = parse_qs(parsed.query)
    found = {"name": None, "latitude": None, "longitude": None, "place_id": None, "url": full}

    place = re.search(r"/maps/place/([^/@]+)", path)
    if place:
        found["name"] = place.group(1).strip()
    exact = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", full)
    view = re.search(r"/@(-?\d+\.\d+),(-?\d+\.\d+)", path)
    asked = (query.get("query") or query.get("q") or query.get("destination") or [""])[0].strip()
    pair = COORD_PAIR.fullmatch(asked) if asked else None
    if exact:
        found["latitude"], found["longitude"] = float(exact.group(1)), float(exact.group(2))
    elif pair:
        found["latitude"], found["longitude"] = float(pair.group(1)), float(pair.group(2))
    elif view:
        found["latitude"], found["longitude"] = float(view.group(1)), float(view.group(2))
    if asked and not pair and not found["name"]:
        found["name"] = asked
    search = re.search(r"/maps/search/([^/@]+)", path)
    if search and not found["name"]:
        text = search.group(1).strip()
        if not COORD_PAIR.fullmatch(text):
            found["name"] = text
        elif found["latitude"] is None:
            coords = COORD_PAIR.fullmatch(text)
            found["latitude"], found["longitude"] = float(coords.group(1)), float(coords.group(2))
    place_id = (query.get("query_place_id") or query.get("place_id") or [None])[0]
    if place_id:
        found["place_id"] = place_id
    return found


LIST_URL = "https://www.google.com/maps/preview/entitylist/getlist"


def list_id(full_url):
    path = urlparse(full_url).path
    found = re.search(r"/maps/placelists/list/([A-Za-z0-9_-]+)", path) or re.search(r"!11m1!2s([A-Za-z0-9_-]+)", full_url)
    return found.group(1) if found else None


def read_list(full_url, limit=2000):
    """Every place in a shared Google Maps list: name, coordinates, the list owner's note."""
    identifier = list_id(full_url)
    if not identifier:
        return None
    try:
        response = requests.get(
            LIST_URL,
            params={"authuser": "0", "hl": "en", "gl": "us",
                    "pb": f"!1m4!1s{identifier}!2e1!3m1!1e1!2e2!3e2!4i{int(limit)}!16b1"},
            headers={"User-Agent": "Mozilla/5.0 (Kaido link reader)"}, timeout=30,
        )
        response.raise_for_status()
        text = response.text
        data = json.loads(text[text.index("\n") + 1:])[0]
    except (requests.RequestException, ValueError, IndexError) as err:
        raise GoogleError("could not open that list: " + redact(str(err))[:100]) from None
    owner = (data[3] or [None])[0] if len(data) > 3 else None
    title = data[4] if len(data) > 4 else None
    places = []
    for entry in (data[8] if len(data) > 8 and data[8] else []):
        try:
            where = entry[1]
            ids = where[6] if len(where) > 6 else None
            latitude, longitude = float(where[5][2]), float(where[5][3])
        except (TypeError, IndexError, ValueError):
            continue
        if not ids or not ids[1]:
            continue
        cid = int(ids[1]) & 0xFFFFFFFFFFFFFFFF
        places.append({
            "name": (entry[2] or "").replace("\n", " ").strip(),
            "note": (entry[3] or "").strip() or None,
            "latitude": latitude,
            "longitude": longitude,
            "url": f"https://maps.google.com/?cid={cid}",
        })
    return {"owner": owner, "title": title, "places": places, "url": full_url}


def looks_like_link(text):
    text = (text or "").strip().lower()
    return bool(re.match(r"^(https?://)?((www|maps)\.)?(google\.[a-z.]+/maps|maps\.google\.|maps\.app\.goo\.gl|goo\.gl/maps)", text))
