# Kaido

Fleet maintenance for a company that runs its own trucks and manages trucks for
several other carriers. It is meant to be the one place every repair is logged —
for any truck and any driver, including ones from outside the company.

## What it does

- **Work orders** in 81 work types across 13 systems: preventive maintenance,
  inspections and compliance, engine, aftertreatment (DPF, DEF, SCR/NOx), transmission
  and drivetrain, brakes and air, tires and wheels, steering and suspension,
  electrical, cab and body, trailer, road service, other. Grouped roughly along the
  ATA/TMC VMRS system codes.
- **Service schedule** by miles or by date: oil, DOT annual, PM-A, PM-B, PM-C, air
  dryer, transmission fluid, differential fluid, coolant and DPF cleaning. Each
  company sets its own intervals; severe-duty trucks come due sooner.
- **Samsara sync** every 15 minutes: odometer, GPS, J1939/OBD-II fault codes, DVIR
  defects. Stop-lamp faults go to Telegram the moment they are seen.
- **Fleet map** on the dashboard, coloured by what each truck needs.
- **Where to send it**: nearby truck shops from OpenStreetMap with address, phone,
  a Call button, a Google Maps link and Claude's pick.
- **Claude** explains fault codes in plain words, suggests the oil from the engine
  read off the VIN, and answers questions about any truck — under a hard daily cap.
- **Daily follow-up** on Telegram: open breakdowns, overdue service, work that was
  due, reminders, new faults, papers expiring. Reminders can be set on any record.
- **Fuel**: manual entry and EFS Transaction Report import.
- **Reports** for maintenance, fuel, breakdowns, faults and fleet status as PDF,
  Excel or CSV.
- **Company lock**: Postgres row-level security on every company table, so a
  carrier's users only ever see their own company.

## Stack

Python 3.9 · Flask · PostgreSQL 16 · Jinja templates · plain CSS and JS.
No build step, no frontend framework. Shell scripts in `bin/` run it.

## Layout

    app/
      __init__.py     app factory, security headers, session and CSRF middleware
      config.py       .env loader
      db.py           psycopg connection pool and query helpers
      security.py     scrypt passwords, AES-GCM credential encryption, CSRF tokens
      auth.py         sessions, trusted devices, one-time codes, throttling
      tenancy.py      companies, memberships, role checks
      queries.py      service status, due dates for every tracked service, dashboard aggregates
      work_types.py   the 81 work types, their systems, and the service schedule defaults
      samsara.py      Samsara REST client and fault-code parser
      sync.py         the sync engine: vehicles, odometer, positions, faults, DVIR defects
      shops.py        OpenStreetMap shop search, opening-hours parser, lookup cache
      advisor.py      the Claude calls: shop notes and pick, fault explanations, oil, truck chat
      vehicles.py     engine lookup from the VIN (NHTSA decoder)
      followup.py     the daily Telegram follow-up
      reminders.py    reminders on any record
      reports.py      report queries and PDF / Excel / CSV output
      fuel_import.py  EFS Transaction Report import
      sheets.py       reading uploaded Excel and CSV files
      views/          one blueprint per section
      templates/      Jinja templates
      static/         app.css, app.js, fleet.js, shops.js, favicon, vendor/leaflet
    bin/              run, serve, sync, backup
    db/schema.sql     the whole schema
    manage.py         CLI

## First run

    python3 -m venv venv
    ./venv/bin/pip install -r requirements.txt
    cp .env.example .env          # fill in DATABASE_URL, SECRET_KEY, ENCRYPTION_KEY
    ./venv/bin/python manage.py migrate
    ./venv/bin/python manage.py bootstrap --email you@example.com --name "Your Name" --company "House Fleet"
    ./bin/run.sh

`bootstrap` prints a temporary password once. Sign in at http://127.0.0.1:8790.

## Signing in

Password, then a six-digit code sent to Telegram the first time a browser is used.
That browser is then trusted for `TRUST_DAYS` (30 by default), so day to day it is
password only. Set `TRUST_DAYS=1` for a code every day.

Without `TELEGRAM_BOT_TOKEN` set, codes print to the server log — development only.
In production a user with no linked Telegram cannot sign in from a new device.

To link Telegram: Account → Get link code, then send `/link <code>` to the bot with
`./venv/bin/python manage.py telegram-bot` running.

Every sign-in message carries a block link. Following it cancels the attempt, locks
the account, and signs out every session and trusted device.

## Roles

| Role | Can |
|---|---|
| admin | everything in the company: trucks, drivers, fuel, work orders, breakdowns, people, integrations |
| viewer | read only |

Platform staff (`platform_role`) see and administer every company.

## Samsara

Connect per company at Integrations. The token needs read scopes for Vehicles,
Vehicle Statistics and DVIRs. It is encrypted with AES-GCM before storage.

A sync pulls vehicles (matched to trucks by VIN, then unit number), odometer
readings, engine fault codes and DVIR defects. Faults that stop appearing are
closed automatically. Run it from the Integrations page, or on a schedule:

    */15 * * * * /root/kaido/bin/sync.sh

## Commands

    manage.py migrate                     apply db/schema.sql
    manage.py bootstrap --email --name    create the first platform owner
    manage.py add-company --name          add a carrier
    manage.py add-user --email --name --company --role
    manage.py sync --all                  pull from Samsara for every connected company
    manage.py telegram-bot                link Telegram accounts
    manage.py demo --company              sample trucks, fuel and a breakdown
    manage.py ai-spend                    what the AI notes have cost so far

## The fleet map

The dashboard opens on a map of every truck that has reported a position, drawn
from the same Samsara sync. A dot is red when the truck has an open breakdown or
is overdue for service, amber when it has an active fault or is due soon, green
when there is nothing outstanding. Hovering names the unit and its driver;
clicking opens the driver, the truck, where it is, how long ago it said so, the
odometer, anything wrong with it, and a link into the truck's page. A company
with no telematics sees a line saying so instead of an empty map.

## Where to send it

Pick a truck on a work order and the form offers to look for shops near it. The
truck's position comes from Samsara on every sync, and the map shows where the
driver is. **A truck with no Samsara feed is not a dead end**: type an address,
a city and state, or the name of a truck stop into the box, or click anywhere on
the map, and the search runs from there. Addresses are resolved by Nominatim and
cached for 90 days. Shops come from OpenStreetMap
through Overpass — truck repair, truck stops, tyre and car repair, and HGV fuel —
sorted so the ones that take a Class 8 tractor come first, then the ones that are
open, then by distance. If fewer than three confirmed truck shops are within
`SHOP_RADIUS_MILES` (50), it widens to 100.

Each shop shows its address, how far it is, what the round trip costs in diesel
(`DIESEL_PRICE` ÷ `TRUCK_MPG`) and how long it takes at `ROAD_SPEED_MPH`, its
opening hours read from the OSM `opening_hours` tag, its phone, and what this
company has paid there before — matched against past oil invoices by name.
*Call* opens the phone's dialer, *Google Maps* opens the shop there, *Show on map*
zooms to it and enlarges its pin, and *Use as vendor* fills the vendor field.
Most OpenStreetMap shops have no phone listed; Google Maps is the fallback, and
Claude is never asked to supply one.

The search runs in steps so nothing sits on a blank "waiting": the list and map
come back as soon as OpenStreetMap answers, then Claude's pick
(`/maintenance/shops/<id>/advice`) and any missing street addresses
(`/maintenance/shops/address`, a Nominatim reverse lookup cached 90 days) fill in
while a progress bar shows how far along it is. The percentage inside each step is
an estimate — neither service reports its own progress.

Answers are cached per 0.01° cell for seven days, so the same corner of the map
is only asked for once a week, and a stale answer is served if Overpass is busy.
The map is Leaflet, served from `static/vendor`; only the tiles come from
openstreetmap.org.

`Referrer-Policy` is `strict-origin-when-cross-origin` **because the map depends
on it**. OpenStreetMap's volunteer tile servers answer requests they cannot
identify with a 403 "Access blocked" tile, and under `same-origin` the browser
sends them no referrer at all. Tightening that header back breaks every map on
the site, silently — the tiles still return 200, they just say Access blocked.

With `ANTHROPIC_API_KEY` set, Claude (`AI_MODEL`, Haiku 4.5 by default) adds one
line per shop and names the one to send the truck to. It is told to use nothing
but the data above — no invented hours, prices or reviews — and past invoices from
this fleet outrank everything else. Without the key the list works exactly the
same, minus those lines.

Spending is capped. Every call is priced and written to `ai_usage`; once the day's
total reaches `AI_DAILY_USD` (20 cents) the notes stop until tomorrow and the list
carries on without them. Answers are also cached for seven days, so opening the
same truck in the same place again costs nothing. A lookup is about a quarter of a
cent.

    manage.py ai-spend                    what it has cost, per day and all time
    manage.py ai-spend --credit 5         how far a given amount of credit goes

## Service schedule

Oil is per truck (`oil_interval_miles`), 25,000 miles by default and 15,000 for
severe duty. The DOT annual inspection is tracked from the last recorded
inspection date and warns 30 days out; completing an `annual_inspection` work
order resets it.

The rest are company-wide, set on Trucks → Service intervals (`service_intervals`):

| Service | Default |
|---|---|
| PM-A | 15,000 mi |
| PM-B | 45,000 mi |
| PM-C | 150,000 mi |
| Air dryer | 60,000 mi or 12 months |
| Transmission fluid | 60,000 mi |
| Differential fluid | 60,000 mi |
| Coolant | 150,000 mi or 36 months |
| DPF cleaning | 300,000 mi |

The defaults are the middle of published Class 8 schedules; OEM intervals vary a
lot (synthetic transmission fluid and extended-life coolant can run far longer), so
check them against the manuals. Severe-duty trucks are due 25% sooner on miles. A
PM-B also counts as a PM-A and a PM-C as both. A "next due" typed on a work order
wins over the interval. Nothing is counted for a service until one is on record —
Trucks → Service baselines takes the last one per truck, typed or from a sheet.

Overdue and due-soon items show on the dashboard, the truck list, the truck's own
Service schedule, the daily follow-up and the fleet status report.

## Not built yet

The EFS automatic feed (the report import works today), DVIR scope on the Samsara
token, and Love's. See the build map.
