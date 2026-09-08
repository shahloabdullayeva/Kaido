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
      sync.py         the sync engine: vehicles, odometer, faults, DVIR defects
      views/          one blueprint per section
      templates/      Jinja templates
      static/         app.css, app.js, favicon
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
| admin | everything in the company, including people and integrations |
| manager | trucks, drivers, all records, connect Samsara |
| dispatcher | log fuel, work orders, breakdowns, odometer |
| mechanic | update and close work orders and breakdowns |
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

## Maintenance intervals

Oil is per truck (`oil_interval_miles`), 25,000 miles by default and 15,000 for
severe duty. The DOT annual inspection is tracked from the last recorded
inspection date and warns 30 days out. Completing a work order of kind
`annual_inspection` resets that date.

## Not built yet

EFS fuel card feeds, Google Maps nearby search, AI fault triage. See the build map.
