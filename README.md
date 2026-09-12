# Kaido

Fleet maintenance for a company that manages trucks for several carriers.
Companies, trucks, drivers, fuel, work orders, breakdowns and Samsara telematics,
with each carrier's data scoped to its own company.

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
      queries.py      service status, PM due dates, dashboard aggregates
      samsara.py      Samsara REST client and fault-code parser
      sync.py         the sync engine: vehicles, odometer, positions, faults, DVIR defects
      shops.py        OpenStreetMap shop search, opening-hours parser, lookup cache
      advisor.py      the Claude calls: a line per shop and which one to pick
      views/          one blueprint per section
      templates/      Jinja templates
      static/         app.css, app.js, favicon, vendor/leaflet
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

Each shop shows how far it is, what the round trip costs in diesel
(`DIESEL_PRICE` ÷ `TRUCK_MPG`) and how long it takes at `ROAD_SPEED_MPH`, its
opening hours read from the OSM `opening_hours` tag, and what this company has
paid there before — matched against past oil invoices by name. *Use as vendor*
fills the vendor field in the form.

Answers are cached per 0.01° cell for seven days, so the same corner of the map
is only asked for once a week, and a stale answer is served if Overpass is busy.
The map is Leaflet, served from `static/vendor`; only the tiles come from
openstreetmap.org.

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

## Maintenance intervals

Oil is per truck (`oil_interval_miles`), 25,000 miles by default and 15,000 for
severe duty. The DOT annual inspection is tracked from the last recorded
inspection date and warns 30 days out. Completing a work order of kind
`annual_inspection` resets that date.

## Not built yet

EFS fuel card feeds, AI fault triage, the reminder engine. See the build map.
