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

## Videos
@video Testing truck batteries | how to test semi truck batteries
@video J1939 diagnostics basics | J1939 diagnostic port semi truck basics
@video Trailer light troubleshooting | trailer lights 7 way troubleshooting semi
