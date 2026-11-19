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

## More detail
A code like **SPN 3251 FMI 0** has two halves: the **SPN** says which part or reading, and the **FMI** says what kind of problem. The same SPN numbers are used by every brand on the J1939 standard, but each engine maker adds its own codes, so a mechanic always confirms with a diagnostic laptop. Drivers can read codes from the dash menu on most trucks.

## Common SPNs

| SPN | What it's about | Usually means |
|---|---|---|
| 3719 | DPF soot load | DPF is filling up; needs a regen. If ignored, derate |
| 3251 | DPF differential pressure | DPF clogged, or the pressure sensor or its hoses are bad |
| 3242, 3246 | DPF inlet / outlet temperature | Temperature sensor fault, or a regen problem |
| 4765 | DOC inlet temperature | Sensor fault or DOC problem |
| 3216 | NOx sensor, inlet (before SCR) | Bad NOx sensor. Very common |
| 3226 | NOx sensor, outlet (after SCR) | Bad NOx sensor. Very common |
| 4364 | SCR conversion efficiency | SCR not cleaning well: bad DEF, bad sensor, doser or catalyst |
| 4094 | NOx too high from poor DEF | DEF quality or dosing problem |
| 3364 | DEF quality | Diluted or wrong DEF, or a bad quality sensor |
| 1761 | DEF tank level | Low DEF, or tank sender fault |
| 3031 | DEF tank temperature | Sensor or heater fault |
| 4334 | DEF doser pressure | DEF pump, lines or doser clogged |
| 5246 | SCR inducement (derate warning) | The truck is counting down to a speed derate because of a DEF/SCR fault |
| 1569 | Engine protection torque derate | Power limited to protect the engine; look at the other active codes for the cause |
| 27 | EGR valve position | EGR valve sticking or failed |
| 412 | EGR temperature | EGR cooler or sensor problem |
| 102 | Boost pressure | Turbo, CAC leak, or sensor |
| 105 | Intake manifold temperature | Sensor or CAC problem |
| 100 | Engine oil pressure | Low oil pressure (stop the engine) or sensor fault |
| 110 | Coolant temperature | Overheating or sensor fault |
| 111 | Coolant level | Low coolant or level sensor fault |
| 157 | Fuel rail pressure | Fuel pump, filter, leak or pressure sensor |
| 94 | Fuel delivery pressure | Clogged fuel filter, lift pump, air in fuel |
| 97 | Water in fuel | Drain the fuel water separator |
| 168 | Battery voltage | Weak batteries, alternator, or bad connections |
| 84 | Vehicle speed | Speed sensor fault |
| 117, 118 | Brake air pressure, primary / secondary | Low air or sensor fault |
| 629 | ECM internal fault | Computer problem; may need reprogramming or replacement |
| 639 | J1939 data network | Wiring or module communication problem |

## What the FMI number means

| FMI | Meaning in plain words |
|---|---|
| 0 | Too high, severe |
| 1 | Too low, severe |
| 2 | Reading is erratic or doesn't make sense |
| 3 | Voltage too high (usually wiring shorted to power) |
| 4 | Voltage too low (usually wiring shorted to ground) |
| 5 | Open circuit (broken wire or unplugged) |
| 6 | Current too high (grounded circuit) |
| 7 | Mechanical part not responding (stuck valve, actuator) |
| 8, 9, 10 | Abnormal signal (frequency, update rate or rate of change) |
| 11 | Fault, cause not identified |
| 12 | Bad device or module |
| 13 | Out of calibration |
| 14 | Special instructions (check the maker's manual) |
| 15 | Slightly high |
| 16 | Moderately high |
| 17 | Slightly low |
| 18 | Moderately low |
| 19 | Bad data received from another module |
| 31 | Condition exists |

**How to use it on a call.** FMI 3, 4 and 5 usually point to wiring or a sensor, which is cheaper and often fixable roadside. FMI 0, 1, 7, 15 to 18 usually mean the system really is out of range: an actual clog, leak or failed part. Several emissions codes at once plus SPN 1569 or 5246 means the truck is derated or about to be.

## Videos
@video Reading SPN and FMI codes | how to read SPN FMI fault codes
@video Semi truck dash warning lights | semi truck dashboard warning lights meaning
