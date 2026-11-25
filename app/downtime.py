from datetime import datetime, timedelta, timezone

from .db import execute, one, rows

DOWN_STATUSES = ("towing", "in_shop")
MOVING_MPH = 5
GRACE = "30 minutes"


def on_status(order, new_status):
    if new_status in DOWN_STATUSES:
        execute("""update maintenance_orders set down_started_at = coalesce(down_started_at, now()),
                     down_ended_at = null, down_end_reason = null where id = %s""", (order["id"],))
    elif new_status in ("done", "cancelled"):
        execute("""update maintenance_orders set down_ended_at = coalesce(down_ended_at, now()),
                     down_end_reason = coalesce(down_end_reason, %s) where id = %s and down_started_at is not null""",
                (new_status, order["id"]))


def on_create(order):
    if order.get("breakdown") or order.get("status") in DOWN_STATUSES:
        execute("update maintenance_orders set down_started_at = coalesce(down_started_at, reported_at) where id = %s",
                (order["id"],))


def refresh(company_id=None):
    clause = " and m.company_id = %s" if company_id else ""
    execute(
        f"""update maintenance_orders m set down_ended_at = moved.at, down_end_reason = 'moving'
            from (select m2.id, (select min(p.recorded_at) from truck_positions p
                                 where p.truck_id = m2.truck_id and p.speed_mph >= {MOVING_MPH}
                                   and p.recorded_at > m2.down_started_at + interval '{GRACE}') as at
                  from maintenance_orders m2
                  where m2.down_started_at is not null and m2.down_ended_at is null and m2.truck_id is not null
                    and m2.asset_type = 'truck') moved
            where moved.id = m.id and moved.at is not null{clause}""",
        (company_id,) if company_id else (),
    )


def days(order):
    start = order.get("down_started_at")
    if not start:
        return None
    end = order.get("down_ended_at") or datetime.now(timezone.utc)
    return max(0.0, (end - start).total_seconds() / 86400)


SPAN = """greatest(0, extract(epoch from least(coalesce(m.down_ended_at, now()), %(end)s) - greatest(m.down_started_at, %(start)s))) / 86400.0"""


def truck_totals(truck_id):
    now = datetime.now(timezone.utc)
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    out = {}
    for label, start in (("month", month), ("days90", now - timedelta(days=90))):
        row = one(
            f"""select coalesce(sum({SPAN}), 0) as d from maintenance_orders m
                where m.truck_id = %(truck)s and m.asset_type = 'truck' and m.down_started_at is not null
                  and m.down_started_at < %(end)s and coalesce(m.down_ended_at, now()) > %(start)s""",
            {"truck": truck_id, "start": start, "end": now},
        )
        out[label] = float(row["d"])
    return out


def ranking(company_id, days_back=90, limit=8):
    now = datetime.now(timezone.utc)
    return rows(
        f"""select t.id, t.unit_number, t.carrier_group, sum({SPAN}) as days, count(*) as orders,
                   bool_or(m.down_ended_at is null) as down_now
            from maintenance_orders m join trucks t on t.id = m.truck_id
            where m.company_id = %(company)s and m.asset_type = 'truck' and m.down_started_at is not null
              and m.down_started_at < %(end)s and coalesce(m.down_ended_at, now()) > %(start)s
            group by t.id, t.unit_number, t.carrier_group
            having sum({SPAN}) > 0.01
            order by days desc limit %(limit)s""",
        {"company": company_id, "start": now - timedelta(days=days_back), "end": now, "limit": limit},
    )
