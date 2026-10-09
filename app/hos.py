from .db import rows

DUTY = {
    "DS_D": ("Driving", "ok"),
    "DS_ON": ("On duty", "info"),
    "DS_OFF": ("Off duty", "muted"),
    "DS_SB": ("Sleeper berth", "muted"),
    "DS_PC": ("Personal conveyance", "muted"),
    "DS_YM": ("Yard move", "info"),
}
SOURCES = {
    "samsara": "Samsara",
    "horizon": "Horizon ELD",
    "horizoneld": "Horizon ELD",
    "manual": "Entered by hand",
    "telegram": "Driver, via Telegram",
}
HOUR = 3_600_000


def clock(value):
    if value is None:
        return None
    minutes = max(int(float(value)) // 60_000, 0)
    return f"{minutes // 60}:{minutes % 60:02d}"


def clock_tone(value, warn_hours):
    if value is None:
        return "muted"
    value = float(value)
    if value <= 0:
        return "bad"
    return "warn" if value < warn_hours * HOUR else "ok"


def shape(row):
    label, tone = DUTY.get(row["duty_status"] or "", ((row["duty_status"] or "Unknown").replace("DS_", ""), "muted"))
    return dict(
        row,
        duty_label=label,
        duty_tone=tone,
        drive=clock(row["drive_remaining"]), drive_tone=clock_tone(row["drive_remaining"], 1),
        shift=clock(row["shift_remaining"]), shift_tone=clock_tone(row["shift_remaining"], 1),
        cycle=clock(row["cycle_remaining"]), cycle_tone=clock_tone(row["cycle_remaining"], 5),
        brk=clock(row["break_remaining"]), brk_tone=clock_tone(row["break_remaining"], 0.5),
    )


def for_drivers(company_id, driver_ids=None):
    params = [company_id]
    clause = ""
    if driver_ids is not None:
        ids = [driver_id for driver_id in driver_ids if driver_id]
        if not ids:
            return {}
        clause = " and driver_id = any(%s)"
        params.append(ids)
    found = rows(
        f"""select * from hos_status where company_id = %s and driver_id is not null{clause}
            order by updated_at desc""",
        tuple(params),
    )
    result = {}
    for row in found:
        result.setdefault(row["driver_id"], shape(row))
    return result
