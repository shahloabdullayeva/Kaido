import json
import sys
from hashlib import sha256
from typing import List

from pydantic import BaseModel

from .config import config
from .db import execute, one

MODEL = config.AI_MODEL
MAX_SHOPS = 8
KINDS = {
    "truck_repair": "a truck repair shop",
    "truck_stop": "a truck stop",
    "car_repair": "a car repair garage",
    "tyres": "a tyre shop",
    "fuel": "a fuel stop",
}
CACHE_DAYS = 7
PRICES = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-opus-5": (5.0, 25.0),
}


class ShopNote(BaseModel):
    number: int
    note: str


class Advice(BaseModel):
    notes: List[ShopNote]
    pick: str
    why: str


def available():
    return bool(config.ANTHROPIC_API_KEY)


def spent_today():
    row = one(
        "select coalesce(sum(cost_usd), 0) as spent from ai_usage where created_at >= date_trunc('day', now())"
    )
    return float(row["spent"]) if row else 0.0


def spent_total():
    row = one("select coalesce(sum(cost_usd), 0) as spent, count(*) as calls from ai_usage")
    return (float(row["spent"]), row["calls"]) if row else (0.0, 0)


def over_budget():
    return spent_today() >= config.AI_DAILY_USD


def _cost(usage):
    per_input, per_output = PRICES.get(MODEL, (5.0, 25.0))
    return (usage.input_tokens * per_input + usage.output_tokens * per_output) / 1_000_000


def _remember(usage):
    execute(
        "insert into ai_usage (model, input_tokens, output_tokens, cost_usd) values (%s, %s, %s, %s)",
        (MODEL, usage.input_tokens, usage.output_tokens, _cost(usage)),
    )


def _client():
    import anthropic
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _cached(key):
    row = one(
        "select payload from ai_cache where cache_key = %s and fetched_at > now() - make_interval(days => %s)",
        (key, CACHE_DAYS),
    )
    return row["payload"] if row else None


def _store(key, payload):
    execute(
        """insert into ai_cache (cache_key, model, payload, fetched_at) values (%s, %s, %s, now())
           on conflict (cache_key) do update set payload = excluded.payload, fetched_at = now()""",
        (key, MODEL, json.dumps(payload)),
    )


def _ask(system, user, output_format, max_tokens=1200):
    if not available():
        return None
    key = sha256("\n".join([MODEL, system, user]).encode()).hexdigest()
    hit = _cached(key)
    if hit:
        return output_format.model_validate(hit)
    if over_budget():
        return None
    try:
        response = _client().messages.parse(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=output_format,
        )
    except Exception as err:
        print(f"advisor {MODEL} failed: {err}", file=sys.stderr)
        return None
    _remember(response.usage)
    parsed = response.parsed_output
    if parsed is None:
        return None
    _store(key, parsed.model_dump(mode="json"))
    return parsed


SHOP_SYSTEM = (
    "You advise a truck fleet dispatcher choosing where to send a Class 8 tractor "
    "for an oil and filter service. You are given the truck, its current position, "
    "and a numbered list of candidate shops pulled from OpenStreetMap, each with "
    "distance, opening hours where known, and the fleet's own past invoices at that "
    "shop. For each shop write one line of at most 18 words, and give its number. "
    "RULES YOU MUST FOLLOW: "
    "Never write a number of miles, minutes or dollars of detour in your line: the "
    "dispatcher is already reading those on the same screen, and repeating them "
    "wastes the line. Say the thing they cannot see. "
    "Never state an opening time, price, phone number or review that is not in the "
    "data you were given, and never say that hours are not listed — the screen "
    "says that already. "
    "The fleet's own past invoices are the strongest evidence there is: if they have "
    "used a shop before, lead with what they paid and when. "
    "'Truck fit unconfirmed' means OpenStreetMap does not say whether the bay takes a "
    "Class 8 tractor — say to phone ahead, do not assume it fits. "
    "A shop marked 24/7 is worth preferring when the truck is moving at night. "
    "Write plain English a dispatcher would say out loud, never the raw tag words. "
    "If the only honest thing to say is that nobody knows whether the bay fits a "
    "Class 8, say exactly that and nothing else. "
    "Do not invent star ratings; there are no reviews in this data. "
    "Then set 'pick' to the name of the shop you would send the truck to, and "
    "'why' to one sentence under 25 words saying why that one. If nothing is a "
    "sensible choice, set pick to an empty string and say so in 'why'."
)


def shop_advice(truck, shops, fleet_average=None):
    if not shops or not available():
        return None
    lines = []
    for number, shop in enumerate(shops[:MAX_SHOPS], start=1):
        bits = [
            f"{shop['name']}",
            f"{shop['miles']} miles away",
            KINDS.get(shop.get("kind"), "an unlisted kind of shop"),
            ("takes Class 8" if shop["truck_fit"] == "yes" else "truck fit unconfirmed"),
            shop["hours_text"],
        ]
        if shop.get("phone"):
            bits.append(f"phone {shop['phone']}")
        history = shop.get("history")
        if history:
            bits.append(
                f"fleet used it {history['visits']}x, average ${history['average']:.0f}, "
                f"last {history['last']}"
            )
        else:
            bits.append("never used by this fleet")
        if shop.get("detour"):
            bits.append(f"detour about ${shop['detour']['cost']:.0f} and "
                        f"{shop['detour']['spell']} of driving")
        lines.append(f"{number}. " + "; ".join(str(bit) for bit in bits))

    context = [
        f"Truck {truck.get('unit_number')} ({' '.join(str(p) for p in [truck.get('year'), truck.get('make'), truck.get('model')] if p)})",
        f"Currently at: {truck.get('location') or 'position known, address not resolved'}",
        f"Odometer {truck.get('odometer'):,} miles" if truck.get("odometer") else "",
        f"This fleet's average oil service costs ${fleet_average:.0f}" if fleet_average else
        "This fleet has no oil invoices on record yet",
    ]
    user = "\n".join(part for part in context if part) + "\n\nCandidate shops:\n" + "\n".join(lines)
    return _ask(SHOP_SYSTEM, user, Advice)
