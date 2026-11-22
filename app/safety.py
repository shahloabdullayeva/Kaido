import re
from datetime import datetime, timedelta, timezone
from html import escape

from . import config
from .db import execute, one, rows
from .fuel import unit_label
from .logs import get
from .reminders import company_chats, zone_for
from .samsara import SamsaraError
from .sync import client_for
from .telegram import send

log = get("safety")

LOOKBACK_HOURS = 3
BACKFILL_DAYS = 30
ALERT_WITHIN_MINUTES = 90
REPEAT_HOURS = 6
KMH_TO_MPH = 0.621371
ASSET_CHUNK = 50
INSTANT = {"braking", "harshBrake", "harshTurn", "harshAccel", "acceleration", "crash", "rollover",
           "rolloverProtection", "mobileUsage", "noSeatbelt", "drowsy", "drowsiness", "speeding:heavy", "speeding:severe"}
NAMES = {"speeding:light": "Speeding, light", "speeding:moderate": "Speeding", "speeding:heavy": "Speeding, heavy",
         "speeding:severe": "Speeding, severe", "mobileUsage": "Phone use", "noSeatbelt": "No seatbelt",
         "braking": "Harsh braking", "harshBrake": "Harsh braking", "harshTurn": "Harsh turn",
         "harshAccel": "Harsh acceleration", "acceleration": "Harsh acceleration", "crash": "Crash"}


def iso(moment):
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse(text):
    if not text:
        return None
    text = re.sub(r"\.\d+", "", text.replace("Z", "+00:00"))
    return datetime.fromisoformat(text)


def links(company_id):
    return {r["external_id"]: r for r in rows(
        """select v.external_id, t.id as truck_id, t.driver_id from vehicle_links v join trucks t on t.id = v.truck_id
           where v.company_id = %s""", (company_id,))}


def since(company_id, prefix):
    seen = one("select max(happened_at) as at from safety_events where company_id = %s and external_id like %s",
               (company_id, prefix + ":%"))
    if not seen["at"]:
        return datetime.now(timezone.utc) - timedelta(days=BACKFILL_DAYS)
    return datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)


def save(company_id, link, external_id, kind, label, severity, at, ended=None, speed=None, limit=None, g=None,
         lat=None, lon=None, place=None, raw=None):
    import json
    found = one(
        """insert into safety_events (company_id, truck_id, driver_id, external_id, kind, label, severity, happened_at,
             ended_at, speed_mph, limit_mph, g_force, latitude, longitude, place, raw)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           on conflict (company_id, external_id) do nothing returning id""",
        (company_id, link and link["truck_id"], link and link["driver_id"], external_id, kind, label, severity, at, ended,
         speed, limit, g, lat, lon, place, json.dumps(raw) if raw is not None else None),
    )
    return 1 if found else 0


def pull_events(company_id, client, start, linked):
    saved = 0
    end = datetime.now(timezone.utc)
    events = client.paginate("/fleet/safety-events", {"startTime": iso(start), "endTime": iso(end), "limit": 100})
    for event in events:
        link = linked.get(str((event.get("vehicle") or {}).get("id") or ""))
        labels = event.get("behaviorLabels") or [{}]
        first = labels[0]
        location = event.get("location") or {}
        raw = {k: v for k, v in event.items() if "Url" not in k}
        saved += save(company_id, link, f"event:{event['id']}", first.get("label") or "event", first.get("name"),
                      event.get("coachingState"), parse(event.get("time")), g=event.get("maxAccelerationGForce"),
                      lat=location.get("latitude"), lon=location.get("longitude"), raw=raw)
    return saved


def place_of(location):
    address = (location or {}).get("address") or {}
    parts = [address.get("street"), address.get("city"), address.get("state")]
    return ", ".join(p for p in parts if p) or None


def pull_speeding(company_id, client, start, linked):
    saved = 0
    ids = [external for external in linked if external.isdigit()]
    for index in range(0, len(ids), ASSET_CHUNK):
        chunk = ",".join(ids[index:index + ASSET_CHUNK])
        trips = client.paginate("/speeding-intervals/stream", {"startTime": iso(start), "assetIds": chunk, "limit": 100})
        for trip in trips:
            asset = str((trip.get("asset") or {}).get("id") or "")
            for interval in trip.get("intervals") or []:
                if interval.get("isDismissed"):
                    continue
                level = interval.get("severityLevel") or "light"
                location = interval.get("location") or {}
                top = interval.get("maxSpeedKilometersPerHour")
                posted = interval.get("postedSpeedLimitKilometersPerHour")
                saved += save(company_id, linked.get(asset), f"speed:{asset}:{interval.get('startTime')}", f"speeding:{level}",
                              NAMES.get(f"speeding:{level}"), level, parse(interval.get("startTime")),
                              ended=parse(interval.get("endTime")),
                              speed=round(top * KMH_TO_MPH) if top else None,
                              limit=round(posted * KMH_TO_MPH) if posted else None,
                              lat=location.get("latitude"), lon=location.get("longitude"), place=place_of(location),
                              raw=interval)
    return saved


def message(event, company):
    zone = zone_for(company["timezone"])
    when = event["happened_at"].astimezone(zone).strftime("%d %b %H:%M")
    title = NAMES.get(event["kind"]) or event["label"] or event["kind"]
    lines = [f"<b>{escape(title)}</b> · Unit {escape(unit_label(event['unit_number'] or '?'))} · {escape(company['name'])}"]
    if event["driver_name"]:
        lines.append(f"Driver {escape(event['driver_name'])}")
    if event["speed_mph"]:
        lines.append(f"{int(event['speed_mph'])} mph in a {int(event['limit_mph'] or 0)} zone")
    where = event["place"] or (f"{float(event['latitude']):.4f}, {float(event['longitude']):.4f}" if event["latitude"] else None)
    lines.append(" · ".join(p for p in [escape(where) if where else None, when] if p))
    lines.append(f"{config.APP_URL}/safety")
    return "\n".join(lines)


def alert(company):
    fresh = rows(
        """select e.*, t.unit_number, d.name as driver_name from safety_events e
           left join trucks t on t.id = e.truck_id left join drivers d on d.id = e.driver_id
           where e.company_id = %s and e.alerted_at is null and e.kind = any(%s)
             and e.happened_at > now() - make_interval(mins => %s) order by e.happened_at""",
        (company["id"], list(INSTANT), ALERT_WITHIN_MINUTES),
    )
    sent = 0
    for event in fresh:
        recent = one(
            """select 1 from safety_events where company_id = %s and kind = %s and alerted_at is not null
                 and truck_id is not distinct from %s and happened_at > %s""",
            (company["id"], event["kind"], event["truck_id"], event["happened_at"] - timedelta(hours=REPEAT_HOURS)),
        )
        execute("update safety_events set alerted_at = now() where id = %s", (event["id"],))
        if recent:
            continue
        for chat in company_chats(company["id"]):
            send(chat, message(event, company))
        sent += 1
    return sent


def run():
    result = {}
    for company in rows(
        """select c.* from companies c join integrations i on i.company_id = c.id and i.provider = 'samsara'
           where c.status = 'active' and i.credential is not null"""
    ):
        try:
            client, _ = client_for(company["id"])
            linked = links(company["id"])
            events = pull_events(company["id"], client, since(company["id"], "event"), linked)
            speeding = pull_speeding(company["id"], client, since(company["id"], "speed"), linked)
            result[company["name"]] = {"events": events, "speeding": speeding, "alerts": alert(company)}
        except SamsaraError as err:
            log.warning("safety pull failed for %s: %s", company["id"], err)
            result[company["name"]] = {"error": str(err)[:200]}
    return result
