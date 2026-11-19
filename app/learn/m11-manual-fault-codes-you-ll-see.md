# Fault codes you'll see
A code like **SPN 3251 FMI 0** has two halves: the **SPN** says which part or reading, and the **FMI** says what kind of problem.

## Overview
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
