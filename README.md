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
- **Horizon ELD sync** every 15 minutes, next to Samsara: drivers, duty status and
  the four HOS clocks (break, drive, shift, cycle), and which driver is in which truck.
- **Drivers** are imported from the truck names on every sync and kept in step with
  Horizon. Outside trucks and drivers can be logged too and stay off the fleet totals.
- **Pre-trip inspections (PTI)** from the driver's phone through a per-truck link:
  the 11 FMCSA 396.11 items, a photo or video for each, Claude checking the photos,
  a Telegram alert on any defect, sign-off by an admin.
- **Truck Telegram groups**: one group per truck, with its own PTI reminders and
  nudges when the truck drives without a pre-trip.
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
- **Notification center**: a pixel cat in the top bar brings notes and reminders,
  with a history of the last 20.
- **Dark mode**, chosen per user on the Settings page (auto, light or dark).
- **Pages update themselves** after a deploy. No hard refresh is ever needed.
- **Twice-weekly summary** to each company's admins, and nightly backups.

## Stack

Python 3.9 · Flask · PostgreSQL 16 · Jinja templates · plain CSS and JS.
No build step, no frontend framework. Shell scripts in `bin/` run it.

## Layout

    app/
      __init__.py     app factory, security headers, session and CSRF middleware
      config.py       .env loader
      db.py           psycopg connection pool and query helpers
      security.py     scrypt passwords, AES-GCM credential encryption, CSRF tokens
      auth.py         sessions, one-time codes, throttling
      tenancy.py      companies, memberships, role checks
      captcha.py      login captcha: built-in picture, or hCaptcha when keys are set
      billing.py      monthly invoices per company and their PDF
      queries.py      service status, due dates for every tracked service, dashboard aggregates
      work_types.py   the 81 work types, their systems, and the service schedule defaults
      samsara.py      Samsara REST client and fault-code parser
      horizon.py      Horizon ELD client and sync: drivers, vehicles, HOS clocks
      sync.py         the sync engine: vehicles, odometer, positions, faults, DVIR defects
      shops.py        OpenStreetMap shop search, opening-hours parser, lookup cache
      advisor.py      the Claude calls: shop notes and pick, fault explanations, oil, truck chat
      vehicles.py     engine lookup from the VIN (NHTSA decoder)
      followup.py     the daily Telegram follow-up
      reminders.py    reminders on any record
      reports.py      report queries and PDF / Excel / CSV output
      fuel_import.py  EFS Transaction Report import
      sheets.py       reading uploaded Excel and CSV files
      pti.py          pre-trip inspections: checklist, media, sign-off, reminders
      pti_driver.py   the driver's side of a PTI, opened from the truck's link
      pti_ai.py       Claude's check of every PTI photo
      telegram.py     the bot: sign-in codes, account and truck-group linking
      cat.py          the notification center and the page version check
      summary.py      the twice-weekly summary to admins
      encourage.py    the 8pm note from the cat
      google_places.py  Google Places search, used when a key is set
      audit.py        the audit trail
      logs.py         error log with secrets stripped
      views/          one blueprint per section
      templates/      Jinja templates
      static/         app.css, app.js, cat.js, fleet.js, shops.js, favicon, vendor/leaflet
    bin/              run, serve, sync, followup, backup, encourage, golive
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

Password and a captcha, then a six-digit code sent to Telegram on every sign-in.
No browser is remembered.

The captcha is a built-in picture of five characters. Set `HCAPTCHA_SITE_KEY` and
`HCAPTCHA_SECRET` (free at hcaptcha.com) and the login page switches to hCaptcha's
click-the-pictures check instead; if hCaptcha cannot be reached, sign-in is refused.

Without `TELEGRAM_BOT_TOKEN` set, codes print to the server log — development only.
In production a user with no linked Telegram cannot sign in.

To link Telegram: Account → Get link code, then send `/link <code>` to the bot with
`./venv/bin/python manage.py telegram-bot` running.

Every sign-in message carries a block link. Following it cancels the attempt, locks
the account, and signs out every session.

Forgotten password: `./venv/bin/python manage.py reset-password <email>` sends a
temporary one to that user's Telegram and signs out their sessions.

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

## Horizon ELD

For carriers whose drivers are on Horizon ELD (hosconnect.com) as well as, or instead
of, Samsara. Horizon covers every driver on the ELD; Samsara may only cover some of
the trucks, so the two are merged rather than run side by side.

    manage.py horizon-connect --company BOOKIT --user <api user> --password <api password> --company-key <Company:...>
    manage.py horizon-sync --company BOOKIT

The API user, password and company id come from Horizon's API settings. They are
stored together, AES-GCM encrypted, in `integrations.credential`. The company id
is the whole string including its `Company:` prefix.

A sync pulls `/drivers`, `/vehicles`, `/latest_driver_statuses` and
`/latest_vehicle_statuses`:

- **Vehicles** are matched to trucks by VIN, then by unit number. A truck is only
  created when Horizon gives a VIN, so a messy unit name never makes a duplicate.
- **Drivers** are linked through `driver_links` and keep their Kaido record; a
  name typed in Kaido is never overwritten by a different one.
- **HOS** goes to `hos_status`: duty status and the break, drive, shift and cycle
  clocks, plus the last position the ELD reported.
- **The live truck wins.** When the same unit exists twice (once from Samsara, once
  from Horizon), both are kept and the driver goes to whichever one reported its
  position most recently. Horizon only moves a truck's position forward, never back.

Horizon has no fault codes or DVIRs; those stay with Samsara. `bin/sync.sh` runs
`horizon-sync --all` right after the Samsara sync, and a Samsara failure does not
stop it.

## Drivers

Samsara has no proper driver records for most carriers, so drivers are read from
the vehicle names on every sync: "BMG Unit #001B - Sam Reyes",
"4207 Alex Carter (Mercury)", "1323 Omar". The parser knows the local
conventions: *aka* is an honorific, not a surname; O/O means owner-operator; `&`
and `/` separate team drivers; brackets name the sub-carrier; pay notes like
"80 cpm" are dropped.

A driver who came from a truck name follows that truck when it is renamed
(`trucks.driver_from_name`). A driver set by hand, by Telegram `/unit`, or by
Horizon is never overwritten by the name parser.

Drivers and trucks from outside the company (`is_outside`, `outside_carrier`) can
have work orders like any other, so every repair lives in one place, but they stay
off the fleet map and the totals.

## Commands

    manage.py migrate                     apply db/schema.sql
    manage.py bootstrap --email --name    create the first platform owner
    manage.py add-company --name          add a carrier
    manage.py add-user --email --name --company --role
    manage.py reset-password EMAIL        temporary password to the user's Telegram
    manage.py sync --all                  pull from Samsara for every connected company
    manage.py horizon-connect --company --user --password
                                          store Horizon ELD credentials for a company
    manage.py horizon-sync --all          pull drivers, vehicles and HOS from Horizon
    manage.py followup [--show COMPANY]   send reminders, stop-lamp alerts and the follow-up
    manage.py telegram-bot                link Telegram accounts and truck groups
    manage.py cat --to WHO "text"         send a note through the notification center
    manage.py summary                     the twice-weekly summary to admins
    manage.py encourage                   the 8pm note
    manage.py pti-cleanup                 delete PTI photos and videos past 92 days
    manage.py saved-shop-details          fill missing saved-shop addresses
    manage.py demo --company              sample trucks, fuel and a breakdown
    manage.py ai-spend                    what the AI notes have cost so far
    manage.py google-usage                Google Maps calls today and this month

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

## Google Maps and saved shops

With `GOOGLE_MAPS_API_KEY` set, the shop finder asks Google Places instead of
OpenStreetMap: better coverage, a phone number and opening hours on nearly every
shop, and the Google rating. Typed addresses are geocoded by Google too. If Google
fails or today's allowance is used, the search quietly falls back to OpenStreetMap
(and says which it used under the list). Google's terms require its places to be
drawn on a Google map, so that panel's map becomes a Google map; the dashboard map
stays on OpenStreetMap.

**Cost.** A search is two Text Search (Enterprise) calls, $35 per 1,000 with the first
1,000 each month free; geocoding an address is $5 per 1,000 with 10,000 free.
`GOOGLE_DAILY_CALLS` (30) is a hard daily cap, which keeps a whole month under the free
1,000 — worst case about 15 fresh searches a day. Results are kept one hour (Google
does not allow longer), so reopening a work order right away is free. The map on the
page is a Dynamic Maps load, 10,000 free a month.

    manage.py google-usage                calls today and this month, with the estimated bill

Use two keys in Google Cloud: `GOOGLE_MAPS_API_KEY` restricted to this server's IP and
to *Places API (New)* and *Geocoding API*; `GOOGLE_MAPS_BROWSER_KEY` restricted to
`https://kaido.shahlo.blog/*` and to *Maps JavaScript API*. The browser key is visible
in the page, which is why it gets its own restrictions. Set a budget alert on the
billing account as well.

**Saved shops** (Maintenance → Saved shops) are the company's own list — paste Google
Maps links, one per line (Share → Copy link in the app; short `maps.app.goo.gl` links
work), or type a name and address. Every search lists any saved shop within 100 miles
first, with a blue pin and a "saved by" badge, and Claude is told to prefer them.
Reading a link costs nothing: the name and position come from the link itself and the
Google place id is an ID-only lookup, which Google does not bill.

A Google Maps link also works in the shop finder's search box.

**The search remembers where it looked.** Typing a place or clicking the map stores it
on the work order when it is saved, so reopening the order searches there again rather
than jumping back to the Samsara position. *Back to where Samsara has …* returns to it.

## Pre-trip inspections

Every truck has its own link (`/pti/<token>`, no login), sent to the driver over
Telegram; replacing it kills the old one. The checklist is the 11 FMCSA 396.11 items
in three sections. Each item needs a photo or a video (videos up to 50 MB), every
defect needs a photo and a note, and N/A is only allowed on coupling.

Claude (`AI_PHOTO_MODEL`, Opus 5.5 by default) checks every photo in the background
job and flags any that do not show what the item asks for: about 1.5 to 4 cents a
PTI, under the same `AI_DAILY_USD` cap as the rest. Checks past the cap wait for
the next day.

A defect sends a Telegram alert. An admin signs it off (repaired or not needed) and
the next driver has to confirm they read it. The PTI page lists trucks that drove
10+ miles today with no pre-trip. Photos and videos are deleted after 92 days
(`manage.py pti-cleanup`), past the three months FMCSA asks for.

**Truck groups.** Each truck has its own Telegram group with its driver and the
office. Add @kaidofleet_bot, send `/truck <code>` (the code is on the truck page),
and the driver sends `/unit` once. A group only ever hears about its own truck:
pre-trip and post-trip reminders on the company's chosen days (Monday and Thursday
by default), and a nudge any day the truck drives without one.

## Notification center

A black pixel cat waits behind the button left of your name in the top bar. When a
note arrives it walks out, waves and opens the panel; the last 20 read notes stay
under *Earlier*. Every page asks `/cat/pending` every 15 seconds.

    manage.py cat --to John --from Charlotte "text"

The same check carries a version of the templates and static files. When a deploy
changes it, an open page reloads itself, so nobody needs a hard refresh. If you are
in the middle of typing into a form it does not reload; a yellow bar asks you to
save and refresh instead. CSS and JS are served `no-cache`, so the reload picks up
the new files.

## Settings

Each user picks auto, light or dark on the Settings page. Dark mode is the same
old-school look (Verdana, Georgia, bordered tables, beveled buttons) on a dark
palette. Adding companies and the Website section are separate permissions
(`users.can_add_companies`, `users.can_see_site`) and new users never get them.

## Billing

Each company gets one invoice a month: trucks × `BILLING_RATE` (default $4), never
less than `BILLING_MINIMUM` (default $40). Trucks are counted on the day the invoice
is issued; sold and outside trucks are left out. The follow-up job issues the
month's invoices by itself, due 14 days later.

- **Billing** (account menu, company admins): this month's amount, every invoice,
  and a PDF of each. There is no way to pay online.
- **Platform → Billing** (platform staff): every company's invoices. Only the
  platform owner can mark one paid or not paid, recount a due invoice, or set a
  company's own price per truck (empty = default, 0 = not billed).

Settings, Billing, Account and Sign out sit in the menu under the user's name.

## Error log

Warnings and errors from the web app, the sync, the follow-up and the Telegram bot all
go to `logs/errors.log`, with bot tokens and API keys stripped out. It is rotated weekly
with the other logs (`deploy/kaido.logrotate`, installed at `/etc/logrotate.d/kaido`).

    tail -f logs/errors.log

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
token, and Love's.
