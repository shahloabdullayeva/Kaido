import difflib
import json

import requests

from .db import execute, one, rows
from .logs import get

log = get("places")
PHOTON_URL = "https://photon.komoot.io/api/"
USER_AGENT = "Kaido/1.0 fleet maintenance (+https://kaidofleet.com)"
CACHE_DAYS = 30
LIMIT = 7
STATES = {
    "AL": ("Alabama", 32.8, -86.8), "AK": ("Alaska", 61.4, -152.3), "AZ": ("Arizona", 34.2, -111.7),
    "AR": ("Arkansas", 34.9, -92.4), "CA": ("California", 36.8, -119.4), "CO": ("Colorado", 39.0, -105.5),
    "CT": ("Connecticut", 41.6, -72.7), "DE": ("Delaware", 39.0, -75.5), "FL": ("Florida", 28.6, -82.4),
    "GA": ("Georgia", 32.7, -83.4), "HI": ("Hawaii", 20.8, -156.3), "ID": ("Idaho", 44.4, -114.6),
    "IL": ("Illinois", 40.0, -89.2), "IN": ("Indiana", 39.9, -86.3), "IA": ("Iowa", 42.0, -93.5),
    "KS": ("Kansas", 38.5, -98.4), "KY": ("Kentucky", 37.5, -85.3), "LA": ("Louisiana", 31.1, -92.0),
    "ME": ("Maine", 45.4, -69.2), "MD": ("Maryland", 39.0, -76.8), "MA": ("Massachusetts", 42.3, -71.8),
    "MI": ("Michigan", 44.3, -85.4), "MN": ("Minnesota", 46.3, -94.3), "MS": ("Mississippi", 32.7, -89.7),
    "MO": ("Missouri", 38.4, -92.5), "MT": ("Montana", 47.0, -109.6), "NE": ("Nebraska", 41.5, -99.8),
    "NV": ("Nevada", 39.3, -116.6), "NH": ("New Hampshire", 43.7, -71.6), "NJ": ("New Jersey", 40.2, -74.7),
    "NM": ("New Mexico", 34.4, -106.1), "NY": ("New York", 42.9, -75.5), "NC": ("North Carolina", 35.6, -79.4),
    "ND": ("North Dakota", 47.5, -100.5), "OH": ("Ohio", 40.3, -82.8), "OK": ("Oklahoma", 35.6, -97.5),
    "OR": ("Oregon", 43.9, -120.6), "PA": ("Pennsylvania", 40.9, -77.8), "RI": ("Rhode Island", 41.7, -71.5),
    "SC": ("South Carolina", 33.9, -80.9), "SD": ("South Dakota", 44.4, -100.2), "TN": ("Tennessee", 35.9, -86.4),
    "TX": ("Texas", 31.5, -99.3), "UT": ("Utah", 39.3, -111.7), "VT": ("Vermont", 44.1, -72.7),
    "VA": ("Virginia", 37.5, -78.9), "WA": ("Washington", 47.4, -120.5), "WV": ("West Virginia", 38.6, -80.6),
    "WI": ("Wisconsin", 44.6, -89.9), "WY": ("Wyoming", 43.0, -107.6),
}
STATE_NAMES = {name.lower(): code for code, (name, _lat, _lon) in STATES.items()}


def _state(code):
    name, lat, lon = STATES[code]
    return {"label": name, "detail": "state", "lat": lat, "lon": lon}


def state_matches(text):
    low = text.lower().strip()
    found = []
    if len(low) == 2 and low.upper() in STATES:
        found.append(low.upper())
    for name, code in STATE_NAMES.items():
        if code not in found and len(low) >= 2 and name.startswith(low):
            found.append(code)
    close = []
    if not found and len(low) >= 4:
        close = [STATE_NAMES[name] for name in difflib.get_close_matches(low, STATE_NAMES, n=2, cutoff=0.72)]
    return [_state(code) for code in found[:3]], [_state(code) for code in close]


def known_cities():
    return rows(
        """select city, state, avg(latitude)::float as lat, avg(longitude)::float as lon from fuel_stations
           where city is not null and city <> '' group by city, state"""
    )


def corrected(text):
    words = text.split()
    if not words:
        return text
    names = {}
    for row in known_cities():
        names.setdefault(row["city"].lower(), row["city"])
    names.update({name: STATES[code][0] for name, code in STATE_NAMES.items()})
    fixed = []
    for word in words:
        low = word.lower().strip(",")
        if len(low) >= 4 and low not in names:
            close = difflib.get_close_matches(low, [n for n in names if " " not in n], n=1, cutoff=0.8)
            fixed.append(names[close[0]] if close else word)
        else:
            fixed.append(word)
    return " ".join(fixed)


def _photon(text):
    key = "photon:" + text.lower()
    cached = one("select results from place_suggestions where query = %s and fetched_at > now() - make_interval(days => %s)",
                 (key, CACHE_DAYS))
    if cached:
        return cached["results"]
    try:
        response = requests.get(PHOTON_URL, params={"q": text, "limit": 10, "lang": "en", "bbox": "-171,17,-50,72"},
                                headers={"User-Agent": USER_AGENT}, timeout=6)
        response.raise_for_status()
        features = response.json().get("features") or []
    except (requests.RequestException, ValueError) as err:
        log.warning("place search %r failed: %s", text, err)
        return []
    results = []
    for feature in features:
        props = feature.get("properties") or {}
        if props.get("countrycode") not in ("US", "CA", "MX"):
            continue
        lon, lat = (feature.get("geometry") or {}).get("coordinates") or (None, None)
        if lat is None:
            continue
        street = " ".join(p for p in [props.get("housenumber"), props.get("street")] if p)
        place = props.get("city") or props.get("county")
        detail = ", ".join(p for p in [street if street != props.get("name") else None, place if place != props.get("name") else None,
                                       props.get("state")] if p)
        if props.get("osm_key") == "place" and props.get("osm_value") in ("state", "country"):
            continue
        rank = 0 if props.get("osm_key") == "place" else 1
        results.append({"label": props.get("name") or street or place or "", "detail": detail, "lat": lat, "lon": lon,
                        "rank": rank})
    results.sort(key=lambda item: item["rank"])
    execute(
        """insert into place_suggestions (query, results, fetched_at) values (%s, %s, now())
           on conflict (query) do update set results = excluded.results, fetched_at = now()""",
        (key, json.dumps(results)),
    )
    return results


def suggest(text):
    text = " ".join((text or "").split())[:120]
    if len(text) < 2:
        return []
    found, close = state_matches(text)
    remote = _photon(text) if len(text) >= 3 else []
    if len(text) >= 4:
        fixed = corrected(text)
        if fixed.lower() != text.lower():
            remote = _photon(fixed) + remote
    remote = sorted(remote, key=lambda item: item.get("rank", 1))
    seen = {(item["label"], item.get("detail")) for item in found}
    for item in remote:
        mark = (item["label"], item.get("detail"))
        if item["label"] and mark not in seen:
            seen.add(mark)
            found.append(item)
    for item in close:
        if (item["label"], item["detail"]) not in seen:
            found.insert(min(len(found), 3), item)
    return found[:LIMIT]
