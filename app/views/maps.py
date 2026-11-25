from flask import Blueprint, g, jsonify, request

from .. import forms, shops as shop_search, weather
from ..auth import login_required
from ..db import rows
from ..logs import get
from ..tenancy import company_required

bp = Blueprint("maps", __name__)
log = get("maps")
MAX_POINTS = 400


def bounds():
    values = [forms.decimal(request.args.get(k)) for k in ("south", "west", "north", "east")]
    if any(v is None for v in values):
        return None
    south, west, north, east = values
    return south, west, north, east


@bp.get("/map/weather")
@login_required
@company_required
def weather_shapes():
    response = jsonify(weather.shapes())
    response.headers["Cache-Control"] = "private, max-age=300"
    return response


@bp.get("/map/places")
@login_required
@company_required
def places():
    kind = forms.pick(request.args.get("kind"), ["shops", "towing", "parking", "showers"], None)
    box = bounds()
    if not kind or not box:
        return jsonify({"points": []})
    south, west, north, east = box
    if kind == "shops":
        points = [{"name": r["name"], "lat": float(r["latitude"]), "lon": float(r["longitude"]),
                   "detail": " · ".join(p for p in [r["address"], r["phone"], r["note"]] if p)[:200], "url": r["maps_url"]}
                  for r in rows(
                      """select name, latitude, longitude, address, phone, note, maps_url from saved_shops
                         where company_id = %s and latitude between %s and %s and longitude between %s and %s limit %s""",
                      (g.company["id"], south, north, west, east, MAX_POINTS))]
    elif kind in ("parking", "showers"):
        points = [{"name": r["name"], "lat": float(r["latitude"]), "lon": float(r["longitude"]),
                   "detail": " · ".join(p for p in [", ".join(x for x in [r["city"], r["state"]] if x),
                                                    f"{r['amenities'].get('spaces')} truck spaces" if r["amenities"].get("spaces") else None,
                                                    "showers" if r["amenities"].get("showers") else None] if p)}
                  for r in rows(
                      f"""select name, latitude, longitude, city, state, amenities from fuel_stations
                          where (amenities ->> '{kind if kind == 'showers' else 'parking'}')::boolean
                            and latitude between %s and %s and longitude between %s and %s limit %s""",
                      (south, north, west, east, MAX_POINTS))]
    else:
        zoom = forms.integer(request.args.get("zoom")) or 0
        points = [{"name": r["name"], "lat": float(r["latitude"]), "lon": float(r["longitude"]),
                   "detail": " · ".join(p for p in [r["address"], r["phone"]] if p)[:200], "url": r["maps_url"], "saved": True}
                  for r in rows(
                      """select name, latitude, longitude, address, phone, maps_url from saved_shops
                         where company_id = %s and (name ilike '%%tow%%' or coalesce(note, '') ilike '%%tow%%')
                           and latitude between %s and %s and longitude between %s and %s limit %s""",
                      (g.company["id"], south, north, west, east, MAX_POINTS))]
        if zoom >= 8:
            try:
                found, _meta = shop_search.nearby((south + north) / 2, (west + east) / 2, radius_miles=40, limit=60, need="tow")
                points += [{"name": s.get("name") or "Towing", "lat": float(s["latitude"]), "lon": float(s["longitude"]),
                            "detail": " · ".join(p for p in [s.get("address"), s.get("phone")] if p)[:200],
                            "url": shop_search.maps_link(s)} for s in found[:80] if s.get("latitude") is not None]
            except Exception as err:
                log.warning("towing lookup failed: %s", err)
    return jsonify({"points": points[:MAX_POINTS]})
