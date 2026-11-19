# Electrical
Batteries, starting, charging, lights, and the computers on the truck.

## Batteries
A truck has **3 or 4 group 31 batteries** wired in parallel for 12 volts. Some trucks have a separate battery bank for the sleeper (for battery HVAC). Common trouble:
- Dead batteries after the driver ran the sleeper all night without the engine or APU.
- Corroded terminals and cables.
- One bad battery dragging down the others. Replace and test as a set.

A healthy resting battery reads about **12.6 V**; under 12.2 V it is low. While running, the system should show **13.8 to 14.4 V**.

## Starting
**Starter motor** turns the engine; a **starter relay or solenoid** switches it. A truck that only clicks: low batteries, bad cable, or a failing starter. Cold mornings show weak batteries first.

## Charging
The **alternator** charges the batteries and runs everything while driving. Signs of failure: battery lamp, low voltage on the gauge, dim lights. A broken belt stops the alternator too.

## Lights
DOT checks every light: headlamps, turn signals, brake lights, clearance and marker lamps, license plate lamp, reflective tape on the trailer. Light outages are the easiest roadside violations to get and the easiest to avoid. Drivers should check them every PTI.

The **7-way cord** (pigtail) carries power from tractor to trailer for lights and ABS. A green or corroded plug causes flickering trailer lights.

## Computers and networks
- **ECM:** engine control module. Holds fault codes, trip data, speed limits, idle shutdown settings.
- **TCM:** transmission control module.
- **ABS module:** brakes.
- **Body controller:** lights, gauges, switches.
- **Aftertreatment control module** on some engines.

They talk over a network called **J1939**. Shops plug into the **9-pin diagnostic port** (green or black round connector under the dash) with a laptop running the maker's software (Detroit DiagnosticLink, Cummins INSITE, PACCAR DAVIE, Volvo/Mack TechTool, International ServiceMaxx).

The **ELD** and telematics unit (Samsara, Motive, Omnitracs, Geotab and others) plug into the same port. That is how Kaido gets fuel level, location and fault codes from Samsara.

## Wiring problems
Chafed harnesses near the frame, corroded connectors under the cab, and water in connectors cause random faults that come and go. If the same sensor code keeps coming back after the sensor was replaced, suspect the wiring, not the part.

## More detail
Trucks run on **12 volts**, like a car, but with three or four batteries wired together to crank a huge diesel engine. "Truck won't start" is one of the most common breakdown calls, and it is usually batteries, cables, the starter or the alternator.

| Part | What it does | Common problems |
|---|---|---|
| Batteries (3 to 4) | Store power to start the engine and run the cab | Die in cold weather or when the driver runs the cab all night with the engine off |
| Battery cables and terminals | Connect everything | Corrosion (white/green crust), loose connections |
| Starter | Electric motor that spins the engine to start it | Clicks but won't crank |
| Alternator | Charges the batteries while the engine runs | Battery light on, batteries keep dying, low voltage |
| Fuses and relays | Protect circuits | Blown fuse = one thing stops working |
| Wiring harness | All the wiring in the truck | Chafed wires, water in connectors, hard to track down |
| Lights | Headlights, marker lights, turn signals, brake lights, clearance lights | Burned out bulbs and bad connections are the number one DOT roadside violation |
| 7 way plug (trailer cord) | The coiled green cable that sends power from tractor to trailer lights and ABS | Corrosion, broken pins = trailer lights out |
| APU (auxiliary power unit) | A small separate engine or battery pack that powers heat and AC while the driver sleeps, so the main engine can be off | Its own maintenance and breakdowns |
| Instrument cluster | The dashboard gauges and warning lights | Gauges stop working, false warnings |

**Fault codes.** When something goes wrong, the ECM (and other modules for the transmission, ABS and so on) stores a fault code. On heavy trucks the codes follow a standard called **J1939** and look like **SPN 3251 FMI 0**. The **SPN** says which part or system, and the **FMI** says what kind of failure (too high, too low, open circuit and so on). Drivers can often read codes on the dash, and a shop reads them with a laptop and diagnostic software (like Detroit's DiagnosticLink). When you handle a breakdown, the fault code is one of the first things to ask for, because it points the mechanic to the problem before he arrives.

**Telematics / ELD.** Most trucks have a device (Samsara, Motive, Omnitracs and others) that logs driver hours and often sends fault codes and location to the office in real time. Some fleets see a derate code before the driver even calls.

## Videos
@video Testing truck batteries | how to test semi truck batteries
@video J1939 diagnostics basics | J1939 diagnostic port semi truck basics
@video Trailer light troubleshooting | trailer lights 7 way troubleshooting semi
