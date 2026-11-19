# Reading a VIN and a unit profile
The VIN tells you the make, model, year, plant and often the engine, even when the unit profile in a system says OTHER.

## Overview
The VIN tells you the make, model, year, plant and often the engine, even when the unit profile in a system says OTHER. OTHER only means nobody picked the make or engine from the list when the unit was set up. The free [NHTSA VIN decoder](https://vpic.nhtsa.dot.gov/decoder/) fills in the details.

**How the 17 characters break down** (example: 1FUJGLBG9GLHG5090)

| Position | Example | Meaning |
|---|---|---|
| 1 to 3 | 1FU | Manufacturer code (WMI): who made it and in which country. 1 = USA, 2 = Canada, 3 = Mexico, 4 or 5 = USA |
| 4 to 8 | JGLBG | Vehicle details: model, cab, axles, and on many trucks the engine. Each brand codes these differently |
| 9 | 9 | Check digit, a math check that catches typos |
| 10 | G | Model year (table below) |
| 11 | L | Assembly plant |
| 12 to 17 | HG5090 | Serial number of that truck |

That example decodes to a 2016 Freightliner Cascadia 125" sleeper with a Cummins ISX15, built in Cleveland, North Carolina.

## Manufacturer codes (first three characters)

| Code | Maker |
|---|---|
| 1FU, 1FV, 3AK, 3AL | Freightliner |
| 5KJ, 5KK | Western Star |
| 4V4 | Volvo |
| 1M1, 1M2 | Mack |
| 1HS, 3HS | International |
| 1XP, 2XP | Peterbilt |
| 1XK, 1NK, 2NK | Kenworth |
| 1JJ | Wabash (trailers) |
| 1GR | Great Dane (trailers) |
| 1UY | Utility (trailers) |
| 3H3 | Hyundai Translead (trailers) |
| 1DW | Stoughton (trailers) |

## Model year (10th character)

| Code | Year | Code | Year | Code | Year |
|---|---|---|---|---|---|
| A | 2010 | G | 2016 | N | 2022 |
| B | 2011 | H | 2017 | P | 2023 |
| C | 2012 | J | 2018 | R | 2024 |
| D | 2013 | K | 2019 | S | 2025 |
| E | 2014 | L | 2020 | T | 2026 |
| F | 2015 | M | 2021 | V | 2027 |

Letters I, O, Q, U and Z are never used, so they can't be confused with numbers. 2001 to 2009 use the digits 1 to 9. The model year can be one year later than the build date: a truck built in late 2015 is often a 2016 model, which is why a unit profile can say 2015 when the VIN says 2016.

## Engine generations worth recognizing

| Engine | Years (roughly) | Notes |
|---|---|---|
| Detroit Series 60 | up to about 2011 | Old Detroit; no DEF on most |
| Detroit DD15 / DD13 | 2008 onward | Most common Freightliner engine; newer versions from 2017 |
| Cummins ISX15 | 2010 to 2017 | Older Cummins, common in used trucks |
| Cummins X15 | 2017 onward | Replaced the ISX15 |
| PACCAR MX-13 | 2010 onward | Peterbilt and Kenworth |
| Volvo D13 / Mack MP8 | 2010 onward | Volvo Group engines |

The model year also tells you which emission parts the truck has. Almost every truck from 2010 on has a DPF and DEF/SCR, so pre-2010 trucks don't get DEF invoices.

## The other fields on a unit profile

- **Unit number:** the fleet's own name for the truck. Match it on every invoice.
- **License plate and state:** used for roadside inspections, tolls and IFTA.
- **Engine:** the engine family, which decides parts and which dealer to call. If it says OTHER, get it from the VIN.
- **APU number:** the serial of the APU, if the truck has one.
- **Mileage:** the odometer at the last update. Around 700,000 to 1,000,000 miles, many engines are due for an in frame overhaul, and engine, turbo and emissions repairs get more frequent.
