# Aftertreatment (emissions)
DPF, DOC, SCR, DEF, regens and derates. This is where most road calls come from.

## Why it exists
Since 2007 and 2010 the EPA requires trucks to clean their exhaust. The equipment that does it sits in one or two big boxes under the passenger side of the cab. It works well when the truck runs long and hot, and gives trouble when a truck idles a lot or makes short trips.

## The parts, in the order the exhaust flows

![Exhaust flow through the aftertreatment system](aftertreatment.svg)

| Part | What it does | Trouble |
|---|---|---|
| DOC (diesel oxidation catalyst) | Burns leftover fuel and heats the exhaust for regen | Face plugging, cracked, gets "glazed" by oil or coolant |
| DPF (diesel particulate filter) | Traps soot | Fills up with soot and ash, needs regens and cleanings |
| DEF doser (injector) | Sprays DEF into the exhaust | Crystals clog it, doser faults |
| SCR (selective catalytic reduction) | DEF + catalyst turn NOx into nitrogen and water | Low efficiency codes |
| NOx sensors (inlet and outlet) | Measure NOx before and after SCR | Very common failure, around $500 to $1,000 each |
| Temperature and pressure sensors | Tell the ECM how hot and how full the system is | Wiring, sensor failure |
| DPF differential pressure sensor | Measures how plugged the DPF is | False "DPF full" readings when its hoses crack |

## Regen
Soot in the DPF must be burned off. That is a **regeneration**.
- **Passive regen:** happens on its own when the truck runs hot on the highway.
- **Active regen:** the engine adds fuel (or a doser sprays fuel) to heat the DPF to about 1,100 °F. Happens while driving. The **HEST** lamp (high exhaust system temperature) may light.
- **Parked (stationary) regen:** the driver parks, keeps the engine running and starts the regen from a switch. Takes 20 to 60 minutes. The dash asks for it when the DPF is too full for driving regens.
- **Forced / service regen:** a shop starts it with a laptop when the truck will not do it on its own.

If the driver ignores the regen request, the DPF gets fuller, the truck derates, and finally it needs a shop. **Most aftertreatment road calls start with a driver who skipped a parked regen.**

## Derate
When the ECM sees an emissions fault it cannot fix, it **limits power and speed** to force a repair. That is a derate. It usually happens in steps:
1. Warning lamp only.
2. Torque reduced (less power).
3. Speed limited, often 55 mph, later 5 mph after a long time or after a restart.

A truck in a 5 mph derate cannot drive to a shop; it needs a tow or a mobile fix. Always ask the driver: **what speed can the truck do right now?**

## DEF
Diesel exhaust fluid: 32.5% urea and water. Blue cap. About 2 to 3% of diesel use (roughly 1 gallon of DEF per 50 gallons of diesel).
- Frozen DEF is normal in winter; the truck has heaters.
- Bad or diluted DEF (or diesel put in the DEF tank) causes SCR efficiency codes and derates. Diesel in the DEF tank is a big repair: the whole DEF system must be flushed or replaced.
- DEF crystals (white crust) around the doser and lines mean leaks.

## DPF cleaning
Ash (from oil) does not burn off. Every 200,000 to 500,000 miles (or when restriction is high) the DPF and often the DOC are **removed and cleaned** with a bake-and-blow machine. Many fleets keep a cleaned spare and swap it ("core exchange") so the truck is down less than a day. Cost is roughly $400 to $1,200 for the cleaning, more with labor.

## Common codes you will hear
- **SPN 3719 / 3251:** DPF soot load and DPF differential pressure. Usually means a regen is needed.
- **SPN 3720:** DPF ash load. The filter needs cleaning, a regen will not fix it.
- **SPN 4364:** SCR conversion efficiency low. DEF quality, doser, NOx sensors.
- **SPN 3226 / 3216:** NOx sensor outlet or inlet.
- **SPN 5246:** aftertreatment SCR operator inducement severity. This is the derate warning itself.
- **SPN 4094:** NOx limits exceeded due to insufficient reagent quality.

Codes differ a bit by engine maker. Kaido's Faults page explains each code it sees.

## What to ask the driver
1. Which lamps are on: DPF, DEF, check engine, HEST?
2. Did the truck ask for a parked regen, and did they do it?
3. What speed can the truck do?
4. How much DEF is in the tank, and where did they last fill it?
5. Any white crust around the exhaust?

## Videos
@video How DPF regeneration works | how DPF regeneration works semi truck
@video How to do a parked regen | how to do a parked regen semi truck
@video What is SCR and DEF | SCR DEF system explained diesel truck
@video Why trucks derate | semi truck derate explained DEF DPF
