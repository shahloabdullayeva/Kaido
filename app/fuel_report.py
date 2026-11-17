import io
from datetime import datetime, time, timedelta
from html import escape

from PIL import Image, ImageDraw, ImageFont

from .config import ROOT
from .fuel import person, unit_label
from .db import execute, one, rows
from .logs import get
from .reminders import zone_for
from .telegram import send, send_photo

log = get("fuel-report")

FONT = ROOT / "app" / "fonts" / "DejaVuSansCondensed.ttf"
BOLD = ROOT / "app" / "fonts" / "DejaVuSansCondensed-Bold.ttf"
NAVY = "#1f3a8a"
PAPER = "#ffffff"
BG = "#f3f1ec"
INK = "#1a1d24"
MUTED = "#6b6f7a"
LINE = "#e6e2d9"
BLUE = "#2a78d6"
AQUA = "#1baf7a"
ORANGE = "#eb6834"
WIDTH = 1080
TREND_WEEKS = 6


def font(size, bold=False):
    return ImageFont.truetype(str(BOLD if bold else FONT), size)


def money(value, cents=False):
    value = float(value or 0)
    return f"${value:,.2f}" if cents else f"${value:,.0f}"


def week_bounds(company, day=None):
    zone = zone_for(company["timezone"])
    today = day or datetime.now(zone).date()
    start = today - timedelta(days=today.weekday() + 7)
    begin = datetime.combine(start, time.min, zone)
    return start, begin, begin + timedelta(days=7)


def scope_sql(driver_id, truck_id):
    if driver_id:
        return "(f.driver_id = %s or (f.driver_id is null and f.truck_id = %s))", (driver_id, truck_id)
    return "f.truck_id = %s", (truck_id,)


def totals(company_id, begin, end, where="true", params=()):
    found = one(
        f"""select count(*) filter (where f.fuel_type = 'diesel') as fills,
                   coalesce(sum(f.gallons) filter (where f.fuel_type = 'diesel'), 0) as gallons,
                   coalesce(sum(f.total) filter (where f.fuel_type = 'diesel'), 0) as spend,
                   coalesce(sum(f.total) filter (where f.fuel_type = 'def'), 0) as def_spend,
                   coalesce(sum(f.discount_ppu * f.gallons) filter (where f.fuel_type = 'diesel'), 0) as discount,
                   coalesce(sum(f.missed_usd) filter (where f.fuel_type = 'diesel'), 0) as missed,
                   count(*) filter (where f.fuel_type = 'diesel' and f.discount_ppu < 0.01) as no_discount,
                   coalesce(sum(f.retail_ppu * f.gallons) filter (where f.fuel_type = 'diesel'), 0) as retail_spend
            from fuel_transactions f
            where f.company_id = %s and f.purchased_at >= %s and f.purchased_at < %s and {where}""",
        (company_id, begin, end) + tuple(params),
    )
    gallons = float(found["gallons"] or 0)
    found["avg"] = float(found["spend"]) / gallons if gallons else None
    found["avg_retail"] = float(found["retail_spend"]) / gallons if gallons else None
    return found


def offers(company_id, begin, end, where="true", params=()):
    return one(
        f"""select count(*) filter (where o.status <> 'failed') as sent,
                   count(*) filter (where o.chosen_station_id is not null) as accepted,
                   count(*) filter (where o.skip_reason is not null) as skipped,
                   count(*) filter (where o.followed) as followed,
                   coalesce(sum(o.saved_usd) filter (where o.saved_usd > 0), 0) as saved
            from fuel_offers o where o.company_id = %s and o.created_at >= %s and o.created_at < %s and {where}""",
        (company_id, begin, end) + tuple(params),
    )


def week_trend(company_id, end, where="true", params=(), weeks=TREND_WEEKS):
    found = []
    for back in range(weeks, 0, -1):
        stop = end - timedelta(days=7 * (back - 1))
        begin = stop - timedelta(days=7)
        week = totals(company_id, begin, stop, where, params)
        found.append({"label": begin.strftime("%d %b"), "avg": week["avg"], "spend": float(week["spend"]),
                      "missed": float(week["missed"])})
    return found


def fills(company_id, begin, end, where="true", params=()):
    return rows(
        f"""select f.*, s.name as station_name, s.city as station_city, s.state as station_state,
                   b.name as best_name, b.city as best_city, b.state as best_state
            from fuel_transactions f
            left join fuel_stations s on s.id = f.station_id
            left join fuel_stations b on b.id = f.best_station_id
            where f.company_id = %s and f.fuel_type = 'diesel' and f.purchased_at >= %s and f.purchased_at < %s and {where}
            order by f.purchased_at""",
        (company_id, begin, end) + tuple(params),
    )


def truck_miles(truck_ids, begin, end):
    total = 0
    for truck_id in truck_ids:
        found = one(
            """select max(miles) - min(miles) as miles from odometer_readings
               where truck_id = %s and read_at >= %s and read_at < %s""",
            (truck_id, begin, end),
        )
        if found and found["miles"] and 0 < found["miles"] < 6000:
            total += found["miles"]
    return total


def driver_data(truck, begin, end):
    where, params = scope_sql(truck["driver_id"], truck["id"])
    company_id = truck["company_id"]
    week = totals(company_id, begin, end, where, params)
    fleet = totals(company_id, begin, end)
    offer_where = "o.driver_id = %s" if truck["driver_id"] else "o.truck_id = %s"
    asks = offers(company_id, begin, end, offer_where, (truck["driver_id"] or truck["id"],))
    used = fills(company_id, begin, end, where, params)
    miles = truck_miles({f["truck_id"] for f in used} or {truck["id"]}, begin, end)
    mpg = miles / float(week["gallons"]) if miles and week["gallons"] and float(week["gallons"]) > 30 else None
    priced = [f for f in used if f["net_ppu"]]
    return {
        "truck": truck, "week": week, "fleet": fleet, "offers": asks, "fills": used, "miles": miles,
        "mpg": mpg if mpg and 3.5 <= mpg <= 11 else None,
        "best": min(priced, key=lambda f: f["net_ppu"]) if priced else None,
        "worst_miss": max(used, key=lambda f: f["missed_usd"] or 0) if used else None,
        "trend": week_trend(company_id, end, where, params),
        "fleet_trend": week_trend(company_id, end),
    }


def fleet_data(company, begin, end):
    company_id = company["id"]
    week = totals(company_id, begin, end)
    before = totals(company_id, begin - timedelta(days=7), begin)
    people = rows(
        """select coalesce(d.name, f.raw->>'driver name', 'Unit ' || t.unit_number) as who,
                  count(*) as fills, sum(f.gallons) as gallons, sum(f.total) as spend,
                  sum(f.total) / nullif(sum(f.gallons), 0) as avg,
                  coalesce(sum(f.missed_usd), 0) as missed, coalesce(sum(f.discount_ppu * f.gallons), 0) as discount,
                  count(*) filter (where f.discount_ppu < 0.01) as no_discount
           from fuel_transactions f join trucks t on t.id = f.truck_id left join drivers d on d.id = f.driver_id
           where f.company_id = %s and f.fuel_type = 'diesel' and f.purchased_at >= %s and f.purchased_at < %s
           group by 1 order by missed desc, spend desc""",
        (company_id, begin, end),
    )
    misses = rows(
        """select f.*, t.unit_number, coalesce(d.name, f.raw->>'driver name') as who,
                  s.name as station_name, s.city as station_city, s.state as station_state,
                  b.name as best_name, b.city as best_city, b.state as best_state
           from fuel_transactions f join trucks t on t.id = f.truck_id left join drivers d on d.id = f.driver_id
           left join fuel_stations s on s.id = f.station_id left join fuel_stations b on b.id = f.best_station_id
           where f.company_id = %s and f.fuel_type = 'diesel' and f.purchased_at >= %s and f.purchased_at < %s
             and f.missed_usd > 0
           order by f.missed_usd desc limit 5""",
        (company_id, begin, end),
    )
    stations = rows(
        """select s.name, s.city, s.state, count(*) as fills, sum(f.gallons) as gallons,
                  sum(f.total) / nullif(sum(f.gallons), 0) as avg
           from fuel_transactions f join fuel_stations s on s.id = f.station_id
           where f.company_id = %s and f.fuel_type = 'diesel' and f.purchased_at >= %s and f.purchased_at < %s
           group by s.id, s.name, s.city, s.state order by gallons desc limit 5""",
        (company_id, begin, end),
    )
    truck_ids = [r["truck_id"] for r in rows(
        """select distinct truck_id from fuel_transactions where company_id = %s and purchased_at >= %s and purchased_at < %s""",
        (company_id, begin, end))]
    miles = truck_miles(truck_ids, begin, end)
    mpg = miles / float(week["gallons"]) if miles and week["gallons"] and float(week["gallons"]) > 100 else None
    return {
        "company": company, "week": week, "before": before, "offers": offers(company_id, begin, end),
        "people": people, "misses": misses, "stations": stations, "miles": miles,
        "mpg": mpg if mpg and 3.5 <= mpg <= 11 else None, "trend": week_trend(company_id, end, weeks=8),
    }


class Canvas:
    def __init__(self, height):
        self.image = Image.new("RGB", (WIDTH, height), BG)
        self.draw = ImageDraw.Draw(self.image)

    def text(self, xy, value, size=28, bold=False, fill=INK, anchor="la"):
        self.draw.text(xy, str(value), font=font(size, bold), fill=fill, anchor=anchor)

    def fit(self, value, width, size=28, bold=False):
        value = str(value)
        while font(size, bold).getlength(value) > width and len(value) > 3:
            value = value[:-2]
            if not value.endswith("…"):
                value = value[:-1] + "…"
        return value

    def header(self, title, subtitle, height=170):
        self.draw.rectangle([0, 0, WIDTH, height], fill=NAVY)
        self.text((WIDTH - 56, 56), "KAIDO", 26, True, "#c9d3f2", "ra")
        self.text((56, 46), self.fit(title, WIDTH - 112 - 140, 46, True), 46, True, "#ffffff")
        self.text((56, 108), self.fit(subtitle, WIDTH - 112, 28), 28, False, "#c9d3f2")

    def panel(self, box):
        self.draw.rounded_rectangle(box, radius=18, fill=PAPER, outline=LINE, width=2)

    def tile(self, box, label, value, note=None, note_fill=MUTED, value_fill=INK):
        self.panel(box)
        x, y = box[0] + 28, box[1] + 24
        self.text((x, y), label.upper(), 22, True, MUTED)
        self.text((x, y + 38), value, 50, True, value_fill)
        if note:
            self.text((x, y + 104), self.fit(note, box[2] - box[0] - 56, 24), 24, False, note_fill)

    def bars(self, box, series, key, label_fn, title, reference=None, reference_label=None, color=BLUE):
        self.panel(box)
        self.text((box[0] + 28, box[1] + 24), title, 22, True, MUTED)
        if reference and reference_label:
            x = box[2] - 28
            self.text((x, box[1] + 26), reference_label, 21, False, MUTED, "ra")
            width = font(21).getlength(reference_label)
            for dash in range(3):
                start = x - width - 64 + dash * 16
                self.draw.line([start, box[1] + 38, start + 9, box[1] + 38], fill=MUTED, width=3)
        left, top, right, bottom = box[0] + 40, box[1] + 110, box[2] - 40, box[3] - 60
        values = [s[key] for s in series if s[key]]
        if not values:
            self.text(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), "No fuel data yet", 26, False, MUTED, "mm")
            return
        high = max(values + ([reference] if reference else []))
        low = min(values + ([reference] if reference else []))
        floor = 0 if key != "avg" else max(0, low - (high - low or 1) * 0.8)
        span = (high - floor) or 1
        slot = (right - left) / len(series)
        width = min(70, slot * 0.55)
        self.draw.line([left, bottom, right, bottom], fill=LINE, width=2)
        for index, item in enumerate(series):
            cx = left + slot * index + slot / 2
            self.text((cx, bottom + 14), item["label"], 20, False, MUTED, "ma")
            if not item[key]:
                continue
            h = max(4, (item[key] - floor) / span * (bottom - top))
            self.draw.rounded_rectangle([cx - width / 2, bottom - h, cx + width / 2, bottom], radius=6, fill=color)
            self.text((cx, bottom - h - 10), label_fn(item[key]), 21, index == len(series) - 1, INK, "md")
        if reference:
            y = bottom - (reference - floor) / span * (bottom - top)
            for x in range(int(left), int(right), 18):
                self.draw.line([x, y, min(x + 9, right), y], fill=MUTED, width=2)

    def progress(self, box, done, total, color=AQUA):
        self.draw.rounded_rectangle(box, radius=(box[3] - box[1]) // 2, fill=LINE)
        if total:
            share = max(0.0, min(1.0, done / total))
            if share > 0:
                end = box[0] + (box[2] - box[0]) * share
                self.draw.rounded_rectangle([box[0], box[1], max(end, box[0] + box[3] - box[1]), box[3]],
                                            radius=(box[3] - box[1]) // 2, fill=color)

    def png(self):
        out = io.BytesIO()
        self.image.save(out, "PNG", optimize=True)
        return out.getvalue()

    def crop(self, height):
        self.image = self.image.crop((0, 0, WIDTH, min(height, self.image.height)))
        return self.png()


def place(name, city, state):
    where = ", ".join(p for p in [city, state] if p)
    if not name:
        return where or "an unknown stop"
    return f"{name}" + (f" ({where})" if where else "")


def driver_tip(data):
    miss = data["worst_miss"]
    if miss and (miss["missed_usd"] or 0) >= 10 and miss["best_net_ppu"]:
        cheaper = float(miss["net_ppu"]) - float(miss["best_net_ppu"])
        where = f" at {miss['station_name']}" if miss["station_name"] else ""
        best = miss["best_name"] or "another stop"
        return (f"Tip: on {miss['purchased_at']:%a %d %b}{where}, {best} {float(miss['best_miles'] or 0):.0f} mi away "
                f"was ${cheaper:.2f}/gal cheaper.")
    week = data["week"]
    if week["no_discount"]:
        return f"Tip: {week['no_discount']} fill(s) had no discount. Stick to the network stops Kaido suggests."
    if data["offers"]["sent"] and not data["offers"]["accepted"]:
        return "Tip: tap the stop you take on Kaido's fuel message so it learns your route."
    if not week["fills"]:
        return "No diesel on this truck last week."
    return "Nice week. Keep using the stops Kaido suggests."


def render_driver(data, start):
    truck, week, fleet, asks = data["truck"], data["week"], data["fleet"], data["offers"]
    canvas = Canvas(1700)
    who = person(truck.get("driver_name")) or "Driver"
    canvas.header(f"Weekly fuel · Unit {unit_label(truck['unit_number'])}",
                  f"{who} · {start:%d %b} – {start + timedelta(days=6):%d %b %Y}")
    gap, top, half = 24, 200, (WIDTH - 56 * 2 - 24) // 2
    avg_note = None
    if week["avg"] and fleet["avg"]:
        diff = week["avg"] - fleet["avg"]
        avg_note = ("same as fleet " + money(fleet["avg"], True)) if abs(diff) < 0.005 else \
            f"${abs(diff):.2f} {'above' if diff > 0 else 'below'} fleet {money(fleet['avg'], True)}"
    missed = float(week["missed"] or 0)
    canvas.tile([56, top, 56 + half, top + 170], "Spent on diesel", money(week["spend"]),
                f"{int(week['fills'])} fills" + (f" · DEF {money(week['def_spend'])}" if week["def_spend"] else ""))
    canvas.tile([56 + half + gap, top, WIDTH - 56, top + 170], "Gallons", f"{float(week['gallons']):,.0f}",
                f"{data['miles']:,} mi driven" if data["miles"] else "miles not reported")
    top += 170 + gap
    canvas.tile([56, top, 56 + half, top + 170], "Your price / gal", money(week["avg"], True) if week["avg"] else "—",
                avg_note, ORANGE if week["avg"] and fleet["avg"] and week["avg"] > fleet["avg"] + 0.005 else AQUA)
    canvas.tile([56 + half + gap, top, WIDTH - 56, top + 170], "Fuel economy",
                f"{data['mpg']:.1f} mpg" if data["mpg"] else "—", "miles ÷ gallons" if data["mpg"] else "needs odometer data")
    top += 170 + gap
    canvas.tile([56, top, 56 + half, top + 170], "Discounts you got", money(week["discount"]),
                f"pump price was {money(week['avg_retail'], True)}" if week["avg_retail"] else None, AQUA, AQUA)
    canvas.tile([56 + half + gap, top, WIDTH - 56, top + 170], "Missed savings", money(missed),
                "a cheaper stop was nearby" if missed > 0 else ("none — well done" if week["fills"] else None),
                ORANGE if missed > 0 else AQUA, ORANGE if missed > 0 else INK)
    top += 170 + gap
    canvas.bars([56, top, WIDTH - 56, top + 400], data["trend"], "avg", lambda v: f"${v:.2f}",
                "YOUR PRICE PER GALLON", fleet["avg"], f"fleet {money(fleet['avg'], True)}" if fleet["avg"] else None)
    top += 400 + gap
    sent, took = int(asks["sent"] or 0), int(asks["accepted"] or 0)
    if sent:
        canvas.panel([56, top, WIDTH - 56, top + 180])
        canvas.text((84, top + 24), "KAIDO FUEL SUGGESTIONS", 22, True, MUTED)
        canvas.text((84, top + 62), f"You took {took} of {sent}", 34, True)
        if asks["saved"] and float(asks["saved"]) > 0:
            canvas.text((WIDTH - 84, top + 66), f"saved {money(asks['saved'])}", 30, True, AQUA, "ra")
        canvas.progress([84, top + 122, WIDTH - 84, top + 144], took, sent)
        top += 180 + gap
    canvas.panel([56, top, WIDTH - 56, top + 96])
    canvas.text((84, top + 48), canvas.fit(driver_tip(data), WIDTH - 168, 26), 26, False, INK, "lm")
    top += 96 + 40
    return canvas.crop(top)


def render_fleet(data, start):
    company, week, before, asks = data["company"], data["week"], data["before"], data["offers"]
    canvas = Canvas(2600)
    canvas.header(f"Fleet fuel · {company['name']}", f"Week of {start:%d %b} – {start + timedelta(days=6):%d %b %Y}")
    gap, top = 24, 200
    third = (WIDTH - 112 - gap * 2) // 3
    change = None
    if before["spend"] and float(before["spend"]) > 0:
        pct = (float(week["spend"]) - float(before["spend"])) / float(before["spend"]) * 100
        change = "same as last week" if abs(pct) < 0.5 else f"{'up' if pct > 0 else 'down'} {abs(pct):.0f}% vs last week"
    sent = int(asks["sent"] or 0)
    tiles = [
        ("Diesel spend", money(week["spend"]), change, MUTED, INK),
        ("Gallons", f"{float(week['gallons']):,.0f}", f"{int(week['fills'])} fills", MUTED, INK),
        ("Avg price / gal", money(week["avg"], True) if week["avg"] else "—",
         f"pump {money(week['avg_retail'], True)}" if week["avg_retail"] else None, MUTED, INK),
        ("Discounts", money(week["discount"]),
         f"{int(week['no_discount'])} fills got none" if week["no_discount"]
         else ("every fill discounted" if week["fills"] else None), MUTED, AQUA),
        ("Missed savings", money(week["missed"]), "cheaper stop nearby" if float(week["missed"] or 0) else None,
         ORANGE, ORANGE if float(week["missed"] or 0) else INK),
        ("Fleet mpg", f"{data['mpg']:.1f}" if data["mpg"] else "—",
         f"{int(asks['accepted'] or 0)} of {sent} suggestions taken" if sent else "no suggestions sent", MUTED, INK),
    ]
    for index, (label, value, note, note_fill, value_fill) in enumerate(tiles):
        col, row = index % 3, index // 3
        x = 56 + col * (third + gap)
        y = top + row * (170 + gap)
        canvas.tile([x, y, x + third, y + 170], label, value, note, note_fill, value_fill)
    top += 2 * (170 + gap)
    canvas.bars([56, top, WIDTH - 56, top + 380], data["trend"], "spend", lambda v: f"${v / 1000:.1f}k",
                "DIESEL SPEND, LAST 8 WEEKS")
    top += 380 + gap
    people = data["people"][:8]
    height = 110 + 52 * len(people) if people else 130
    canvas.panel([56, top, WIDTH - 56, top + height])
    canvas.text((84, top + 24), "DRIVERS — MOST MISSED SAVINGS FIRST", 22, True, MUTED)
    cols = [(84, "la", "Driver"), (560, "ra", "Gallons"), (720, "ra", "$/gal"), (870, "ra", "Discount"), (WIDTH - 84, "ra", "Missed")]
    for x, anchor, label in cols if people else []:
        canvas.text((x, top + 64), label, 21, True, MUTED, anchor)
    y = top + 104
    for row in people:
        canvas.draw.line([84, y - 10, WIDTH - 84, y - 10], fill=LINE, width=1)
        canvas.text((84, y), canvas.fit(person(row["who"]), 400, 26), 26)
        canvas.text((560, y), f"{float(row['gallons']):,.0f}", 26, anchor="ra")
        canvas.text((720, y), f"${float(row['avg']):.3f}" if row["avg"] else "—", 26, anchor="ra")
        canvas.text((870, y), money(row["discount"]), 26, fill=AQUA, anchor="ra")
        missed = float(row["missed"] or 0)
        canvas.text((WIDTH - 84, y), money(missed), 26, missed > 0, ORANGE if missed > 0 else MUTED, "ra")
        y += 52
    if not people:
        canvas.text((84, top + 70), "No diesel purchases this week.", 26, False, MUTED)
    top += height + gap
    misses = data["misses"][:3]
    if misses:
        height = 76 + 100 * len(misses)
        canvas.panel([56, top, WIDTH - 56, top + height])
        canvas.text((84, top + 24), "BIGGEST MISSED OPPORTUNITIES", 22, True, MUTED)
        y = top + 70
        for miss in misses:
            line = f"Unit {unit_label(miss['unit_number'])} · {person(miss['who']) or 'driver'} · " \
                   f"{place(miss['station_name'], None, miss['station_state'])}"
            canvas.text((84, y), canvas.fit(line, 780, 25, True), 25, True)
            canvas.text((WIDTH - 84, y), money(miss["missed_usd"]), 28, True, ORANGE, "ra")
            detail = f"paid ${float(miss['net_ppu']):.3f} — {place(miss['best_name'], None, miss['best_state'])} " \
                     f"{float(miss['best_miles'] or 0):.0f} mi away was ${float(miss['best_net_ppu']):.3f}"
            canvas.text((84, y + 38), canvas.fit(detail, WIDTH - 168, 23), 23, False, MUTED)
            y += 100
        top += height + gap
    return canvas.crop(top + 16)


def driver_caption(data, start):
    week = data["week"]
    truck = data["truck"]
    lines = [f"<b>Weekly fuel — Unit {escape(unit_label(truck['unit_number']))}</b> ({start:%d %b}–{start + timedelta(days=6):%d %b})"]
    if not week["fills"]:
        lines.append("No diesel purchases on this truck last week.")
        return "\n".join(lines)
    lines.append(f"{float(week['gallons']):,.0f} gal · {money(week['spend'])} · avg {money(week['avg'], True)}/gal")
    lines.append(f"Discounts {money(week['discount'])} · missed {money(week['missed'])}")
    if data["mpg"]:
        lines.append(f"{data['mpg']:.1f} mpg on {data['miles']:,} mi")
    lines.append(escape(driver_tip(data)))
    return "\n".join(lines)


def fleet_caption(data, start):
    week = data["week"]
    lines = [f"<b>Fleet fuel — {escape(data['company']['name'])}</b> ({start:%d %b}–{start + timedelta(days=6):%d %b})",
             (f"{money(week['spend'])} on {float(week['gallons']):,.0f} gal · avg {money(week['avg'], True)}/gal"
              if week["avg"] else "No diesel purchases last week."),
             f"Discounts {money(week['discount'])} · missed savings <b>{money(week['missed'])}</b>"]
    if week["no_discount"]:
        lines.append(f"{int(week['no_discount'])} fill(s) had no network discount")
    return "\n".join(lines)


def already(company_id, kind, target_id, start):
    return one("select ok from fuel_reports where company_id = %s and kind = %s and target_id = %s and week_start = %s",
               (company_id, kind, target_id, start))


def mark(company_id, kind, target_id, start, ok):
    execute(
        """insert into fuel_reports (company_id, kind, target_id, week_start, ok) values (%s, %s, %s, %s, %s)
           on conflict (company_id, kind, target_id, week_start) do update set ok = excluded.ok, sent_at = now()""",
        (company_id, kind, target_id, start, ok),
    )


def send_driver(truck, force=False, start_day=None):
    company = one("select * from companies where id = %s", (truck["company_id"],))
    start, begin, end = week_bounds(company, start_day)
    if not force and already(company["id"], "driver", truck["id"], start):
        return None
    data = driver_data(truck, begin, end)
    result = send_photo(truck["telegram_chat_id"], render_driver(data, start), driver_caption(data, start))
    if not force:
        mark(company["id"], "driver", truck["id"], start, bool(result.get("ok")))
    return bool(result.get("ok"))


def managers(company_id):
    return rows(
        """select distinct u.id, u.telegram_chat_id from users u join memberships m on m.user_id = u.id
           where m.company_id = %s and m.role = 'admin' and u.telegram_chat_id is not null
             and u.status = 'active'""",
        (company_id,),
    )


def send_fleet(company, force=False, start_day=None, to=None):
    start, begin, end = week_bounds(company, start_day)
    data = fleet_data(company, begin, end)
    png = render_fleet(data, start)
    caption = fleet_caption(data, start)
    sent = 0
    for user in to or managers(company["id"]):
        if not force and already(company["id"], "fleet", user["id"], start):
            continue
        ok = bool(send_photo(user["telegram_chat_id"], png, caption).get("ok"))
        if not force:
            mark(company["id"], "fleet", user["id"], start, ok)
        sent += ok
    return sent


def due(company, now=None):
    local = (now or datetime.now(zone_for(company["timezone"]))).astimezone(zone_for(company["timezone"]))
    return local.isoweekday() == company["fuel_report_weekday"] and local.hour >= company["fuel_report_hour"]


def run(company=None, send=True, force=False):
    from .fuel_bot import TRUCK_SQL
    companies = [company] if company else rows(
        "select * from companies where status = 'active' and fuel_assistant_enabled order by id")
    done = {}
    for target in companies:
        if not force and not due(target):
            continue
        start, begin, end = week_bounds(target)
        if not send:
            data = fleet_data(target, begin, end)
            path = ROOT / "logs" / f"fuel-fleet-{target['id']}-{start}.png"
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(render_fleet(data, start))
            done[target["name"]] = {"preview": str(path), "caption": fleet_caption(data, start)}
            continue
        trucks = rows(TRUCK_SQL + " where t.company_id = %s and t.telegram_chat_id is not null and t.status <> 'sold'",
                      (target["id"],))
        drivers = sum(1 for truck in trucks if send_driver(truck))
        done[target["name"]] = {"drivers": drivers, "office": send_fleet(target)}
    return done
