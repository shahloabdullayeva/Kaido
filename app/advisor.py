import json
from hashlib import sha256
from typing import List, Literal

from pydantic import BaseModel

from .config import config
from .db import execute, one
from .logs import get

log = get("advisor")

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
        log.warning("%s call failed: %s", MODEL, err)
        return None
    _remember(response.usage)
    parsed = response.parsed_output
    if parsed is None:
        return None
    _store(key, parsed.model_dump(mode="json"))
    return parsed


SHOP_SYSTEM = (
    "You advise a truck fleet dispatcher choosing where to send a Class 8 tractor "
    "for the job you are given (an oil and filter service when no job is given). Pick a shop "
    "that can actually do that job on a Class 8 truck: a tire job needs a tire or truck shop, "
    "not a paint shop or a fuel-only stop. You are given the truck, its current position, "
    "and a numbered list of candidate shops pulled from Google Maps or OpenStreetMap, each with "
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
    "A shop marked 'saved by the fleet' is one the fleet's own people chose and trust: "
    "pick a saved shop unless it is closed when the truck needs it or much further than "
    "another shop that fits a Class 8. "
    "'Truck fit unconfirmed' means the map data does not say whether the bay takes a "
    "Class 8 tractor — say to phone ahead, do not assume it fits. "
    "A shop marked 24/7 is worth preferring when the truck is moving at night. "
    "Love's Truck Care, Speedco, TA Truck Service and Petro do roadside help and light mechanical work only: "
    "they never tow, do not take heavy repairs (engine, transmission, major electrical, body), and may not "
    "stock the exact oil or part, so for those say to call first. A truck that cannot drive needs a tow "
    "company or mobile road service, never a truck stop. "
    "Write plain English a dispatcher would say out loud, never the raw tag words. "
    "If the only honest thing to say is that nobody knows whether the bay fits a "
    "Class 8, say exactly that and nothing else. "
    "Only mention a star rating when one is given in the data, and never invent one. "
    "Then set 'pick' to the name of the shop you would send the truck to, and "
    "'why' to one sentence under 25 words saying why that one. If nothing is a "
    "sensible choice, set pick to an empty string and say so in 'why'."
)


def shop_advice(truck, shops, fleet_average=None, job=None):
    if not shops or not available():
        return None
    lines = []
    for number, shop in enumerate(shops[:MAX_SHOPS], start=1):
        bits = [
            f"{shop['name']}",
            f"{shop['miles']} miles away",
            KINDS.get(shop.get("kind"), "an unlisted kind of shop"),
            {"tow": "towing company", "road": "mobile road service", "light": "roadside and light repair only, no towing"}.get(shop.get("service"), ""),
            ("takes Class 8" if shop["truck_fit"] == "yes" else "truck fit unconfirmed"),
            shop["hours_text"],
        ]
        if shop.get("saved"):
            note = shop["saved"].get("note")
            bits.append("saved by the fleet" + (f" — note: {note}" if note else ""))
        if shop.get("rating"):
            bits.append(f"Google rating {shop['rating']:.1f} from {shop.get('ratings') or 0} reviews")
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
        f"The job: {job}" if job else "The job: oil and filter service",
        (f"This fleet's average oil service costs ${fleet_average:.0f}" if fleet_average else
         "This fleet has no oil invoices on record yet") if not job or "oil" in job.lower() else "",
    ]
    user = "\n".join(part for part in context if part) + "\n\nCandidate shops:\n" + "\n".join(lines)
    return _ask(SHOP_SYSTEM, user, Advice)


class FaultGuide(BaseModel):
    meaning: str
    urgency: Literal["stop_now", "soon", "next_service", "watch"]
    urgency_reason: str
    likely_fix: str
    driver_check: str


URGENCY_LABELS = {
    "stop_now": "Stop the truck",
    "soon": "Get it looked at within a day or two",
    "next_service": "Fix it at the next service",
    "watch": "Keep an eye on it",
}

FAULT_SYSTEM = (
    "You explain heavy-truck fault codes to a small fleet's dispatcher, who is not a mechanic. "
    "You are given one fault code from the truck's telematics (J1939 SPN/FMI or OBD-II), "
    "the telematics description, the warning lamp, how often it has fired, and the truck's "
    "make, model, year and mileage. "
    "'meaning' is two short sentences in plain English about what the part is and what the "
    "truck is reporting. "
    "'urgency' is stop_now only when driving on risks the engine, the brakes, the tires or "
    "people (a red stop lamp, coolant loss, oil pressure, brake or tire pressure faults); soon "
    "when it should be seen within a day or two; next_service when it can wait for the next "
    "planned visit; watch when it is usually a sensor glitch that clears itself. "
    "'urgency_reason' is one sentence. "
    "'likely_fix' is one or two sentences on what a shop usually does for this code. "
    "'driver_check' is one thing the driver can safely check or report, or an empty string. "
    "RULES: never state a price, a labour time, or a part number. Never claim certainty about "
    "the cause; say 'usually' or 'often'. If the code is one you do not recognise, say so in "
    "'meaning' and set urgency from the lamp alone. Write the way a mechanic would say it on the phone."
)


def fault_guide_key(fault, truck):
    return ":".join(str(part or "") for part in [
        fault.get("protocol"), fault.get("code_key"), fault.get("lamp"),
        (truck.get("make") or "").lower(),
    ])


def fault_guide(fault, truck):
    key = fault_guide_key(fault, truck)
    row = one("select payload from fault_guides where guide_key = %s", (key,))
    if row:
        return FaultGuide.model_validate(row["payload"])
    code = fault.get("dtc_code") or f"SPN {fault.get('spn')} / FMI {fault.get('fmi')}"
    user = "\n".join(part for part in [
        f"Code: {code} ({fault.get('protocol')})",
        f"Telematics description: {fault.get('description') or 'none given'}",
        f"Warning lamp: {fault.get('lamp') or 'not reported'}",
        f"Times seen: {fault.get('occurrence_count') or 'unknown'}",
        "Truck: " + " ".join(str(p) for p in [truck.get("year"), truck.get("make"), truck.get("model")] if p),
        f"Odometer: {truck.get('odometer'):,} miles" if truck.get("odometer") else "",
    ] if part)
    guide = _ask(FAULT_SYSTEM, user, FaultGuide, max_tokens=700)
    if guide is None:
        return None
    execute(
        """insert into fault_guides (guide_key, model, payload) values (%s, %s, %s)
           on conflict (guide_key) do nothing""",
        (key, MODEL, json.dumps(guide.model_dump(mode="json"))),
    )
    return guide


class OilAdvice(BaseModel):
    oil: str
    viscosity: str
    capacity: str
    filter_note: str
    interval_note: str
    confidence: Literal["engine_known", "make_only", "guess"]
    caution: str


OIL_SYSTEM = (
    "You tell a truck fleet's dispatcher which engine oil to ask the shop for at an oil and filter "
    "service. You are given the truck's year, make, model, engine (decoded from the VIN or typed by "
    "the fleet), mileage and duty cycle. "
    "'oil' names the API service category (for example CK-4 or FA-4) and, if the engine maker "
    "publishes its own approval, says to look for that maker's approval on the label, naming the maker "
    "only. Never write an engine maker's specification number or code. "
    "'viscosity' is the grade or grades usually used, with the most common first. "
    "'capacity' is the usual oil fill with the filter change, written like 'about 11 US gallons "
    "with the filter', always with the unit and the word about. "
    "'filter_note' is one sentence on the filter (full-flow, bypass, centrifuge) without part numbers. "
    "'interval_note' is one sentence comparing the fleet's interval to the maker's typical guidance for "
    "this duty cycle. "
    "'confidence' is engine_known when you were given a specific engine, make_only when you only know "
    "the truck make, guess otherwise. "
    "'caution' is one sentence telling them to confirm against the engine maker's current spec or the "
    "sticker on the engine before the shop pours it. "
    "RULES: never give prices, brands of oil, part numbers or specification codes. Plain English."
)


def oil_advice(truck):
    if not available():
        return None
    user = "\n".join(part for part in [
        "Truck: " + " ".join(str(p) for p in [truck.get("year"), truck.get("make"), truck.get("model")] if p),
        f"Engine: {truck.get('engine')}" + (f", {truck.get('engine_liters')} L" if truck.get("engine_liters") else "")
        if truck.get("engine") else "Engine: unknown",
        f"Odometer: {truck.get('odometer'):,} miles" if truck.get("odometer") else "",
        f"Duty cycle: {truck.get('duty_cycle') or 'standard'}",
        f"Fleet oil interval: {truck.get('oil_interval_miles') or 25000:,} miles",
    ] if part)
    return _ask(OIL_SYSTEM, user, OilAdvice, max_tokens=600)


CHAT_SYSTEM = (
    "You are the assistant inside Kaido, a maintenance app for a small trucking fleet. You talk to "
    "dispatchers and fleet managers, not mechanics. Below the rules is everything Kaido knows about "
    "the truck being discussed. "
    "RULES: Facts about this fleet (dates, costs, miles, faults, shops used) come only from the data "
    "given; if it is not there, say Kaido does not have it. General mechanical knowledge is fine but "
    "say 'usually' and never claim certainty about a diagnosis. Never make up shop hours, phone "
    "numbers, prices or reviews. Keep answers short: a few sentences or a short list. When they ask "
    "you to write something (a message to a driver or a shop, a note for a work order), write it "
    "ready to paste. Due dates and mileages in the data are already calculated; repeat them, do not "
    "recalculate. Write plain text only: no markdown, no asterisks, no headings, no horizontal lines. "
    "Use simple numbered or dashed lists when a list helps."
)
CHAT_TURNS = 12


def chat_reply(context, history, question):
    if not available():
        return None, "The assistant is off because no Anthropic key is set."
    if over_budget():
        return None, "Today's AI budget is used up. The assistant is back tomorrow."
    messages = [{"role": turn["role"], "content": turn["content"]} for turn in history[-CHAT_TURNS:]]
    messages.append({"role": "user", "content": question})
    try:
        response = _client().messages.create(
            model=MODEL,
            max_tokens=700,
            system=CHAT_SYSTEM + "\n\n" + context,
            messages=messages,
        )
    except Exception as err:
        log.warning("%s chat failed: %s", MODEL, err)
        return None, "The assistant did not answer just now. Try again in a minute."
    _remember(response.usage)
    text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text").strip()
    return text or None, None if text else "The assistant came back empty. Try asking another way."
