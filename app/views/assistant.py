from flask import Blueprint, g, jsonify, render_template, request

from .. import advisor, forms
from ..auth import login_required
from ..db import execute, one, rows
from ..queries import service_status
from ..tenancy import company_required

bp = Blueprint("assistant", __name__)


def truck_context(truck):
    company_id = g.company["id"]
    last_oil = one(
        """select max(odometer) as odometer, max(performed_on) as performed_on from maintenance_orders
           where truck_id = %s and kind = 'oil' and status = 'done'""",
        (truck["id"],),
    )
    enriched = dict(truck, last_oil_odometer=last_oil["odometer"] if last_oil else None)
    driver = one("select name, phone from drivers where id = %s", (truck["driver_id"],)) if truck["driver_id"] else None
    faults = rows(
        """select dtc_code, spn, fmi, description, lamp, severity, first_seen_at from fault_events
           where truck_id = %s and cleared_at is null order by last_seen_at desc limit 10""",
        (truck["id"],),
    )
    work = rows(
        """select id, kind, status, coalesce(performed_on, scheduled_for) as on_day, odometer, vendor, cost, description
           from maintenance_orders where truck_id = %s
           order by coalesce(performed_on, scheduled_for) desc nulls last, id desc limit 8""",
        (truck["id"],),
    )
    breakdowns = rows(
        """select id, status, occurred_at, description, location from breakdowns
           where truck_id = %s and status <> 'resolved' order by occurred_at desc limit 5""",
        (truck["id"],),
    )
    reminders = rows(
        """select note, remind_at from reminders where company_id = %s and entity = 'truck' and entity_id = %s
           and done_at is null order by remind_at limit 5""",
        (company_id, truck["id"]),
    )
    lines = [
        f"Company: {g.company['name']}",
        f"Truck: unit {truck['unit_number']}, " + " ".join(str(p) for p in [truck.get("year"), truck.get("make"), truck.get("model")] if p),
        f"Outside truck belonging to {truck.get('outside_carrier') or 'another carrier'}" if truck.get("is_outside") else "",
        f"VIN {truck['vin']}" if truck.get("vin") else "",
        f"Engine: {truck['engine']}" if truck.get("engine") else "Engine: not known",
        f"Status: {truck['status'].replace('_', ' ')}; duty cycle {truck['duty_cycle']}",
        f"Odometer: {truck['odometer']:,} miles" if truck.get("odometer") else "Odometer: not recorded",
        f"Last known position: {truck['location']}" if truck.get("location") else "",
        f"Driver: {driver['name']}" + (f", phone {driver['phone']}" if driver and driver["phone"] else "") if driver else "Driver: none assigned",
        "Service status: " + "; ".join(f"{item['label']} {item['detail']}" for item in service_status(enriched)),
        f"Oil interval: {truck.get('oil_interval_miles') or 25000:,} miles",
    ]
    lines.append("Active fault codes:" if faults else "Active fault codes: none")
    for fault in faults:
        code = fault["dtc_code"] or f"SPN {fault['spn']} / FMI {fault['fmi']}"
        lines.append(f"- {code}: {fault['description'] or 'no description'}; lamp {fault['lamp'] or 'none'}; "
                     f"severity {fault['severity']}; since {fault['first_seen_at']:%d %b %Y}")
    lines.append("Recent work orders:" if work else "Work orders: none on record")
    for order in work:
        lines.append(f"- #{order['id']} {order['kind'].replace('_', ' ')} ({order['status'].replace('_', ' ')}), "
                     f"{order['on_day']:%d %b %Y}" if order["on_day"] else f"- #{order['id']} {order['kind']} ({order['status']})")
        extra = ", ".join(part for part in [
            f"{order['odometer']:,} mi" if order["odometer"] else "",
            order["vendor"] or "",
            f"${float(order['cost']):,.2f}" if order["cost"] is not None else "",
            (order["description"] or "")[:160],
        ] if part)
        if extra:
            lines[-1] += f": {extra}"
    for item in breakdowns:
        lines.append(f"Open breakdown #{item['id']} ({item['status'].replace('_', ' ')}) since "
                     f"{item['occurred_at']:%d %b %Y}: {item['description'][:200]}")
    for item in reminders:
        lines.append(f"Reminder set for {item['remind_at']:%d %b %Y}: {item['note'][:160]}")
    return "\n".join(line for line in lines if line)


def scoped(truck_id):
    return one("select * from trucks where id = %s and company_id = %s", (truck_id, g.company["id"]))


def thread(truck_id):
    return rows(
        """select role, content, created_at from ai_chats
           where company_id = %s and user_id = %s and truck_id = %s order by created_at, id""",
        (g.company["id"], g.session["user_id"], truck_id),
    )


@bp.get("/assistant/<int:truck_id>")
@login_required
@company_required
def history(truck_id):
    if not scoped(truck_id):
        return jsonify({"error": "Truck not found."}), 404
    return jsonify({"messages": [{"role": m["role"], "content": m["content"]} for m in thread(truck_id)],
                    "available": advisor.available()})


@bp.post("/assistant/<int:truck_id>")
@login_required
@company_required
def ask(truck_id):
    truck = scoped(truck_id)
    if not truck:
        return jsonify({"error": "Truck not found."}), 404
    question = forms.required(request.form.get("question"), 2000)
    if not question:
        return jsonify({"error": "Type a question first."}), 400
    past = thread(truck_id)
    answer, problem = advisor.chat_reply(truck_context(truck), past, question)
    if problem:
        return jsonify({"error": problem}), 200
    for role, content in (("user", question), ("assistant", answer)):
        execute(
            "insert into ai_chats (company_id, user_id, truck_id, role, content) values (%s, %s, %s, %s, %s)",
            (g.company["id"], g.session["user_id"], truck_id, role, content),
        )
    return jsonify({"answer": answer})


@bp.post("/assistant/<int:truck_id>/clear")
@login_required
@company_required
def clear(truck_id):
    execute("delete from ai_chats where company_id = %s and user_id = %s and truck_id = %s",
            (g.company["id"], g.session["user_id"], truck_id))
    return jsonify({"ok": True})
