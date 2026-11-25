from datetime import datetime, timedelta, timezone

from . import weather
from .db import rows

MOVING_MPH = 5


def status(company_id):
    now = datetime.now(timezone.utc)
    speeds = {r["truck_id"]: r for r in rows(
        """select distinct on (p.truck_id) p.truck_id, p.speed_mph, p.recorded_at from truck_positions p
           join trucks t on t.id = p.truck_id where t.company_id = %s and p.recorded_at > now() - interval '1 day'
           order by p.truck_id, p.recorded_at desc""", (company_id,))}
    engines = {r["truck_id"]: r for r in rows(
        """select truck_id, state, started_at from engine_sessions where company_id = %s and ended_at is null""", (company_id,))}
    moved = {r["truck_id"]: r["at"] for r in rows(
        """select p.truck_id, max(p.recorded_at) as at from truck_positions p join trucks t on t.id = p.truck_id
           where t.company_id = %s and p.speed_mph >= %s and p.recorded_at > now() - interval '30 days' group by 1""",
        (company_id, MOVING_MPH))}
    storms = weather.for_trucks(company_id)
    out = {}
    for truck_id in set(speeds) | set(engines) | set(storms) | set(moved):
        position = speeds.get(truck_id)
        engine = engines.get(truck_id)
        fresh = position and position["recorded_at"] > now - timedelta(minutes=45)
        speed = float(position["speed_mph"]) if fresh and position["speed_mph"] is not None else None
        moving = speed is not None and speed >= MOVING_MPH
        state = engine["state"] if engine else None
        out[truck_id] = {
            "speed": round(speed) if speed is not None else None,
            "moving": moving,
            "engine": state,
            "idle_minutes": int((now - engine["started_at"]).total_seconds() // 60) if state == "Idle" else None,
            "parked_minutes": int((now - moved[truck_id]).total_seconds() // 60) if not moving and truck_id in moved else None,
            "running": moving or state in ("On", "Idle"),
            "weather": storms.get(truck_id, []),
        }
    return out


def spell(minutes):
    if minutes is None:
        return None
    if minutes < 60:
        return f"{minutes} min"
    if minutes < 48 * 60:
        return f"{minutes // 60} h {minutes % 60} min"
    return f"{minutes // 1440} days"
