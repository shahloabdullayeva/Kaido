GROUPS = [
    ("pm", "Preventive maintenance", [
        ("oil", "Oil & filter"),
        ("pm_a", "PM-A"),
        ("pm_b", "PM-B"),
        ("pm_c", "PM-C (major service)"),
        ("grease", "Chassis grease / lube"),
        ("filters", "Fuel & air filters"),
        ("fluids", "Fluid check & top-up"),
        ("valve_adjust", "Overhead valve adjustment"),
        ("wash", "Wash / detail"),
    ]),
    ("compliance", "Inspections & compliance", [
        ("annual_inspection", "DOT annual inspection"),
        ("state_inspection", "State inspection"),
        ("emissions_test", "Emissions / smoke test"),
        ("dvir_repair", "DVIR defect repair"),
        ("roadside_violation", "Roadside inspection violation"),
        ("recall", "Recall"),
        ("warranty", "Warranty repair"),
    ]),
    ("engine", "Engine", [
        ("engine_repair", "Engine repair"),
        ("engine_overhaul", "Engine overhaul / in-frame"),
        ("turbo", "Turbocharger"),
        ("fuel_system", "Injectors & fuel system"),
        ("cooling", "Radiator, water pump & hoses"),
        ("coolant_flush", "Coolant flush"),
        ("belts", "Belts & tensioners"),
        ("oil_leak", "Oil leak"),
        ("egr", "EGR valve / cooler"),
        ("engine_brake", "Engine brake (Jake)"),
        ("engine_sensors", "Engine sensors"),
    ]),
    ("aftertreatment", "Aftertreatment & emissions", [
        ("dpf_clean", "DPF cleaning"),
        ("regen", "Forced / parked regen"),
        ("def_system", "DEF doser, pump & heater"),
        ("scr_nox", "SCR catalyst & NOx sensors"),
        ("doc", "DOC"),
        ("exhaust", "Exhaust pipes & leaks"),
    ]),
    ("drivetrain", "Transmission & drivetrain", [
        ("transmission_service", "Transmission fluid service"),
        ("transmission_repair", "Transmission repair"),
        ("clutch", "Clutch adjust / replace"),
        ("driveshaft", "Driveshaft & U-joints"),
        ("differential", "Differential / rear-end service"),
        ("wheel_seals", "Wheel bearings & hub seals"),
    ]),
    ("brakes", "Brakes & air system", [
        ("brake_adjust", "Brake adjustment"),
        ("brake_reline", "Brake shoes, drums & rotors"),
        ("brake_chambers", "Brake chambers & slack adjusters"),
        ("air_dryer", "Air dryer cartridge"),
        ("air_compressor", "Air compressor"),
        ("air_leak", "Air leak"),
        ("abs", "ABS / traction control"),
    ]),
    ("tires", "Tires & wheels", [
        ("tire", "Tire replacement"),
        ("tire_repair", "Flat / tire repair"),
        ("alignment", "Alignment & balancing"),
        ("wheels", "Wheels, rims & lug nuts"),
    ]),
    ("suspension", "Steering & suspension", [
        ("steering", "Steering gear & power steering"),
        ("front_end", "Tie rods, drag link & kingpins"),
        ("air_suspension", "Air bags & ride height"),
        ("shocks", "Shocks"),
        ("springs", "Leaf springs & U-bolts"),
        ("fifth_wheel", "Fifth wheel"),
    ]),
    ("electrical", "Electrical & electronics", [
        ("batteries", "Batteries"),
        ("starter", "Starter"),
        ("alternator", "Alternator / charging"),
        ("lights", "Lights & wiring"),
        ("ecm", "ECM / software update"),
        ("telematics", "ELD, camera & telematics"),
    ]),
    ("cab", "Cab & body", [
        ("hvac", "A/C & heater"),
        ("apu", "APU"),
        ("glass", "Windshield & glass"),
        ("mirrors", "Mirrors"),
        ("wipers", "Wipers & washer"),
        ("doors", "Doors, locks & latches"),
        ("interior", "Seats, bunk & interior"),
        ("body_damage", "Body / collision damage"),
    ]),
    ("trailer", "Trailer", [
        ("trailer_annual", "Trailer DOT annual"),
        ("trailer_brakes", "Trailer brakes"),
        ("trailer_tires", "Trailer tires"),
        ("trailer_lights", "Trailer lights & wiring"),
        ("reefer", "Reefer unit service"),
        ("landing_gear", "Landing gear"),
        ("trailer_doors", "Trailer doors, floor & seals"),
    ]),
    ("road", "Road service", [
        ("tow", "Towing"),
        ("roadside", "Roadside service call"),
    ]),
    ("other", "Other", [
        ("repair", "Other repair"),
        ("other", "Other"),
    ]),
]

KINDS = [key for _, _, items in GROUPS for key, _ in items]
KIND_LABELS = {key: label for _, _, items in GROUPS for key, label in items}
GROUP_OF = {key: group for group, _, items in GROUPS for key, _ in items}
GROUP_LABELS = {group: label for group, label, _ in GROUPS}


def label(kind):
    return KIND_LABELS.get(kind, (kind or "").replace("_", " "))


def kinds_in(group):
    return [key for key in KINDS if GROUP_OF[key] == group]
