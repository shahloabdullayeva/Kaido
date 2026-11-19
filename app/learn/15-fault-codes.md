# Dash lamps and fault codes
What each warning lamp means and how to read SPN/FMI codes.

## Dash lamps

![A truck dashboard: gauges in the middle, warning lamps around them](dash-kenworth.jpg)

| Lamp | Meaning | What to tell the driver |
|---|---|---|
| Amber check engine / warning | A fault was found; the truck can usually keep driving | Get the code, keep driving carefully, plan a shop visit |
| Red stop engine | Serious fault: low oil pressure, high coolant temperature, etc. | Pull over safely and shut down. Many engines shut down by themselves |
| MIL (malfunction indicator, emissions) | Emissions-related fault | Get the code, check DEF and DPF lamps |
| DPF lamp (solid or flashing) | Soot load high. Flashing = more urgent | Do a parked regen as soon as safe |
| HEST (high exhaust temperature) | Regen in progress, exhaust very hot | Normal during regen. Keep away from dry grass and fuel |
| DEF lamp | DEF low or DEF system fault | Fill DEF; if full, it is a system fault |
| ABS lamp (tractor or trailer) | ABS fault; normal brakes still work | Get it checked soon; it is a roadside violation |
| Low air warning (plus buzzer) | Air pressure below about 60 psi | Stop. Spring brakes will apply if it keeps dropping |
| Water in fuel | Water in the fuel separator | Drain the separator |
| Battery / charging | Charging system fault | Check belts and voltage; plan a shop before the truck dies |

## SPN and FMI
Heavy trucks use the **J1939** code format. Each fault has:

![How to read a fault code](fault-code.svg)

- **SPN (Suspect Parameter Number):** what part or value is affected. Example: SPN 110 is engine coolant temperature; SPN 100 is engine oil pressure.
- **FMI (Failure Mode Identifier):** how it failed, from 0 to 31.
- **Source address / MID:** which computer reported it (engine, transmission, ABS, aftertreatment).
- **Occurrence count:** how many times it happened.
- **Active or inactive (stored).** An inactive code happened before but is not happening now.

## FMI meanings worth knowing
| FMI | Meaning |
|---|---|
| 0 | Value too high (most severe level) |
| 1 | Value too low (most severe level) |
| 2 | Data erratic or intermittent |
| 3 | Voltage above normal, or shorted to power |
| 4 | Voltage below normal, or shorted to ground |
| 5 | Current below normal, or open circuit |
| 7 | Mechanical system not responding |
| 9 | Abnormal update rate (lost signal) |
| 11 | Root cause not known |
| 12 | Bad device or component |
| 14 | Special instructions |
| 15 to 18 | Value high or low, less severe levels |
| 19 | Network data error |
| 31 | Condition exists |

**FMI 3, 4 and 5 point to wiring or the sensor, not the system it measures.** "Coolant temperature sensor voltage high" (SPN 110 FMI 3) is a sensor or wire problem, not a hot engine. That difference saves money: a $60 sensor versus a cooling system repair.

## Codes you will see often
| SPN | What it is |
|---|---|
| 100 | Engine oil pressure |
| 110 | Engine coolant temperature |
| 111 | Coolant level |
| 157 | Fuel rail pressure |
| 168 | Battery voltage |
| 190 | Engine speed |
| 102 | Boost pressure |
| 3216 / 3226 | NOx sensor, inlet / outlet |
| 3251 | DPF differential pressure |
| 3719 | DPF soot load |
| 4364 | SCR conversion efficiency |
| 5246 | SCR inducement (derate warning) |
| 3720 | DPF ash load |
| 639 | J1939 data link (network) |
| 1761 | DEF tank level |

## How to use codes on a call
1. Ask the driver to read the code from the dash, or read it in Samsara or Kaido's Faults page.
2. Look at active codes first.
3. Group related codes: five aftertreatment codes at once usually have one root cause.
4. Check the occurrence count and whether it came back after a past repair.
5. Use the code to decide: keep driving, drive to a shop, or stop now.

Kaido's Faults page lists codes from Samsara and explains each one.

## Videos
@video Reading SPN and FMI codes | how to read SPN FMI fault codes
@video Semi truck dash warning lights | semi truck dashboard warning lights meaning
