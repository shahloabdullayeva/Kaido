import re
from datetime import date, datetime, timedelta, timezone

from .db import execute, one, rows
from .work_types import group_of

SKIP_GROUPS = {"pm", "compliance", "road"}
GENERIC_KINDS = {"repair", "other"}
STOP = {"the", "a", "an", "and", "or", "on", "in", "at", "to", "of", "for", "with", "is", "was", "it", "truck", "trailer",
        "unit", "repair", "replaced", "replace", "fix", "fixed", "check", "checked", "new", "done", "work", "needs", "need",
        "shop", "driver", "says", "said", "from", "by", "has", "had", "not", "no", "yes", "pm", "am"}
PHRASES = ["air leak", "oil leak", "coolant leak", "fuel leak", "check engine", "no start", "dpf", "def", "egr", "turbo",
           "starter", "alternator", "battery", "brake", "abs", "clutch", "transmission", "radiator", "water pump",
           "injector", "mud flap", "mudflap", "light", "tire", "rim", "hub", "seal", "bearing", "kingpin", "air bag",
           "airbag", "suspension", "slack", "chamber", "compressor", "dryer", "wiper", "door", "mirror", "reefer"]
POSITIONS = ["steer", "drive", "trailer", "left", "right", "front", "rear", "inside", "outside", "inner", "outer"]


def words(text):
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in STOP and len(w) > 2}


def phrases(text):
    low = (text or "").lower()
    return {p for p in PHRASES if p in low}


def similar(a, b):
    shared_phrases = phrases(a) & phrases(b)
    if shared_phrases:
        if {"tire", "rim", "hub"} & shared_phrases:
            pos_a = {p for p in POSITIONS if p in (a or "").lower()}
            pos_b = {p for p in POSITIONS if p in (b or "").lower()}
            if pos_a and pos_b and not (pos_a & pos_b):
                return None
        return "similar description (" + ", ".join(sorted(shared_phrases)) + ")"
    wa, wb = words(a), words(b)
    shared = wa & wb
    if len(shared) >= 2 and len(shared) / max(len(wa | wb), 1) >= 0.5:
        return "similar description"
    return None


def reason_for(order, earlier):
    kind, other = order["kind"], earlier["kind"]
    if group_of(kind) in SKIP_GROUPS or group_of(other) in SKIP_GROUPS:
        return similar(order["description"], earlier["description"]) if kind in GENERIC_KINDS or other in GENERIC_KINDS else None
    if kind == other and kind not in GENERIC_KINDS:
        return "same work type"
    group = group_of(kind)
    if group and group == group_of(other) and group != "other":
        return "same system"
    return similar(order["description"], earlier["description"])


def when(order):
    if order["performed_on"]:
        return order["performed_on"]
    return order["reported_at"].date() if order["reported_at"] else date.today()


def check(order_id):
    order = one("select m.*, c.comeback_days from maintenance_orders m join companies c on c.id = m.company_id where m.id = %s",
                (order_id,))
    if not order or order["status"] == "cancelled":
        return 0
    days = order["comeback_days"] or 60
    on = when(order)
    unit_col, unit_id = ("trailer_id", order["trailer_id"]) if order["asset_type"] == "trailer" else ("truck_id", order["truck_id"])
    earlier = rows(
        f"""select * from maintenance_orders where {unit_col} = %s and id <> %s and status = 'done'
              and coalesce(performed_on, reported_at::date) between %s and %s
              and (coalesce(performed_on, reported_at::date) < %s or id < %s)""",
        (unit_id, order_id, on - timedelta(days=days), on, on, order_id),
    )
    found = 0
    for item in earlier:
        reason = reason_for(order, item)
        if not reason:
            continue
        execute(
            """insert into maintenance_comebacks (company_id, order_id, earlier_id, reason) values (%s, %s, %s, %s)
               on conflict (order_id, earlier_id) do nothing""",
            (order["company_id"], order_id, item["id"], reason),
        )
        found += 1
    return found


def flags_for(order_id):
    return rows(
        """select c.*, m.id as earlier_number, m.vendor, m.performed_on, m.reported_at, m.kind, m.description
           from maintenance_comebacks c join maintenance_orders m on m.id = c.earlier_id
           where c.order_id = %s order by c.dismissed_at nulls first, m.performed_on desc""",
        (order_id,),
    )


def recheck_company(company_id):
    for row in rows("select id from maintenance_orders where company_id = %s and status <> 'cancelled' order by id", (company_id,)):
        check(row["id"])


def by_vendor(company_id):
    return {row["vendor"].lower(): row["n"] for row in rows(
        """select m.vendor, count(*) as n from maintenance_comebacks c join maintenance_orders m on m.id = c.earlier_id
           where c.company_id = %s and c.dismissed_at is null and m.vendor is not null and m.vendor <> ''
           group by m.vendor""",
        (company_id,),
    )}
