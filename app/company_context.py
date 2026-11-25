from datetime import datetime, timezone

from . import live, work_types
from .db import one, rows
from .queries import attention_score, service_status, trucks_with_service


def _day(value):
    return f"{value:%d %b}" if value else "-"


def _spell(minutes):
    if minutes is None:
        return ""
    return f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{minutes} min"


DUTY = {"DS_D": "driving", "DS_ON": "on duty", "DS_OFF": "off duty", "DS_SB": "sleeper"}


def _ms(value):
    if value is None:
        return "-"
    minutes = int(value) // 60000
    return f"{minutes // 60}:{minutes % 60:02d}"


def build(company):
    company_id = company["id"]
    now = datetime.now(timezone.utc)
    fleet = [t for t in trucks_with_service(company_id) if not t["is_outside"]]
    state = live.status(company_id)
    faults = {r["truck_id"]: r["n"] for r in rows(
        "select truck_id, count(*) as n from fault_events where company_id = %s and cleared_at is null group by truck_id",
        (company_id,))}
    lines = [f"Company: {company['name']}. Today is {now:%a %d %b %Y} (UTC).",
             f"Trucks ({len(fleet)}): unit | group | status | driver | where | now | fuel | odometer | faults | service"]
    for t in sorted(fleet, key=lambda t: -attention_score(t)):
        s = state.get(t["id"]) or {}
        if s.get("moving"):
            now_text = f"moving {s.get('speed') or 0} mph"
        elif s.get("engine") == "Idle":
            now_text = f"idling {_spell(s.get('idle_minutes'))}"
        elif s.get("parked_minutes") is not None:
            now_text = f"parked {_spell(s.get('parked_minutes'))}"
        else:
            now_text = "-"
        due = "; ".join(f"{i['label']} {i['detail']}" for i in service_status(t) if i.get("tone") in ("bad", "warn")) or "ok"
        weather = ", ".join(w["event"] for w in s.get("weather") or [])
        lines.append(" | ".join(str(x) for x in [
            t["unit_number"], t.get("carrier_group") or "-", t["status"].replace("_", " "), t.get("driver_name") or "no driver",
            (t.get("location") or "-")[:60], now_text + (f", weather: {weather}" if weather else ""),
            f"{int(t['fuel_percent'])}%" if t.get("fuel_percent") is not None else "-",
            f"{t['odometer']:,}" if t.get("odometer") else "-", faults.get(t["id"], 0), due]))

    orders = rows(
        """select m.id, m.kind, m.status, m.priority, m.breakdown, m.vendor, m.reported_at, m.scheduled_for, m.description,
                  coalesce(t.unit_number, tr.unit_number) as unit
           from maintenance_orders m left join trucks t on t.id = m.truck_id left join trailers tr on tr.id = m.trailer_id
           where m.company_id = %s and m.status not in ('done', 'cancelled') order by m.reported_at desc limit 25""",
        (company_id,))
    lines.append(f"Open work orders ({len(orders)}):" if orders else "Open work orders: none")
    for o in orders:
        lines.append(f"- #{o['id']} unit {o['unit']}: {work_types.label(o['kind'])}, {o['status'].replace('_', ' ')}, "
                     f"{o['priority']}{', breakdown' if o['breakdown'] else ''}, reported {_day(o['reported_at'])}"
                     f"{', scheduled ' + _day(o['scheduled_for']) if o['scheduled_for'] else ''}"
                     f"{', shop ' + o['vendor'] if o['vendor'] else ''}: {(o['description'] or '')[:120]}")

    done = one("""select count(*) as n, coalesce(sum(cost), 0) as cost from maintenance_orders
                  where company_id = %s and status = 'done' and performed_on >= date_trunc('month', now())""", (company_id,))
    fuel = one("""select count(*) as n, coalesce(sum(gallons), 0) as gallons, coalesce(sum(total), 0) as total
                  from fuel_transactions where company_id = %s and purchased_at >= date_trunc('month', now())""", (company_id,))
    lines.append(f"This month: {done['n']} work orders done (${float(done['cost']):,.2f}); fuel {fuel['n']} purchases, "
                 f"{float(fuel['gallons']):,.0f} gal, ${float(fuel['total']):,.2f}.")

    fault_rows = rows(
        """select t.unit_number, f.dtc_code, f.spn, f.fmi, f.description, f.severity from fault_events f
           join trucks t on t.id = f.truck_id where f.company_id = %s and f.cleared_at is null
           order by f.severity = 'high' desc, f.last_seen_at desc limit 25""", (company_id,))
    if fault_rows:
        lines.append("Active fault codes (latest 25):")
        for f in fault_rows:
            code = f["dtc_code"] or f"SPN {f['spn']} FMI {f['fmi']}"
            lines.append(f"- {f['unit_number']}: {code} {(f['description'] or '')[:80]} ({f['severity']})")

    health = rows(
        """select t.unit_number, h.kind, h.detail, h.opened_at from health_alerts h join trucks t on t.id = h.truck_id
           where h.company_id = %s and h.cleared_at is null order by h.opened_at desc limit 20""", (company_id,))
    if health:
        lines.append("Open truck health alerts:")
        lines += [f"- {h['unit_number']}: {h['kind'].replace('_', ' ')} {(h['detail'] or '')[:80]} since {_day(h['opened_at'])}" for h in health]

    safety = rows(
        """select coalesce(d.name, t.unit_number) as who, s.label, count(*) as n from safety_events s
           left join drivers d on d.id = s.driver_id left join trucks t on t.id = s.truck_id
           where s.company_id = %s and s.happened_at > now() - interval '7 days'
           group by 1, 2 order by n desc limit 15""", (company_id,))
    if safety:
        lines.append("Safety events, last 7 days (driver: kind x count): " +
                     "; ".join(f"{s['who']}: {s['label']} x{s['n']}" for s in safety))

    hours = rows(
        """select d.name, h.duty_status, h.drive_remaining, h.shift_remaining, h.cycle_remaining from hos_status h
           join drivers d on d.id = h.driver_id where h.company_id = %s and h.duty_status is not null
           order by h.drive_remaining nulls last limit 30""", (company_id,))
    if hours:
        lines.append("Hours of service (driver: status, drive / shift / cycle left in h:mm): " + "; ".join(
            f"{h['name']}: {DUTY.get(h['duty_status'], h['duty_status'])}, {_ms(h['drive_remaining'])} / {_ms(h['shift_remaining'])} / {_ms(h['cycle_remaining'])}"
            for h in hours))

    trips = rows(
        """select t.unit_number, p.load_number, p.status, p.distance_miles from trips p join trucks t on t.id = p.truck_id
           where p.company_id = %s and p.status in ('sent', 'accepted') order by p.id desc limit 10""", (company_id,))
    if trips:
        lines.append("Active trips: " + "; ".join(f"{p['unit_number']} load {p['load_number'] or '-'} ({p['status']}, "
                                                   f"{int(p['distance_miles'] or 0)} mi)" for p in trips))

    docs = rows(
        """select title, kind, expires_on, coalesce(dr.name, t.unit_number) as owner from documents d
           left join drivers dr on dr.id = d.driver_id left join trucks t on t.id = d.truck_id
           where d.company_id = %s and d.expires_on < now() + interval '45 days' order by d.expires_on limit 15""", (company_id,))
    if docs:
        lines.append("Documents expiring or expired: " + "; ".join(f"{d['owner']} {d['title'] or d['kind']} {_day(d['expires_on'])}" for d in docs))

    recalls = one("""select count(*) as n, count(distinct truck_id) as trucks from vehicle_recalls
                     where company_id = %s and status not in ('done', 'not_applicable')""", (company_id,))
    if recalls and recalls["n"]:
        lines.append(f"Possible open recalls: {recalls['n']} on {recalls['trucks']} trucks (by make/model/year, not confirmed by VIN).")
    return "\n".join(lines)
