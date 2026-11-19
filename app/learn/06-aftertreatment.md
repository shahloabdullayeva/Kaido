# Air intake, turbo and aftertreatment
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

## More detail
This is the system behind the most breakdowns and the most expensive invoices on modern trucks, so it is worth learning well. It has two halves: getting clean, dense air **into** the engine, and cleaning the exhaust **out** of it so the truck meets EPA emission rules.

## The path the air takes

Air filter → turbo (compressor side) → charge air cooler → intake manifold → cylinders → exhaust manifold → turbo (turbine side) → DOC → DPF → DEF injection → SCR → tailpipe. The EGR system takes a little exhaust from near the exhaust manifold and sends it back into the intake.

## Air in

| Part | What it does | Common problems |
|---|---|---|
| Air filter | Cleans the air before it enters the engine | Clogged filter = low power, bad fuel mileage. Cheap PM item |
| Turbocharger | A fan spun by exhaust gas that forces extra air into the engine for more power | Oil leaks, whistling, low power, bearings failing. Replacement is a big job |
| Turbo actuator | Controls how much boost the turbo makes | Fails often; truck loses power and throws a code |
| Charge air cooler (CAC), also called intercooler | A radiator for air. The turbo heats the air; the CAC cools it so it is denser | Cracks and leaks = low power, black smoke |
| CAC hoses and clamps | Connect turbo, CAC and engine | Blown hose = sudden loss of power, loud whoosh |

## Exhaust out (the aftertreatment system)

| Part | What it does | Common problems |
|---|---|---|
| EGR valve and EGR cooler | Sends some cooled exhaust back into the intake. Lowers combustion temperature, which lowers NOx (a pollutant) | EGR cooler leaks coolant into the exhaust; valve sticks. Very common on older engines |
| DOC (Diesel Oxidation Catalyst) | First filter in the exhaust. Burns off some pollutants and heats the exhaust for the DPF | Gets clogged or face plugged |
| DPF (Diesel Particulate Filter) | Traps soot (black smoke particles) | Fills up with soot and ash. Needs regens and periodic cleaning |
| DEF tank, pump and doser | Sprays DEF (Diesel Exhaust Fluid, a urea and water mix, the blue cap tank) into the exhaust | Crystals clog the doser, pump fails, bad or diluted DEF |
| SCR (Selective Catalytic Reduction) | Where DEF reacts with NOx and turns it into nitrogen and water | Low efficiency codes |
| NOx sensors | Measure NOx before and after the SCR so the ECM knows it works | Fail very often, common road service call |

**Regens.** The DPF cleans itself by burning the soot off at very high heat, which is called a regeneration. A **passive regen** happens on its own during highway driving. An **active regen** is when the ECM adds extra fuel to heat the exhaust while driving. A **parked regen** (or forced regen) is when the driver or a mechanic starts it while the truck sits, usually 30 to 60 minutes. If regens keep failing, the DPF has to be pulled and cleaned or replaced.

**Derate.** When the emissions system has a problem (DPF too full, DEF empty or bad, bad NOx sensor), the ECM **derates** the truck: it cuts power and speed, sometimes down to 5 mph, to force a repair. A derated truck is basically a breakdown, and it is one of the most common road service calls you'll see.

**Dash lights to know:** check engine (yellow), stop engine (red, pull over), DPF light (needs a regen), high exhaust temp light (regen in progress), DEF gauge and warning.

## Videos
@video How DPF regeneration works | how DPF regeneration works semi truck
@video How to do a parked regen | how to do a parked regen semi truck
@video What is SCR and DEF | SCR DEF system explained diesel truck
@video Why trucks derate | semi truck derate explained DEF DPF
