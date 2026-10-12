from .db import execute, one, rows
from .work_types import CUSTOM_PREFIX, GROUPS, SCHEDULES, label as work_label

LOCKED = ["oil"]
LABEL_LIMIT = 36
DEFAULTS = {item["kind"]: item for item in SCHEDULES}
BUILT_IN = [key for group, _, items in GROUPS if group == "pm" for key, _ in items] + [kind for kind in DEFAULTS]


def edits(company_id):
    return rows("select kind, label, removed from pm_list where company_id = %s order by created_at, kind", (company_id,))


def removed(company_id):
    return {row["kind"] for row in edits(company_id) if row["removed"]}


def items(company_id, keep=None):
    saved = edits(company_id)
    gone = {row["kind"] for row in saved if row["removed"]} - {keep}
    out = [(key, text) for group, _, entries in GROUPS if group == "pm" for key, text in entries if key not in gone]
    out += [(row["kind"], row["label"]) for row in saved if row["kind"].startswith(CUSTOM_PREFIX) and row["kind"] not in gone]
    return out


def removed_items(company_id):
    labels = {key: text for group, _, entries in GROUPS if group == "pm" for key, text in entries}
    labels.update({kind: item["label"] for kind, item in DEFAULTS.items()})
    return [(row["kind"], row["label"] or labels.get(row["kind"], row["kind"])) for row in edits(company_id)
            if row["removed"] and (row["kind"] in labels or row["kind"].startswith(CUSTOM_PREFIX))]


def groups(company_id, keep=None):
    return [(group, heading, items(company_id, keep) if group == "pm" else entries) for group, heading, entries in GROUPS]


def kinds(company_id, keep=None):
    return [key for _, _, entries in groups(company_id, keep) for key, _ in entries]


def add(company_id, label):
    label = " ".join((label or "").split())[:LABEL_LIMIT]
    if not label:
        return None, "Type a name for it."
    taken = {text.lower(): key for key, text in items(company_id)}
    if label.lower() in taken:
        return None, f"{label} is already on the list."
    for key, text in removed_items(company_id):
        if text.lower() == label.lower():
            restore(company_id, key)
            return text, None
    execute(
        """insert into pm_list (company_id, kind, label, removed) values (%s, %s, %s, false)
           on conflict (company_id, kind) do update set removed = false, label = excluded.label""",
        (company_id, CUSTOM_PREFIX + label, label),
    )
    return label, None


def remove(company_id, kind):
    listed = dict(items(company_id) + candidates(company_id))
    if kind in LOCKED or kind not in listed:
        return None
    label = listed[kind]
    execute(
        """insert into pm_list (company_id, kind, label, removed) values (%s, %s, %s, true)
           on conflict (company_id, kind) do update set removed = true""",
        (company_id, kind, label if kind.startswith(CUSTOM_PREFIX) else None),
    )
    return label


def restore(company_id, kind):
    row = one("select kind from pm_list where company_id = %s and kind = %s and removed", (company_id, kind))
    if not row:
        return False
    if kind in BUILT_IN:
        execute("delete from pm_list where company_id = %s and kind = %s", (company_id, kind))
    else:
        execute("update pm_list set removed = false where company_id = %s and kind = %s", (company_id, kind))
    return True


def used(company_id):
    return {row["kind"]: row["n"] for row in rows(
        "select kind, count(*) as n from maintenance_orders where company_id = %s group by kind", (company_id,))}


def candidates(company_id):
    gone = removed(company_id)
    out = [(item["kind"], item["label"]) for item in SCHEDULES if item["kind"] not in gone]
    out += [(kind, text) for kind, text in items(company_id) if kind not in DEFAULTS and kind not in LOCKED]
    return out


def find(company_id, name):
    wanted = " ".join((name or "").split()).lower()
    for kind, text in candidates(company_id) + removed_items(company_id):
        if wanted and wanted in (text.lower(), work_label(kind).lower()):
            return kind
    return None


def ensure(company_id, name):
    kind = find(company_id, name)
    if kind:
        return kind, None
    label, problem = add(company_id, name)
    return (None, problem) if problem else (CUSTOM_PREFIX + label, None)


def schedule_item(kind, label, miles, months, **extra):
    base = DEFAULTS.get(kind)
    return dict({"kind": kind, "label": label, "covered_by": base["covered_by"] if base else [kind],
                 "miles": miles, "months": months, "own": True}, **extra)


def company_schedules(company_id):
    saved = {row["kind"]: row for row in rows("select kind, miles, months from service_intervals where company_id = %s", (company_id,))}
    out = []
    for kind, label in candidates(company_id):
        row, base = saved.get(kind), DEFAULTS.get(kind)
        out.append(schedule_item(kind, label,
                                 row["miles"] if row else (base["miles"] if base else None),
                                 row["months"] if row else (base["months"] if base else None)))
    return out


def set_interval(company_id, kind, miles, months):
    execute(
        """insert into service_intervals (company_id, kind, miles, months) values (%s, %s, %s, %s)
           on conflict (company_id, kind) do update set miles = excluded.miles, months = excluded.months, updated_at = now()""",
        (company_id, kind, miles, months),
    )


def truck_edits(truck_ids):
    out = {}
    if truck_ids:
        for row in rows("select truck_id, kind, removed, miles, months from truck_services where truck_id = any(%s) order by created_at, kind",
                        (list(truck_ids),)):
            out.setdefault(row["truck_id"], []).append(row)
    return out


def for_truck(company_items, edits):
    by_kind = {row["kind"]: row for row in edits}
    out = []
    for item in company_items:
        row = by_kind.get(item["kind"])
        if row and row["removed"]:
            continue
        if row and (row["miles"] or row["months"]):
            out.append(dict(item, miles=row["miles"], months=row["months"], scope="truck interval"))
        elif item["kind"] in DEFAULTS or item["miles"] or item["months"]:
            out.append(dict(item, scope="company"))
    known = {item["kind"] for item in company_items}
    for row in edits:
        if not row["removed"] and row["kind"] not in known and (row["miles"] or row["months"]):
            base = DEFAULTS.get(row["kind"])
            out.append(schedule_item(row["kind"], base["label"] if base else work_label(row["kind"]),
                                     row["miles"], row["months"], scope="truck only"))
    return out


def set_for_truck(company_id, truck_id, kind, miles=None, months=None, removed=False):
    execute(
        """insert into truck_services (company_id, truck_id, kind, removed, miles, months) values (%s, %s, %s, %s, %s, %s)
           on conflict (truck_id, kind) do update set removed = excluded.removed, miles = excluded.miles, months = excluded.months""",
        (company_id, truck_id, kind, removed, miles, months),
    )


def clear_for_truck(truck_id, kind):
    execute("delete from truck_services where truck_id = %s and kind = %s", (truck_id, kind))
