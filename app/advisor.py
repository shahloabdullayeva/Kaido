import sys
from typing import List

from .config import config

MODEL = config.AI_MODEL
MAX_SHOPS = 8


def available():
    return bool(config.ANTHROPIC_API_KEY)


def _client():
    import anthropic
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _ask(system, user, output_format, max_tokens=1600):
    if not available():
        return None
    try:
        response = _client().messages.parse(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=output_format,
        )
        return response.parsed_output
    except Exception as err:
        print(f"advisor {MODEL} failed: {err}", file=sys.stderr)
        return None


SHOP_SYSTEM = (
    "You advise a truck fleet dispatcher choosing where to send a Class 8 tractor "
    "for an oil and filter service. You are given the truck, its current position, "
    "and a list of candidate shops pulled from OpenStreetMap, each with distance, "
    "opening hours where known, and the fleet's own past invoices at that shop. "
    "For each shop write one line of at most 22 words that helps the dispatcher "
    "decide. Lead with the single most decisive fact. "
    "RULES YOU MUST FOLLOW: "
    "Never state an opening time, price, phone number or review that is not in the "
    "data you were given — say 'hours not listed' rather than guessing. "
    "The fleet's own past invoices are the strongest evidence there is: if they have "
    "used a shop before, lead with what they paid and when. "
    "'Truck fit unconfirmed' means OpenStreetMap does not say whether the bay takes a "
    "Class 8 tractor — say to phone ahead, do not assume it fits. "
    "A shop marked 24/7 is worth preferring when the truck is moving at night. "
    "Do not invent star ratings; there are no reviews in this data. "
    "Then set 'pick' to the name of the shop you would send the truck to, and "
    "'why' to one sentence under 25 words saying why that one. If nothing is a "
    "sensible choice, set pick to an empty string and say so in 'why'."
)


def shop_advice(truck, shops, fleet_average=None):
    if not shops or not available():
        return None
    from pydantic import BaseModel

    class ShopNote(BaseModel):
        name: str
        note: str

    class Advice(BaseModel):
        notes: List[ShopNote]
        pick: str
        why: str

    lines = []
    for shop in shops[:MAX_SHOPS]:
        bits = [
            f"{shop['name']}",
            f"{shop['miles']} miles away",
            f"type {shop.get('kind') or 'unknown'}",
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
        lines.append("- " + "; ".join(str(bit) for bit in bits))

    context = [
        f"Truck {truck.get('unit_number')} ({' '.join(str(p) for p in [truck.get('year'), truck.get('make'), truck.get('model')] if p)})",
        f"Currently at: {truck.get('location') or 'position known, address not resolved'}",
        f"Odometer {truck.get('odometer'):,} miles" if truck.get("odometer") else "",
        f"This fleet's average oil service costs ${fleet_average:.0f}" if fleet_average else
        "This fleet has no oil invoices on record yet",
    ]
    user = "\n".join(part for part in context if part) + "\n\nCandidate shops:\n" + "\n".join(lines)
    return _ask(SHOP_SYSTEM, user, Advice)
