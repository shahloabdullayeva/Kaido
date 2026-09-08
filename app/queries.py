from datetime import date, datetime, timezone

from .db import one, rows


def trucks_with_service(company_id):
    return rows(
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


def service_status(truck):
    items = []
    interval = truck.get("oil_interval_miles") or 25000
    last_oil = truck.get("last_oil_odometer")
    if last_oil is not None:
        due = last_oil + interval
        remaining = due - (truck.get("odometer") or 0)
        items.append({
            "label": "Oil service",
            "due": due,
            "remaining": remaining,
            "tone": "bad" if remaining <= 0 else ("warn" if remaining <= interval * 0.1 else "ok"),
            "detail": f"{abs(remaining):,} mi overdue" if remaining <= 0 else f"{remaining:,} mi to go",
        })
    else:
        items.append({"label": "Oil service", "due": None, "remaining": None, "tone": "muted", "detail": "No service on record"})

    inspection = truck.get("annual_inspection_on")
    if inspection:
        if isinstance(inspection, datetime):
            inspection = inspection.date()
        due = date(inspection.year + 1, inspection.month, inspection.day) if inspection.month != 2 or inspection.day != 29 else date(inspection.year + 1, 3, 1)
        days = (due - date.today()).days
        items.append({
            "label": "DOT annual",
            "due": due,
            "remaining": days,
            "tone": "bad" if days <= 0 else ("warn" if days <= 30 else "ok"),
            "detail": f"{abs(days)} days overdue" if days <= 0 else f"{days} days left",
        })
    else:
        items.append({"label": "DOT annual", "due": None, "remaining": None, "tone": "muted", "detail": "Not recorded"})
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
            (select count(*) from trucks where company_id = %(c)s and status = 'active') as trucks_active,
            (select count(*) from trucks where company_id = %(c)s and status = 'shop') as trucks_shop,
            (select count(*) from trucks where company_id = %(c)s and status = 'out_of_service') as trucks_down,
            (select count(*) from drivers where company_id = %(c)s and status = 'active') as drivers_active,
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
