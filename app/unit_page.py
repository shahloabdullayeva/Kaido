from datetime import date, datetime, timedelta, timezone

from . import documents, work_orders
from .db import one, rows

MOVING_MPH = 5
PTI_DAYS = 10
SAFETY_HIDDEN = ("speeding:light",)


def position(truck):
    if truck.get("latitude") is None:
        return None
    last = one(
        """select speed_mph, recorded_at from truck_positions where truck_id = %s
           order by recorded_at desc limit 1""",
        (truck["id"],),
    )
    moved = one(
        """select max(recorded_at) as at from truck_positions where truck_id = %s and speed_mph >= %s
             and recorded_at > now() - interval '30 days'""",
        (truck["id"], MOVING_MPH),
    )
    speed = float(last["speed_mph"]) if last and last["speed_mph"] is not None else None
    moving = speed is not None and speed >= MOVING_MPH and last["recorded_at"] > datetime.now(timezone.utc) - timedelta(minutes=45)
    parked_since = None if moving else (moved["at"] if moved else None)
    return {"lat": float(truck["latitude"]), "lon": float(truck["longitude"]), "where": truck.get("location"),
            "at": truck.get("located_at"), "speed": speed, "moving": moving, "parked_since": parked_since}


def parked_for(since):
    if not since:
        return None
    minutes = int((datetime.now(timezone.utc) - since).total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} h {minutes % 60} min"
    return f"{hours // 24} days"


def truck_section(company_id, truck):
    open_orders = rows(
        f"""select m.*, {work_orders.UNIT_COL} as unit_number,
                   (select count(*) from work_order_comments c where c.order_id = m.id and c.kind = 'comment') as comments
            from maintenance_orders m {work_orders.UNIT_JOIN}
            where m.truck_id = %s and m.status not in ('done', 'cancelled')
            order by m.reported_at desc""",
        (truck["id"],),
    )
    recent = rows(
        """select * from maintenance_orders where truck_id = %s and status in ('done', 'cancelled')
           order by coalesce(performed_on, scheduled_for, reported_at::date) desc, id desc limit 10""",
        (truck["id"],),
    )
    faults = rows(
        """select * from fault_events where truck_id = %s and cleared_at is null
           order by last_seen_at desc limit 10""",
        (truck["id"],),
    )
    alerts = rows(
        """select * from health_alerts where truck_id = %s and kind not like 'hos%%'
           order by opened_at desc limit 10""",
        (truck["id"],),
    )
    return {"open_orders": open_orders, "recent_orders": recent, "faults": faults, "alerts": alerts,
            "position": position(truck),
            "drivers": rows(
                """select a.*, d.name from driver_assignments a join drivers d on d.id = a.driver_id
                   where a.truck_id = %s order by coalesce(a.ended_at, now()) desc limit 10""",
                (truck["id"],),
            )}


def paper(company_id, driver_id, kind):
    doc = one(
        """select * from documents where company_id = %s and owner = 'driver' and driver_id = %s and kind = %s
           order by expires_on desc nulls last, id desc limit 1""",
        (company_id, driver_id, kind),
    )
    if not doc:
        return {"state": "missing"}
    if doc["expires_on"] is None:
        return {"state": "on file", "doc": doc}
    left = (doc["expires_on"] - date.today()).days
    return {"state": "expired" if left < 0 else ("soon" if left <= documents.SOON_DAYS else "ok"), "doc": doc, "left": left}


def pti_days(company_id, driver):
    today = date.today()
    start = today - timedelta(days=PTI_DAYS - 1)
    done = {}
    for row in rows(
        """select i.id, i.submitted_at::date as day, i.defect_count, i.ai_status, i.certified_at, t.unit_number
           from inspections i left join trucks t on t.id = i.truck_id
           where i.company_id = %s and i.submitted_at::date >= %s
             and (i.driver_id = %s or (i.driver_id is null and lower(i.driver_name) = lower(%s)))
           order by i.submitted_at""",
        (company_id, start, driver["id"], driver["name"]),
    ):
        done.setdefault(row["day"], row)
    drove = {row["day"] for row in rows(
        """select distinct p.recorded_at::date as day from truck_positions p
           join driver_assignments a on a.truck_id = p.truck_id and a.driver_id = %s
             and p.recorded_at >= a.started_at - interval '1 day' and p.recorded_at <= coalesce(a.ended_at, now())
           where p.recorded_at::date >= %s and p.speed_mph >= %s""",
        (driver["id"], start, MOVING_MPH),
    )}
    days = []
    for offset in range(PTI_DAYS):
        day = today - timedelta(days=offset)
        item = done.get(day)
        state = "done" if item else ("missing" if day in drove else "off")
        days.append({"day": day, "state": state, "pti": item})
    return days


def fuel_with_suggestions(driver_id):
    purchases = rows(
        """select f.*, t.unit_number, o.id as offer_id, o.followed, s.name as suggested_name,
                  (f.raw ->> 'demo') is not null as demo
           from fuel_transactions f join trucks t on t.id = f.truck_id
           left join lateral (
             select * from fuel_offers o where o.transaction_id = f.id
                or (o.driver_id = f.driver_id and o.created_at between f.purchased_at - interval '24 hours' and f.purchased_at)
             order by (o.transaction_id = f.id) desc, o.created_at desc limit 1) o on true
           left join fuel_stations s on s.id = o.chosen_station_id
           where f.driver_id = %s and f.fuel_type = 'diesel'
           order by f.purchased_at desc limit 10""",
        (driver_id,),
    )
    return purchases


def driver_section(company_id, driver):
    driver_id = driver["id"]
    return {
        "driver": driver,
        "cdl": paper(company_id, driver_id, "cdl"),
        "medical": paper(company_id, driver_id, "medical"),
        "hours": rows(
            """select a.*, t.unit_number from health_alerts a join trucks t on t.id = a.truck_id
               where a.driver_id = %s and a.kind like 'hos%%' order by a.opened_at desc limit 10""",
            (driver_id,),
        ),
        "safety": rows(
            """select e.*, t.unit_number from safety_events e left join trucks t on t.id = e.truck_id
               where e.driver_id = %s and e.kind <> all(%s) order by e.happened_at desc limit 10""",
            (driver_id, list(SAFETY_HIDDEN)),
        ),
        "pti": pti_days(company_id, driver),
        "fuel": fuel_with_suggestions(driver_id),
        "trucks": rows(
            """select a.truck_id, t.unit_number, min(a.started_at) as first_at,
                      case when bool_or(a.ended_at is null) then null else max(a.ended_at) end as last_at
               from driver_assignments a join trucks t on t.id = a.truck_id
               where a.driver_id = %s group by a.truck_id, t.unit_number
               order by bool_or(a.ended_at is null) desc, max(coalesce(a.ended_at, now())) desc limit 10""",
            (driver_id,),
        ),
        "telegram": driver.get("telegram_username") or driver.get("telegram_user_id"),
    }


def last_truck(driver_id):
    return one(
        """select t.id, t.unit_number, a.ended_at from driver_assignments a join trucks t on t.id = a.truck_id
           where a.driver_id = %s order by coalesce(a.ended_at, now()) desc limit 1""",
        (driver_id,),
    )
