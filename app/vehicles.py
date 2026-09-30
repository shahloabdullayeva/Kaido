import requests

from .db import execute, one

VPIC = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json"


def decode_vin(vin):
    response = requests.get(VPIC.format(vin=vin), timeout=15)
    response.raise_for_status()
    result = (response.json().get("Results") or [{}])[0]
    engine = " ".join(part for part in [
        (result.get("EngineManufacturer") or "").strip(),
        (result.get("EngineModel") or "").strip(),
    ] if part).strip()
    liters = None
    try:
        liters = round(float(result.get("DisplacementL") or 0), 1) or None
    except ValueError:
        pass
    return {
        "engine": engine or None,
        "liters": liters,
        "make": (result.get("Make") or "").strip().title() or None,
        "model": (result.get("Model") or "").strip() or None,
        "year": int(result["ModelYear"]) if (result.get("ModelYear") or "").isdigit() else None,
        "fuel": (result.get("FuelTypePrimary") or "").strip() or None,
    }


def ensure_engine(truck):
    if truck.get("engine") or truck.get("engine_checked_at") or not truck.get("vin") or len(truck["vin"]) != 17:
        return truck
    try:
        found = decode_vin(truck["vin"])
    except Exception as err:
        print(f"[vpic] {truck['vin']}: {err}")
        return truck
    execute(
        """update trucks set engine = coalesce(engine, %s), engine_liters = coalesce(engine_liters, %s),
             engine_source = case when engine is null and %s::text is not null then 'vin' else engine_source end,
             make = coalesce(make, %s), model = coalesce(model, %s), year = coalesce(year, %s),
             engine_checked_at = now()
           where id = %s""",
        (found["engine"], found["liters"], found["engine"], found["make"], found["model"], found["year"], truck["id"]),
    )
    return one("select * from trucks where id = %s", (truck["id"],))
