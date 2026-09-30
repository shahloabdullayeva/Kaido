from datetime import date, datetime, timezone

from .db import one, rows
from .work_types import SCHEDULE_KINDS, SCHEDULES, SEVERE_FACTOR


def trucks_with_service(company_id):
    trucks = rows(
        """select t.*,
             d.name as driver_name,
             (select max(m.odometer) from maintenance_orders m
               where m.truck_id = t.id and m.kind = 'oil' and m.status = 'done' and m.odometer is not null) as last_oil_odometer,
             (select max(m.performed_on) from maintenance_orders m
               where m.truck_id = t.id and m.kind = 'oil' and m.status = 'done') as last_oil_on,
             (select count(*) from breakdowns b where b.truck_id = t.id and b.status <> 'resolved') as open_breakdowns,
             (select count(*) from fault_events f where f.truck_id = t.id and f.cleared_at is null) as active_faults,
             (select external_id from vehicle_links v where v.truck_id = t.id limit 1) as samsara_id
           from trucks t
           left join drivers d on d.id = t.driver_id
           where t.company_id = %s
           order by lower(t.unit_number)""",
        (company_id,),
    )
    return attach_last_services(trucks, company_id)


def attach_last_services(trucks, company_id):
    ids = [truck["id"] for truck in trucks]
    latest = {}
    if ids:
        for row in rows(
            """select distinct on (truck_id, kind) truck_id, kind, odometer, performed_on, next_due_odometer, next_due_on
               from maintenance_orders
               where truck_id = any(%s) and status = 'done' and kind = any(%s)
                 and (odometer is not null or performed_on is not null)
               order by truck_id, kind, odometer desc nulls last, performed_on desc nulls last, id desc""",
            (ids, SCHEDULE_KINDS),
        ):
            latest.setdefault(row["truck_id"], {})[row["kind"]] = row
    intervals = company_intervals(company_id)
    for truck in trucks:
        truck["last_service"] = latest.get(truck["id"], {})
        truck["intervals"] = intervals
    return trucks


def company_intervals(company_id):
    saved = {row["kind"]: row for row in rows("select kind, miles, months from service_intervals where company_id = %s", (company_id,))}
    out = {}
    for item in SCHEDULES:
        row = saved.get(item["kind"])
        out[item["kind"]] = {
            "miles": row["miles"] if row else item["miles"],
            "months": row["months"] if row else item["months"],
        }
    return out


def add_months(day, months):
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    for last in (31, 30, 29, 28):
        try:
            return date(year, month, min(day.day, last))
        except ValueError:
            continue


def schedule_status(truck, item):
    interval = (truck.get("intervals") or {}).get(item["kind"]) or {"miles": item["miles"], "months": item["months"]}
    miles = interval["miles"]
    if miles and truck.get("duty_cycle") == "severe":
        miles = int(miles * SEVERE_FACTOR)
    months = interval["months"]
    done = [row for kind, row in (truck.get("last_service") or {}).items() if kind in item["covered_by"]]
    base = {"label": item["label"], "kind": item["kind"], "core": False, "interval_miles": miles, "interval_months": months,
            "last_odometer": None, "last_on": None, "due": None, "due_on": None, "remaining": None, "days": None}
    if not done:
        return dict(base, tone="muted", detail="No record yet")
    last_odometer = max((row["odometer"] for row in done if row["odometer"] is not None), default=None)
    last_on = max((row["performed_on"] for row in done if row["performed_on"] is not None), default=None)
    newest = max(done, key=lambda row: ((row["odometer"] or 0), row["performed_on"] or date.min))
    due = newest["next_due_odometer"] or ((last_odometer + miles) if last_odometer is not None and miles else None)
    due_on = newest["next_due_on"] or (add_months(last_on, months) if last_on and months else None)
    remaining = due - (truck.get("odometer") or 0) if due is not None else None
    days = (due_on - date.today()).days if due_on else None
    tones = []
    if remaining is not None:
        tones.append("bad" if remaining <= 0 else ("warn" if remaining <= max((miles or 0) * 0.1, 1000) else "ok"))
    if days is not None:
        tones.append("bad" if days <= 0 else ("warn" if days <= 30 else "ok"))
    order = {"bad": 0, "warn": 1, "ok": 2}
    tone = min(tones, key=order.get) if tones else "muted"
    parts = []
    if remaining is not None:
        parts.append(f"{abs(remaining):,} mi overdue" if remaining <= 0 else f"{remaining:,} mi to go")
    if days is not None and (tone != "ok" or remaining is None):
        parts.append(f"{abs(days)} days overdue" if days <= 0 else f"{days} days left")
    return dict(base, tone=tone, detail=" · ".join(parts) or "No miles or date on record",
                last_odometer=last_odometer, last_on=last_on, due=due, due_on=due_on, remaining=remaining, days=days)


def service_status(truck):
    items = []
    interval = truck.get("oil_interval_miles") or 25000
    last_oil = truck.get("last_oil_odometer")
    if last_oil is not None:
        due = last_oil + interval
        remaining = due - (truck.get("odometer") or 0)
        items.append({
            "label": "Oil service",
            "core": True,
            "unit": "mi",
            "due": due,
            "remaining": remaining,
            "tone": "bad" if remaining <= 0 else ("warn" if remaining <= interval * 0.1 else "ok"),
            "detail": f"{abs(remaining):,} mi overdue" if remaining <= 0 else f"{remaining:,} mi to go",
        })
    else:
        items.append({"label": "Oil service", "core": True, "due": None, "remaining": None, "tone": "muted", "detail": "No service on record"})

    inspection = truck.get("annual_inspection_on")
    if inspection:
        if isinstance(inspection, datetime):
            inspection = inspection.date()
        due = date(inspection.year + 1, inspection.month, inspection.day) if inspection.month != 2 or inspection.day != 29 else date(inspection.year + 1, 3, 1)
        days = (due - date.today()).days
        items.append({
            "label": "DOT annual",
            "core": True,
            "due": due,
            "remaining": days,
            "tone": "bad" if days <= 0 else ("warn" if days <= 30 else "ok"),
            "detail": f"{abs(days)} days overdue" if days <= 0 else f"{days} days left",
        })
    else:
        items.append({"label": "DOT annual", "core": True, "due": None, "remaining": None, "tone": "muted", "detail": "Not recorded"})
    if "last_service" in truck:
        items.extend(schedule_status(truck, item) for item in SCHEDULES)
    return items


def attention_score(truck):
    statuses = service_status(truck)
    if (truck.get("open_breakdowns") or 0) > 0:
        return 3
    if any(s["tone"] == "bad" for s in statuses):
        return 3
    if (truck.get("active_faults") or 0) > 0:
        return 2
    if any(s["tone"] == "warn" for s in statuses):
        return 1
    return 0


def expiring_documents(company_id, days=45):
    truck_rows = rows(
        """select id, unit_number, registration_expires, insurance_expires
           from trucks
           where company_id = %s and status <> 'sold'
             and (registration_expires <= current_date + %s or insurance_expires <= current_date + %s)""",
        (company_id, days, days),
    )
    driver_rows = rows(
        """select id, name, license_expires, medical_expires
           from drivers
           where company_id = %s and status = 'active'
             and (license_expires <= current_date + %s or medical_expires <= current_date + %s)""",
        (company_id, days, days),
    )
    out = []
    for truck in truck_rows:
        if truck["registration_expires"]:
            out.append({"kind": "Registration", "who": f"Unit {truck['unit_number']}", "href": f"/trucks/{truck['id']}", "on": truck["registration_expires"]})
        if truck["insurance_expires"]:
            out.append({"kind": "Insurance", "who": f"Unit {truck['unit_number']}", "href": f"/trucks/{truck['id']}", "on": truck["insurance_expires"]})
    for driver in driver_rows:
        if driver["license_expires"]:
            out.append({"kind": "Licence", "who": driver["name"], "href": f"/drivers/{driver['id']}", "on": driver["license_expires"]})
        if driver["medical_expires"]:
            out.append({"kind": "Medical card", "who": driver["name"], "href": f"/drivers/{driver['id']}", "on": driver["medical_expires"]})
    cutoff = date.today()
    out = [row for row in out if (row["on"] - cutoff).days <= days]
    return sorted(out, key=lambda row: row["on"])


def company_summary(company_id):
    return one(
        """select
            (select count(*) from trucks where company_id = %(c)s and status = 'active' and not is_outside) as trucks_active,
            (select count(*) from trucks where company_id = %(c)s and status = 'shop' and not is_outside) as trucks_shop,
            (select count(*) from trucks where company_id = %(c)s and status = 'out_of_service' and not is_outside) as trucks_down,
            (select count(*) from drivers where company_id = %(c)s and status = 'active' and not is_outside) as drivers_active,
            (select count(*) from breakdowns where company_id = %(c)s and status <> 'resolved') as breakdowns_open,
            (select count(*) from fault_events where company_id = %(c)s and cleared_at is null) as faults_active,
            (select coalesce(sum(total), 0) from fuel_transactions
              where company_id = %(c)s and purchased_at >= date_trunc('month', now())) as fuel_month,
            (select coalesce(sum(cost), 0) from maintenance_orders
              where company_id = %(c)s and status = 'done' and performed_on >= date_trunc('month', current_date)) as maintenance_month""",
        {"c": company_id},
    )


def fuel_economy(truck_id, limit=12):
    entries = rows(
        """select purchased_at, gallons, odometer, total
           from fuel_transactions
           where truck_id = %s and odometer is not null and fuel_type = 'diesel'
           order by odometer desc limit %s""",
        (truck_id, limit),
    )
    ordered = list(reversed(entries))
    points = []
    for previous, current in zip(ordered, ordered[1:]):
        miles = current["odometer"] - previous["odometer"]
        gallons = float(current["gallons"])
        if 0 < miles < 3000 and gallons > 0:
            points.append({"at": current["purchased_at"], "mpg": miles / gallons})
    if not points:
        return None
    recent = points[-4:]
    return {
        "average": sum(p["mpg"] for p in points) / len(points),
        "latest": sum(p["mpg"] for p in recent) / len(recent),
        "points": points,
    }
