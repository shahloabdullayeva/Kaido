# Kaido

Fleet maintenance for a company that runs its own trucks and manages trucks for
several other carriers. It is meant to be the one place every repair is logged —
for any truck and any driver, including ones from outside the company.

## What it does

- **One list for all work**: breakdowns and maintenance are the same record, a work
  order. It can start as a reported problem (unit, summary, priority, date) and grow into
  the full job once a shop is involved. README → Work orders.
- **Work orders** in 81 work types across 13 systems: preventive maintenance,
  inspections and compliance, engine, aftertreatment (DPF, DEF, SCR/NOx), transmission
  and drivetrain, brakes and air, tires and wheels, steering and suspension,
  electrical, cab and body, trailer, road service, other. Grouped roughly along the
  ATA/TMC VMRS system codes.
- **Service schedule** by miles or by date: oil, DOT annual, PM-A, PM-B, PM-C, air
  dryer, transmission fluid, differential fluid, coolant and DPF cleaning. Each
  company sets its own intervals; severe-duty trucks come due sooner.
- **Samsara sync** every 5 minutes (Horizon every 15): odometer, GPS, J1939/OBD-II fault codes, DVIR
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
  due, reminders, new faults, papers expiring. Reminders can be set on any record except work orders.
- **Fuel**: manual entry and EFS Transaction Report import, matched to trucks by unit number
  (or the number the unit starts with) and then by fuel card. The fuel list sorts newest or oldest first
  from the Date column.
- **Reports** for maintenance, fuel, breakdowns, faults and fleet status as PDF,
  Excel or CSV.
- **Company lock**: Postgres row-level security on every company table, so a
  carrier's users only ever see their own company.
- **Notification center**: a bell in the top bar shows notes and due reminders,
  with a history of the last 20.
- **Private platform only**: `/` sends anyone not signed in to the sign-in page. There is
  no public front page and no contact form, and every response carries `X-Robots-Tag: noindex`.
- **Fuel desk**: tank-level fuel stop suggestions in each truck's Telegram group with
  Accept / Skip buttons, driver preferences that Kaido learns, missed-savings analysis on
  every EFS purchase, and weekly picture reports for drivers and the office.
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
      pm_list.py      the editable service list: company additions and removals, per-truck overrides
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
      google_places.py  Google Places search, used when a key is set
      audit.py        the audit trail
      logs.py         error log with secrets stripped
      views/          one blueprint per section
      templates/      Jinja templates
      static/         app.css, modern.css, app.js, cat.js, fleet.js, shops.js, favicon, vendor/leaflet
    bin/              run, serve, sync, followup, backup, golive
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

Password and a captcha, then a six-digit code sent to Telegram on every sign-in. The code is
sent as its own `<code>` line, so tapping it in Telegram copies just the number.
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
    manage.py pti-cleanup                 delete PTI photos and videos past 92 days
    manage.py saved-shop-details          fill missing saved-shop addresses
    manage.py demo --company              sample trucks, fuel and a breakdown
    manage.py ai-spend                    what the AI notes have cost so far
    manage.py google-usage                Google Maps calls today and this month
    manage.py fuel-directory [--states NV,AZ]
                                          load truck stops from OpenStreetMap
    manage.py fuel-prepare [--company] [--recheck]
                                          match purchases to stations, find missed savings
    manage.py brand-prices [--brand loves] [--states TX,OK] [--limit N]
                                          today's pump prices from truck-stop websites
    manage.py trip --company --truck UNIT [--file load.txt] [--send]
                                          plan a load: route, fuel stops, hours, ETAs
    manage.py fuel [--force]              send fuel stop suggestions, match refuels
    manage.py fuel-demo --company [--days 28] [--remove]
                                          placeholder fuel purchases marked demo
    manage.py fuel-report [--company] [--dry-run] [--force]
                                          weekly fuel reports to drivers and admins

## The fleet map

The dashboard opens on a map of every truck that has reported a position, drawn
from the same Samsara sync. A dot is red when the truck has an open breakdown or
is overdue for service, amber when it has an active fault or is due soon, green
when there is nothing outstanding. Hovering names the unit and its driver;
clicking opens the driver, the truck, where it is, how long ago it said so, the
odometer, anything wrong with it, and a link into the truck's page. A company
with no telematics sees a line saying so instead of an empty map.

Map layers (dashboard and the unit page map, `app/static/map_layers.js`): Dark, Street (OpenStreetMap) and
Satellite (Esri World Imagery) bases; overlays for weather radar (NOAA/NWS MRMS reflectivity, WMS), weather
alert areas, saved shops, towing, truck parking and showers (the last three from the shop finder's
OpenStreetMap search, zoom 6 and closer). Traffic (TomTom flow tiles) appears only when `TOMTOM_API_KEY` is
set in `.env`; the free tier is 50,000 tile requests a day. The dashboard also filters trucks to all or
running only. Each browser remembers the last base, overlays and filter. The mouse wheel zooms every map while the pointer is on it. Hover shows the unit, driver,
moving/idling/parked, fuel and duty status; clicking a truck opens its unit page.

Weather (`app/weather.py`, `manage.py weather`, run by `bin/sync.sh` every 15 minutes): active National
Weather Service alerts from api.weather.gov (no key) for winter, ice, wind, flood, fog, cold, tornado and
severe thunderstorm events. Alerts with no polygon are drawn from their forecast zones, cached in
`weather_zones`. Trucks inside an alert area are stored in `truck_weather` and get a badge on the map, the
status board and the unit page; clicking the badge shows the alert text and when it ends.

## Where to send it

On a work order the panel opens with two buttons, Find shop and Find towing; it no longer asks whether the truck can drive.

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

**Place suggestions while typing** (`app/places.py`, `static/place_suggest.js`): both boxes in Where to send it show
up to 7 matches as you type. Two letters can match a state ("OK" gives Oklahoma). Towns and addresses come from
Photon (photon.komoot.io, free OpenStreetMap search made for type-ahead, no key), restricted to North America, towns
ranked first. Typos are fixed by Photon's own fuzzy match plus a second try with each word corrected against the 50
states and the ~1,150 truck-stop cities in `fuel_stations` ("amarilo tx" gives Amarillo, "memphs" gives Memphis).
Answers are cached 30 days in `place_suggestions`. Picking one searches for shops at that spot.

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
`https://kaidofleet.com/*` and to *Maps JavaScript API*. The browser key is visible
in the page, which is why it gets its own restrictions. Set a budget alert on the
billing account as well.

**Saved shops** (Maintenance → Saved shops) are the company's own list — paste Google
Maps links, one per line (Share → Copy link in the app; short `maps.app.goo.gl` links
work), or type a name and address. Every search lists any saved shop within 100 miles
first, with a blue pin and a "saved by" badge, and Claude is told to prefer them.
Reading a link costs nothing: the name and position come from the link itself and the
Google place id is an ID-only lookup, which Google does not bill.

A spreadsheet of shops goes in from the shell:
`venv/bin/python manage.py import-shops FILE.xlsx --company NAME [--user EMAIL] [--dry-run]`.
Columns: Title, Area / Address (or Area), Latitude, Longitude, Note, Map link. Shops
already saved (same Google Maps place, or same name within ~100 m) are skipped, and only
a new note is added to them. Rows without coordinates are looked up by address, then by
city. Sheets named Towing, Mobile service and Tire shops set the shop's `service`, which
the finder reads with the name and note to sort towing, road service and tires.

**Sort** on the shop list: Closest (default), Open now, Cheapest we paid (average of this
company's work orders at that shop), Best rated (own work-order ratings, then Google's), Used
before (visits, then saved shops). In every sort, shops confirmed to take semis come before
unconfirmed ones, and when the truck cannot drive, towing and road service come first. Saved
shops within 100 mi are mixed in by the same sort instead of always leading the list.

A finished work order with a shop name shows **Save shop** with a comment box (prefilled
with the work order's shop comment). It uses the work order's map spot, or looks up the shop
address; once saved, the work order shows it as a saved shop.

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
by default), and a nudge on those same days when the truck drives without one. When the group is
connected Kaido renames it to the unit ("Unit 5831"); the bot needs to be a group admin
with "Change group info" for that. `/rename` in the group does it again later.

## Fuel checks (fraud and theft)

`app/fuel_guard.py`, run every 5 minutes from `bin/followup.sh`, page Fuel → Fuel checks. Every
diesel purchase is checked once against what Samsara saw; each finding is stored in `fuel_alerts`
and sent to the company admins on Telegram (never to the driver), with a link to the page:

- **Fuel not in the tank**: 40+ gal bought but the tank rose by less than 60% of it (minus 10 gal
  of slack). High when under 30%.
- **Card used away from the truck**: the truck was never within 15 miles of the station (40 when the
  station is only placed at its city) around the purchase time.
- **More than the tank holds**: more gallons than the tank size, or than the room left in the tank
  just before (with 15% + 15 gal of slack).
- **Two fills close together**: two diesel purchases for one truck under 2 hours apart.
- **Tank dropped while parked**: Samsara's tank fell 12+ points (25+ gal) within an hour while the
  truck stood still, and the fuel is still missing once the truck runs on. Kaido waits 45 minutes to
  3 hours (or until the next fill), works out where the gauge should be after the miles driven
  (truck mpg, 6.5 if unknown), and alerts only if 10+ points and 20+ gal are still missing. A gauge
  that stays frozen over 50+ miles of driving is treated as a faulty sensor, not theft. Gauges often
  read low after a cold start or a fill (the two tanks evening out through the crossover line).

EFS times carry no time zone, so a purchase is matched to the truck's track across UTC, Central
and the station's own zone, one hour either side. Tank and location checks need the truck's
Samsara track, which Kaido keeps from 17 Nov 2026 on, so older purchases only get the capacity and
double-fill checks. Only findings from the last 3 days are sent to Telegram, so importing an old file
does not flood anyone. Admins mark each one "Looks OK" or "Confirmed problem", with a note.


## Trip planning

`app/trips.py`, the Trips page and `manage.py trip`. Paste a load as the load board or broker
sends it (load ID, $rate, `PU1:` name / address / `FCFS:` or `APPT:` window, `DEL1:` ..., any
number of stops), pick a truck, and Kaido plans the whole trip:

- **Delivered.** When the truck reaches the delivery the trip is set to done, and done trips show as
  "delivered" on the Trips page and the trip page.
- **Places instead of a load.** Without `PU`/`DEL` lines the box takes plain places: one per line or
  "Dallas, TX to Phoenix, AZ". One place is a fuel-only run from the truck to there; two or more are
  stops with no dock time or window ("Arrive" on the map and messages).
- **From the truck group.** With "Plan trips from load posts in truck groups" on (Fuel → Fuel
  assistant, off by default), a message in a group connected to one truck that has a pickup and a
  delivery with addresses is planned in the background and sent like the Send button: the first fuel
  stop with a Trip map link. Older open trips for that truck are cancelled; the same load number within
  3 days is ignored. If it cannot be planned the admins are told. Telegram only shows a bot normal group
  messages when the bot is a group admin, or when privacy mode is turned off in BotFather (`/setprivacy`),
  which then needs the bot removed and added back to each group.
- **Live map.** Every trip has a share link `/m/<token>` (no login, `trips.share_token`): route, start,
  pickup/delivery with ETA, numbered fuel stops with ETA and gallons, 10 h rests and restarts with time
  and place, and the truck's live position (refreshed every minute from `/m/<token>.json`). The link
  stops working 2 days after the trip is done or cancelled. Driver fuel-stop messages carry it as
  "Trip map"; the office trip page has a Live map button and its own map polls `/trips/<id>/live.json`.
- **Truck.** Pick one, or let Kaido pick: "closest truck to the pickup that is live on Samsara now"
  (`--truck nearest`) or "any truck live on Samsara" at random (`--truck random`). Live means a
  driver is set and Samsara gave a position and a tank reading in the last hour.
- **Remaining fuel.** The plan starts from the truck's tank % from Samsara and shows it as gallons and
  miles of range. A reading over 2 hours old is flagged; without one, 50% is assumed and the plan says so.
- **Route.** The stop addresses are geocoded (Nominatim, cached; when the full address does not
  resolve, it retries without the house number, then with city/state/ZIP). The road route
  from the truck's live position through every stop comes from the free OSRM demo server
  (`router.project-osrm.org`). It is a car route, so driving time is OSRM's × 1.12, and never
  faster than 65 mph on average.
- **Fuel stops.** Every directory station within 3 miles of the route gets a mile marker. Its
  price is the company's own price when it is under 7 days old, otherwise today's website pump price
  minus the company's usual discount at that brand, otherwise an older own price with an age
  penalty of $0.004/gal per day. A dynamic program then picks where to stop and how many gallons
  to buy, in 10-gallon steps, for the lowest total cost. It starts from the truck's real tank
  level (Samsara) and tank size, uses the truck's MPG, never lets the tank go under the reserve
  (company setting, at least 10%), adds the detour miles off the road, and counts each stop as
  $12 so it does not split fuel into many small stops. Savings are shown against buying the same gallons at the
  average known price on the route.
- **Hours of service.** The driver's live clocks come from Horizon when they are under 12 hours old (drive,
  shift, 70-hour cycle, break). Without them a fresh 11/14 is assumed. The simulation drives the route
  with the 30-minute break after 8 hours of driving, a 10-hour rest when the 11 or 14 runs out, and a
  34-hour restart when the cycle runs out. It counts 30 minutes per fuel stop and 2 hours at each dock,
  and waits for a window that is not open yet. A 10-hour rest is placed at the truck stop with parking
  in the 45 miles before the limit.
- **ETAs** are shown in each stop's local time zone and checked against its window, so the plan says
  "on time" or "LATE by about N h", and flags a restart the trip will need.
- **Expensive states.** Fuel left in the tank at delivery is valued at the cheapest known price
  within 120 miles of the delivery, so a trip into California fills up before the border instead
  of arriving empty. When a stop fills the tank because diesel ahead is at least $0.25/gal dearer,
  the stop says so ("Fill the tank here: diesel ahead in CA averages $7.35, $1.48/gal more").
  Each purchase is at least 50 gallons, or a fill if the tank needs less.
- **To the driver: fuel only, one stop at a time, short.** Dispatch already posts the load (pickup,
  delivery, times) in the truck group, so Kaido does not repeat it. "Send to driver" posts only the
  first fuel stop: name and city, miles ahead, gallons, price and Map, a fill-up note when fuel ahead
  costs more, and tank % with drive and shift hours left, plus a location pin. Buttons: **Fuel there**
  or **Skip this stop**. When the plan needs a 34-hour restart or will be late, that goes to the
  company admins on Telegram, not to the driver. The full plan (pickup and delivery ETAs, every stop,
  rests, timeline, map) is on the trip's page in Kaido.
- **Live follow-up** (`trips.follow`, every 5 minutes from `bin/followup.sh`, for sent and accepted
  trips up to 8 days old, while the truck's position is under an hour old and within 15 miles of the
  route):
  - When the next planned stop is under 80 miles ahead, or the tank is at or under the alert level,
    the driver gets that one stop in a few lines: station name; street address, city and Map; miles
    ahead, about what % the tank will be at on arrival, and truck parking spots; gallons and price;
    "Fill the tank, fuel ahead costs more" when it is a fill-up before a dearer state; and tank %
    with drive and shift hours left. When the clock runs out first it says "Rest first". A location
    pin follows. Buttons: **Fuel there** or **Skip this stop**.
  - A tank jump of 15 points marks the stop done; the next one comes when it is close.
  - **Fueled note.** After the Samsara sync that shows the fill (`fuel_bot.refuel_notices`, every 5
    minutes), the group gets a short note: where (the station within 1 mile of where the truck stood
    still during the fill, not where it was after), tank before and after, about how many gallons and
    dollars, and "Planned stop" (any stop on the plan) or "Not the planned stop. Plan was name, city".
    The planned line is left out when the truck is more than 15 miles off the trip's route. It waits
    until the reading has settled or the truck is moving again, so a half-done fill is not reported.
    It runs for trucks with a group when the fuel assistant is on, or when the truck has an active
    trip. Each fill is logged once in `fuel_refuels`.
  - **Skip**, or driving 8 miles past the stop without fueling, re-plans the rest of the route from
    the truck's position and tank (the skipped stations are left out) and sends the new next stop at
    once. The admins are told about a skip. A tank lower than planned also triggers a re-plan.
  - The trip is marked done when the truck reaches the delivery.

Trips are stored in `trips` with the parsed stops, route, the fuel plan, rests and summary. Re-plan
builds a new trip from the same load text with the truck's current position.

## Signed-out visitors

`/` redirects to `/login` for anyone not signed in. The public front page and its contact
form were taken down on 17 Nov 2026 (they drew spam from "SEO" sellers); the old
`contact_requests` rows are still in the database. `/robots.txt` disallows everything and
every response carries `X-Robots-Tag: noindex, nofollow`. The favicon is a plain navy
rounded square with a white K (`static/favicon.svg`, `static/favicon.png` for `/favicon.ico`).

## Fuel

Everything fuel lives in three modules: `app/fuel.py` (stations, prices, MPG, missed
savings), `app/fuel_bot.py` (the driver-chat cards and buttons) and `app/fuel_report.py`
(the weekly picture reports). No AI is used anywhere in it, so it costs nothing to run.

**Where the data comes from.**
- *Tank level, heading and speed* come from Samsara's `fuelPercents` and `gps` stats on
  every 15-minute sync and are kept on the truck. Each sync also appends a row to
  `truck_positions`, the track used to see which stations a truck actually drove past.
- *Truck stops* come from OpenStreetMap: `manage.py fuel-directory` loads every fuel
  station that is a known truck-stop brand (Pilot, Flying J, Love's, TA, Petro, Maverik,
  Sapp Bros, Road Ranger, Ambest…) or is tagged for trucks, state by state, into
  `fuel_stations`. Amenities (parking, showers, scale, DEF, food, repair) come from the OSM tags,
  and where a brand nearly always has one, from that brand's usual set; the brand-based ones
  are listed under `amenities.typical`.
- *Prices and discounts* come from the company's own fuel card purchases. The EFS Transaction
  Report carries the pump price (`unit price`), the discounted price (`disc ppu`) and the amount
  already net of the discount, so every import becomes a real net price at that station
  (`fuel_prices`, source `transaction`). A daily price or discount list from the fuel program
  can be uploaded on Fuel → Prices (source `price_file`). It needs a station-name column and either a
  net price or pump price + discount.
- *Today's pump prices from brand websites* (`app/brand_prices.py`, `manage.py brand-prices`,
  `bin/brand-prices.sh` twice a day). Love's location pages carry each travel stop's diesel
  price (cash and credit), DEF price, truck parking spaces, showers, CAT scale and repair (about 620
  travel stops). TA, Petro and TA Express pages (about 367, from the ta-petro.com sitemap) carry
  diesel and DEF prices, truck parking, scale, showers and repair; Petro stops are stored under
  the Petro brand. Pilot / Flying J is not fetched: its site answers every request from the
  server with a 403, so Pilot prices come only from EFS purchases or a price list. The
  credit price is kept as the pump price in `station_retail_prices` (one row per station and
  fuel, refreshed in place), and the page's amenities replace the brand guess. A stop already in
  the directory within 0.3 mi with the same brand is updated rather than duplicated. One page every
  1.5 s, travel stops only. Used for 30 hours after fetching.
- *Older prices count for less*: in the fuel cards and the trip planner a price paid N days ago is ranked
  as if $0.004/gal × (N − 1) dearer, so today's website prices win unless an old one is clearly cheaper.
- *Your estimated price at a brand*: pump price − the company's average discount at that brand
  over its last 60 days of EFS fills (all history if fewer than two recent ones). A card marks it
  "est." and shows the discount it assumed. When the company has a real price under 7 days
  old at that station, that price is used instead.
- *Sample price list*: Fuel → Prices → "Download a sample built from your purchases" writes a
  CSV in the usual price-list layout (station, city, state, latitude, longitude, retail,
  discount, your price, date) from the latest price paid at each station, dated today. It is
  there to show and test the upload; uploading it makes those older prices count as today's.
  A row with coordinates is attached to the station already within 0.25 mi when there is one.
- *Matching purchases to stations*: the EFS location name + city + state is geocoded at the
  city level (Nominatim, cached 90 days) and matched to the nearest OSM station of the same
  brand within 20 miles. Unbranded stops are geocoded by name. A station still placed only
  at the city centre is tried again once a day as more of the directory loads.

**Missed savings.** For each diesel fill Kaido looks for stations with a price the company
paid within 3 days either side. When the truck's track for the 10 hours before the fill is
known, it uses only stations within 3 miles of that route. Without a track, it uses stations
within 30 miles. When the cheapest of them was at least 3¢/gal lower, the difference × gallons
is stored on the purchase as `missed_usd`, with the cheaper station and its distance.

**Truck health alerts** (`app/health.py`, every 5 minutes from `bin/followup.sh`, all companies). The
Samsara sync saves battery volts, coolant temperature, oil pressure, DEF level, rpm and engine state on
`trucks.health`. An alert is sent once, on the first reading that crosses the line, to the truck's group and
to everyone in the company with Telegram linked; it clears when the reading comes back and cannot reopen
for 6 hours. Listed under Trucks → Faults → Truck health.
- Battery low: under 12.2 V with the engine off. Not charging: under 12.8 V with the engine running.
- Engine running hot: coolant 104°C (219°F) or more while running.
- Low oil pressure: under 10 psi below 1,000 rpm, under 20 psi above, with oil and rpm read together.
- DEF low: under 15% (under 5% says the truck will slow down).
- Check engine: a warning or stop-lamp code new to that truck in 30 days (stop-lamp codes already go to the office, so only the group gets those here).
- Office only: idling 60 minutes or more, and no ELD signal for 6 to 48 hours.
- Hours (Horizon, BOOKIT only; the Samsara tokens have no HOS scope): under 1 h of driving or of the 14-hour shift, under 30 min to the break, under 3 h of cycle, or driving with a clock at zero. To the group and the office.
- Service: due soon (10% of the interval or 1,000 mi, or 30 days) and overdue, per service. Office only. Needs a service on record for the truck (Settings → Service baselines); none exist yet.
- MPG dropped: once a day, Samsara's fuel-energy report, last 7 days vs the 28 before; 12% or more lower with 800+ mi this week. Office only, at most once a week per truck.
- Tire pressure low: any tire under 85 psi (under 60 psi says stop), from Samsara's `tirePressure` stat, clears at 90 psi. Neither current fleet has tire sensors, so it only fires for trucks that report them.

**Alerts group** (`app/alert_group.py`). Make a Telegram group with Topics on, add the bot as admin with
"Manage topics", and send `/alerts` there (or just promote the bot, if you are a Kaido admin). Every active
company you are admin of with `companies.alerts_group` on is linked (`alert_groups`). If the group's title contains a company's name ("DFK transportation"), only that company is linked; otherwise only companies not already in another group are. BOOKIT and LLAP share one group, DFK has its own. One topic per issue is created (`alert_topics`: check
engine, stop-lamp faults, battery, charging, engine temperature, oil pressure, DEF, tire pressure, idling, ELD
not reporting, hours, service, MPG, speeding, harsh driving and camera, harsh turn and crash videos, fuel checks, fuel reports, PTI,
documents, reminders, daily follow-up, summary), and `manage.py alerts-history --chat <id>` replays every past
alert, follow-up and summary into its topic, oldest first, about 18 a minute. Once a company has a group, its
office alerts go there instead of to each person's Telegram; driver messages are unchanged. A deleted topic is
made again on the next alert. Removing the bot from the group unlinks it.

**Safety** (`app/safety.py`, `manage.py safety` from `bin/sync.sh` every 15 minutes). Pulls Samsara camera
safety events and speeding intervals (30 days backfilled on first run) into `safety_events`. Crash, harsh
braking/turn/acceleration, phone use, no seatbelt, drowsiness and heavy or severe speeding go to the office at once,
one per truck and type in 6 hours. Everything is on Trucks → Safety (per-driver counts and the event list; light
speeding only under the Speeding filter). Harsh turn, crash and rollover events also send their Samsara camera
video (forward camera, else inward) to the group's "Harsh turn and crash videos" topic, once each (`safety_events.video_sent_at`),
within 24 hours of the event; only when the company has an alerts group. Videos over 49 MB are skipped (bot upload limit).

**Alerts** page (`/alerts`, top menu): every health, hours, service, MPG, check engine, safety and fuel-check alert in
one list, filtered by type, status and period (all by default).

**Documents** (`app/documents.py`, Trucks → Documents). Driver, truck, trailer and company papers (CDL, medical
card, MVR, clearinghouse, registration, insurance, annual DOT, IFTA, 2290, permits, UCR, BOC-3, MCS-150 and more)
with number, issue and expiry dates and a PDF or photo in `uploads/documents/<company>/`. Truck, driver and
trailer pages show their own. Alerts are off for every company until an admin presses "Turn on alerts" on the
Documents page (turning them on does not send old steps: each document starts from its current step). They go to the office at 30, 14, 7 and 1 days before and on the day it expires
(the driver's truck group gets 30, 7 and expired for driver papers); changing the date starts the steps again.
The page also lists who is missing a CDL, medical card, registration, insurance or annual inspection. The old
licence/medical/registration/insurance date fields were moved here (they were all empty).

**Trailers** (Trucks → Trailers): number, type, VIN, plate, year, make, length, status, the truck it is with, and
documents. Samsara has no trailers on either account, so they are entered by hand.

**Status board** (Trucks → Status board, `app/board.py`): every truck sorted into En route (5 mph or more), Stopped
(with how long since it last moved), Home (within 2 mi of the home yard set on the Company page), In shop (truck
status, or a work order in shop or in progress), Broken down (open breakdown work order), Accident (Samsara crash in 72 h or
a breakdown that says accident/crash/collision), No signal (6 h) and Inactive. Hooked trailers are shown.

**Shop finder extras**: a row of place types (truck repair, towing, tires, mobile mechanic, reefer repair, trailer
repair, truck parking, truck wash), each with its own Google queries or OpenStreetMap filter. Each shop has
"Text the job" (opens the phone's SMS with unit, VIN, location link, driver and the work order description) and
"Copy the job". Work orders have a shop rating (1-5) and comment; the shop list shows visits, average cost,
rating, days in the shop and the last comment for shops used before (all work, not only oil).

**Fuel stop suggestions** (`fuel_bot.run`, every 5 minutes from `bin/followup.sh`, for every
active truck with a position and a tank reading under 90 minutes old):
- **Fuel → Driver suggestions** works for every truck, Telegram or not. All trucks lists the
  fleet lowest tank first; picking one shows a live suggestion with a map (truck, the active
  trip's route when there is one, numbered stations, the best one larger and green) and the
  ranked list. A truck with a connected Telegram group gets **Send to driver**; without one the
  suggestion stays on the page. Low-tank suggestions for trucks that are not sent to Telegram
  are saved with status `ready` and show in History, with a **Send** button once the group is
  connected. Only delivered suggestions count as "sent" in reports.
- **EFS only.** Stations are limited to the EFS network list uploaded on Fuel → Prices
  (`efs_network`, `app/efs_network.py`) plus any station the company has paid at with EFS.
  Before a list is uploaded, only the paid-at stations are used. The upload needs a location
  name and either city and state or latitude and longitude; address and zip help. Rows are
  matched to known stations by coordinates (0.35 mi), then brand or name in the same city
  (store numbers must agree); the rest are looked up in the background
  (`manage.py efs-network-match`, Nominatim, about 1 a second). A new upload replaces the list.
- The Telegram card is sent automatically only when the fuel assistant is on (Fuel → Settings)
  and the truck has a group.
- The search radius is the truck's range, never less than 25 mi (a tank under the reserve
  used to search the full 150 mi). The same store listed under two names (brand + store
  number) shows once.
- A card is sent when the tank is at or below the alert level (company default 35%, or the
  driver's own). It is not repeated for 4 hours, or for 90 minutes once the tank is under 15%.
- Stations are picked around wherever the truck is now (ahead of its heading when moving).
  If the truck has an active trip and is on that trip's route, this card is not sent; the
  trip follower sends the next planned stop on the load's route instead. Off the route, the
  location card is sent as usual.
- Range = (tank % − reserve %) × tank gallons × the truck's MPG. MPG comes from its own fills
  and odometer over 60 days, or the company default.
- Candidates are stations within range (capped at the company's search miles) and, when the
  truck is moving, within 70° of its heading. Stations the driver avoids, or that lack
  something the driver needs, are dropped. Stations are then ranked by net price, with a
  small penalty per mile, a bonus for the driver's favourite and usual brands, and a penalty
  for unknown amenities the driver needs.
- Prices count for 90 days; the card always says how old each one is ("paid 12d ago").
- The card is short: "Fuel · Unit N · Tank X%", then up to three stops of two lines each (name,
  city, miles; price, savings against the nearest priced stop on a full fill, Map), with "More stops"
  for three more. Price age, pump price and amenities are on the web pages, not in the chat.
- Buttons: **Take** a stop, which edits the card and sends the stop as a location pin to
  navigate to. **Skip** asks why: already fueling, off my route, no parking, don't like this
  brand, found cheaper, or remind me later (asks again in 90 minutes).
- When the tank jumps 15 points or more, the suggestion is marked fueled and Kaido checks
  whether it happened within 2 miles of the chosen stop. When the EFS purchase arrives it is
  linked to the suggestion from the 18 hours before, with `followed` and `saved_usd` against
  the nearest priced option.

**Driver preferences** (`driver_fuel_prefs`, per driver): alert %, must-haves, favourite and
never-suggest brands. Drivers set them with `/fuelprefs` in the truck group. Kaido also
learns: skipping a brand twice for "don't like this brand" adds it to never-suggest, and
brands with 30%+ of a driver's fills in 90 days count as favourites.

**Truck group commands:** `/fuel` (best stops from here, now), `/fuelprefs`, `/fuelweek`
(last week's report now).

**Fuel → Fuel assistant** has the settings, a **Connected trucks** table (group name, driver, tank %
and how old it is, where, the fuel stop last sent and whether the driver fueled: the fueled note's
% before and after, gallons, station, planned or not), and the drivers' preferences. Fuel → Prices
lists the company's own prices and today's Love's / TA / Petro website prices (with the estimated
price after the usual discount at that brand), about 1,100 stations.

**Demo purchases** (`app/fuel_demo.py`, `manage.py fuel-demo --company NAME [--days 28]`, undo with
`--remove`). Placeholder fuel purchases, `source = 'demo'`, for showing the fuel pages when no recent
EFS report is available. For each active truck with a driver, the tank is drawn down by its real
Samsara miles at 6.5 mpg; days with no readings use the truck's average day. When the tank would be
under 35% it fills at a Love's, TA or Petro within 250 miles of the truck with today's website price,
a few cents of drift, and the company's usual discount at that brand. About 1 in 5 fills is at a
pricier stop and 1 in 20 has no discount, so missed savings show up, and about 1 in 6 also buys DEF.
Demo rows are badged "demo" on Purchases, counted on Insights, and skipped by the fuel checks.

**Weekly reports** (`fuel_report.run`, on the company's report weekday and hour, default
Monday 08:00 local, once per week per target, logged in `fuel_reports`). The report covers
the previous Monday–Sunday:
- *Driver card* to each truck group: a PNG with diesel spend, gallons, price per gallon against
  the fleet, mpg, discounts captured, missed savings, a 6-week price trend against the fleet
  average, suggestions taken, and one tip from the week's data.
- *Fleet card* to each company admin's Telegram: spend with week-on-week change, gallons,
  average price against pump, discounts, missed savings, mpg, suggestions taken, 8-week spend,
  drivers ranked by missed savings, and the three biggest missed opportunities.

`manage.py fuel-report --company NAME --dry-run --force` writes the fleet card to `logs/`
without sending anything.


**Regional averages (EIA).** `manage.py eia-prices` (`app/eia.py`) reads the US Energy Information Administration's free weekly
diesel table (`PET_PRI_GND_A_EPD2D_PTE_DPGAL_W.xls`, no key needed) into `regional_diesel_prices`: New England, Central Atlantic,
Lower Atlantic, Midwest, Gulf Coast, Rocky Mountain, West Coast and California, plus the US average. Each station's state maps to
its region. Trip planning uses it only for a stop with no company or website price, plus a $0.10 penalty so stops with a real price
win; the trip page shows it as "region avg" and the driver message says "(region avg)". It is a weekly average, not a pump price.
It runs after the brand prices in `bin/brand-prices.sh`, from cron every day at 7:00 US Eastern.
Fuel → Insights opens with **Diesel market**: the EIA U.S. average with its change vs last week, 4 weeks and a year
(`eia.changes()`, 60 weeks kept), a 12-week chart (U.S., California, Gulf Coast), the region table, and **Pump price by
state**: the Love's/TA prices averaged per state each morning into `state_diesel_daily` (`eia.snapshot_states()`), with
the change vs yesterday and last week, the cheapest stop, and the difference from the EIA region average. The state
history starts 20 Nov 2026, so day and week changes appear as the days build up.

## Notification center

A bell sits left of your name in the top bar. When a note arrives the panel opens;
the last 20 read notes stay under *Earlier*. Every page asks `/cat/pending` every 15
seconds. A reminder set on any record shows up here when it is due, as well as on
Telegram: for whoever set it, or for every admin of the company when it was set for
admins. Its *Open* button switches to the reminder's company and opens the record.

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

## Work orders

**Time at shop** replaces downtime on work orders. It starts when the status becomes *in shop*
(or *in progress* if *in shop* was skipped). Waiting time runs from *in shop* to *in progress*;
repair time from *in progress* to *done*. The list's At shop column shows the total and the
wait (amber while still waiting); the work order shows total, waiting and repair; the PDF lists
all three. Times come from the status changes in the activity thread, so orders moved straight
to done have none. Truck-level downtime (dashboard, unit page) is unchanged.

**PDF** puts the attached invoice files first (PDF pages, and photos as pages, in upload
order), then the work order. A file that cannot be read is skipped and logged.

Each row on the Maintenance list has an **×** that deletes the work order (asks first, admins
only) and returns to the same filtered list.

Maintenance → one list (`maintenance_orders`, `app/views/maintenance.py`). Cases (breakdowns) were merged into it
on 25 Nov 2026: each old case became a work order with `breakdown = true` and `from_breakdown_id` set (case 12 joined
the work order already made from it, #30; case 13 became #34), and the case updates became comments. The old
`breakdowns` and `breakdown_updates` tables are kept untouched as an archive; `/breakdowns/...` links redirect to the
matching work order. Statuses: open, scheduled, towing, in shop, in progress, done, cancelled. Priority: low, medium,
high, urgent. "Report a breakdown" on a truck page opens a work order flagged as a breakdown.

Opening one asks only for the basics: truck or trailer, the unit, what's wrong, priority, when it was reported and
whether it is broken down, with shop and scheduled date folded away. A trailer order can have no truck and no driver
(a dropped trailer) and records where it is sitting (`location`). The status is open, or scheduled when a shop or
date is given. On the work order page: a status bar (one click per status), a comments thread (author, time, a photo
or PDF per comment, stored in `uploads/maintenance/comments/`), then the details, with parts, labor, tax, invoice,
payment and shop rating folded into "Costs and invoice" (open once the order is done or has any cost). Choosing an invoice PDF or
photo there sends it (up to 3 files) to `POST /maintenance/invoice/read` (`advisor.read_invoice`, the `AI_MODEL`
under `AI_DAILY_USD`, about $0.014 a read) and fills parts, labor, tax and fees, invoice number, paid with and next
due when the invoice shows them; fields already filled are left alone, and nothing is saved until Save. Every status
change writes "<name> changed status from X to Y" into the thread. Cancelled orders are hidden from the list unless
the Status filter is Cancelled; Delete asks first and removes the order with its comments, files and reminders.
The list shows the comment count per order and filters by status, truck/trailer and system.

Work order page layout: title is the work type and number, a facts strip (driver, shop, reported, downtime,
total, invoice), the details form on the left, and a Status steps list plus the Activity thread (comments and
status changes) on the right; on phones the right column moves to the top. No reminders panel. 

Claude: a round button next to the bell on every page opens a chat drawer (Escape closes it). Each question
sends a fresh snapshot of the whole company from `app/company_context.py` (every truck with status, driver,
place, moving/idling/parked, fuel, odometer, faults, service due and weather; open work orders; month's
work-order and fuel spend; active faults; open health alerts; 7-day safety counts; hours of service; active
trips; expiring documents; open recalls). On a unit or work order page the page marks the truck with
`data-page-truck`, and that truck's full detail is added. One thread per user per company (`ai_chats.truck_id`
null), routes `/assistant` and `/assistant/clear`; the per-truck routes are kept but no page uses them. Same
model and the same `AI_DAILY_USD` cap as before, roughly half a cent a question with 40 trucks.
History and attachments: each chat is a row in `ai_conversations` (titled from the first question); History in the
drawer lists them, New chat starts one, Delete removes it with its files. Up to 5 photos (JPG, PNG, WEBP) or PDFs
of 10 MB each go with a question, stored in `uploads/assistant/<company>/` (`ai_chat_files`) and served at
`/assistant/files/<id>` to the user who sent them. The 4 most recent attachments are sent again with every
follow-up so Claude can still see them; images are shrunk to 1568 px first. Chats from before 25 Nov were
imported as "Unit N" conversations. The Fuel menu opens on Insights.

Logo: `app/templates/_logo.html`, inline SVG made from her file (`app/static/kaido-logo-original.svg`, which has a dark background), so KAI follows the theme ink and DO is navy in light and light blue in dark; used in the top bar, sign-in and driver PTI pages. The favicon is the K square from the same file.

Look: Inter (variable, self-hosted in `app/static/fonts`, SIL Open Font License) for all text, sentence-case
badges and table headers, rounded inputs and buttons. The overrides sit at the end of `app/static/modern.css`.

## Search

The search box in the top bar (`app/search.py`, `static/search.js`) looks through units (number, label, VIN in full or
any part such as the last 6, plate, group), drivers (name, phone, Telegram), trailers, work orders (number,
description, shop, invoice number), saved shops and recalls (3 letters or more), ignoring capitals and matching any
part ("jacq" finds Jean Jacques, "0239" finds the unit). Results show grouped as you type; arrows move, Enter or a
click opens the page (units and drivers open the combined unit/driver page). `/` or Ctrl+K (Cmd+K) jumps into the box.
Pressing Enter with no list open goes to `/search`, which opens the page directly when there is one match.

## Recalls

`manage.py recalls` (cron, Mondays 05:30 server time; `app/recalls.py`) checks every truck and trailer with a VIN.
Missing make, model or year is filled from NHTSA's vPIC VIN decoder, then NHTSA's free recalls API
(`api.nhtsa.gov/recalls/recallsByVehicle`, no key) is asked by make, model and year. Volvo trucks are looked up as
"VOLVO" when "VOLVO TRUCK" finds nothing. **The public API has no exact-VIN lookup**, so every recall is shown as "may
apply, confirm with dealer", with a link to NHTSA's own VIN check (`nhtsa.gov/recalls?vin=...`). The nhtsa.gov docs
page refuses automated readers, so the endpoint and its fields were confirmed by calling the API itself on 25 Nov 2026.

Campaigns are kept in `recall_campaigns`, and each unit's recalls in `vehicle_recalls` (open, done with date and shop,
or not applicable; one click makes a warranty work order linked to it). Shown on the unit page (Recalls section), as
a count on the dashboard, and as a "With open recalls" filter and badge on Trucks. The first run on 25 Nov linked 1,244
possible recalls to 72 trucks (about 17 per truck, since many apply only to some build dates) and sent nothing. Later
runs send "New safety recall" to the office (alerts group or admins' DMs) only for campaigns not seen before.

## Comebacks and downtime

**Comebacks** (`app/comebacks.py`): when a work order is opened, saved or marked done, Kaido looks for a done work
order on the same truck or trailer within the comeback window (`companies.comeback_days`, default 60) that matches by
the same work type, the same system, or a similar description (shared phrases such as "air leak", "brake", "tire";
tire and wheel jobs on clearly different positions do not match). Preventive maintenance, inspections and towing never
count on type or system. Each match is a row in `maintenance_comebacks` with the reason. It shows as "possible
comeback" on the work order (link to the earlier one and its shop, "Not a comeback" to clear it, Undo to bring it
back), as "comeback?" in the list, on the unit page, and as a count in the shop finder's history line. Maintenance →
Flags → Possible comebacks lists them with a table of comebacks per shop and the window setting (saving rechecks all
work orders).

**Downtime** (`app/downtime.py`): a work order is down from the moment it goes to towing or in shop, or from when a
breakdown is reported, until it is marked done or cancelled, or until the truck moves again at 5 mph or more (30
minutes of grace for a road test), whichever comes first (`down_started_at`, `down_ended_at`, `down_end_reason`).
Shown in days on the work order and in the list, as totals per truck for this month and the last 90 days on the unit
page, and as "Most downtime, 90 days" on the dashboard. Trailers end only on done or cancelled since they have no
GPS. Existing orders were filled from their status history; position history only goes back to 17 Nov 2026.

## Unit and driver page

`/trucks/<id>` is one page for the truck and whoever drives it (`app/unit_page.py`, `trucks/unit.html`). `/drivers/<id>`
opens the same page when the driver has a truck; a driver with no truck gets only the driver section, "No truck
assigned" and their last truck. Driver edit moved to `/drivers/<id>/edit`. Trailers have their own page
(`/trailers/<id>`, edit at `/trailers/<id>/edit`) with work orders and the dropped location from the latest work
order that recorded one.

- Truck: VIN, plate, year/make/model, group, odometer, fuel, hooked trailer, a small map with the address, moving or
  parked (and for how long, from `truck_positions`), speed and the last update. Open issues, work order history,
  active fault codes and recent alerts (non-hours), latest 10 each.
- Driver: phone, Telegram, CDL and medical card from Documents ("missing" when not on file), hours panel, hours
  alerts, safety events (light speeding left out), PTI done or missing for each of the last 10 days (missing = one of
  their trucks moved that day with no PTI), diesel purchases and whether they took the fuel suggestion, trucks driven.
- Every section has "See all", which opens the list filtered by `truck_id`, `trailer_id` or `driver_id`.
- `driver_assignments` keeps who drove which truck and when. A trigger on `trucks.driver_id` opens and closes the rows,
  so history stays right when drivers switch trucks. The past was filled in from safety events, fuel purchases and
  PTIs. Hours alerts now carry `driver_id`; the 143 older ones got the truck's current driver.
- Idle time (driver section): hours idling today, this week and this month, gallons and dollars burned, and the 5
  longest idle sessions in 31 days with where they happened. Built from the engine state (`On`/`Off`/`Idle` with the
  time it changed) that the existing Samsara stats sync already reads every 15 minutes; each change becomes a row in
  `engine_sessions` tagged with the truck's driver at that moment, so idle time follows the driver. No new Samsara
  endpoint is used, so there is no history before 25 Nov 2026, and a state that starts and ends between two syncs is
  missed. Gallons use `IDLE_GALLONS_PER_HOUR` (0.8, a typical heavy-truck idle burn) and dollars use the company's
  average diesel price over 90 days. Fuel → Insights has an Idle hours column per driver.

## Alerts, hours and safety

- **Alerts** (`/alerts`) open on **Open** (open or acknowledged), at her request. Repeats of the same alert on the same
  truck on the same day (company time zone) are one row with a count. Every row has a status (open, acknowledged,
  cleared) and Acknowledge / Clear buttons that act on all alerts in the row; "Clear all shown" clears the page.
  Statuses live in `health_alerts.acknowledged_at/cleared_at`, `safety_events.status`, and `fuel_alerts.status` plus
  `acknowledged_at`. On 25 Nov 2026 safety events older than 7 days were set to cleared so the open list starts clean.
- **Hours** (Trucks → Hours, `/hours`): the hours alerts (14-hour shift almost out, driving hours almost out, break,
  cycle, violations) in the same grouped list. **Faults** shows engine fault codes only.
- **Speeding threshold** (Safety page, admins): a speeding event counts only when it is at least N mph over the limit
  for at least S seconds (`companies.speeding_min_over`, default 10, and `speeding_min_seconds`, default 30). It
  applies to the Safety totals and list, the Alerts list and the driver section of the unit page (`safety.counted_sql`).
  The Telegram alerts for heavy and severe speeding are unchanged.

## Groups and names

Trucks have a **carrier/group** (`carrier_group`: Octane, Mercury, TVC, TCS...) and an optional **label**
(`unit_label`), both on the truck form. On 25 Nov 2026 the group was filled from the bracketed part of each unit
name and the unit was cut to its number ("0803 Clarke (Octane)" became 0803, group Octane). Four units kept their old
name because the bare number is already taken by a duplicate: 107, 111, 5831 and 777. New trucks imported from
Samsara get the same split. Samsara and fuel matching are unaffected: Samsara links by vehicle id, and the EFS import
already matched on the number the unit starts with. Trucks, Alerts, Fuel and Safety have a Group filter. Fuel also
has a Demo purchases filter (show, hide, only demo).

Driver names are tidied by a database trigger (`drivers_tidy_name`): names in all capitals or all lower case become
Title Case and extra spaces go, whatever writes them (Horizon, Samsara names, the form). A name changed by hand on
the driver form is locked (`drivers.name_locked`) so the Horizon sync no longer overwrites it. A Horizon login marked
`driver_links.ignored` is skipped by the sync.

## Service schedule

Oil is per truck (`oil_interval_miles`), 25,000 miles by default and 15,000 for
severe duty. The DOT annual inspection is tracked from the last recorded
inspection date and warns 30 days out; completing an `annual_inspection` work
order resets it.

The rest start company-wide, with intervals set on Trucks → Service intervals (`service_intervals`):

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

The list itself is editable by admins, at two levels:

- **Company** — Maintenance → Preventive maintenance list (`/maintenance/pm-list`). Add a
  service by name with "every … miles" and/or "… months", or remove one. Anything with an
  interval is counted under every truck. Added names also appear under Preventive
  maintenance in the work-order picker, so the work can be logged and counted from.
  Removed ones can be put back; work orders already logged keep their name. Oil stays.
- **One truck** — the truck's page → Service schedule → Edit list (`/trucks/<id>/services`).
  Add a service to that truck only, remove one from that truck only, or give it its own
  interval. Everything else keeps following the company list.

Company edits live in `pm_list` and `service_intervals`, per-truck ones in
`truck_services`; `app/pm_list.py` works out each truck's list. A service the company
added is stored on work orders as `pm:<name>`.

Overdue and due-soon items show on the dashboard, the truck list, the truck's own
Service schedule, the daily follow-up and the fleet status report.

## Not built yet

The EFS automatic feed (the report import works today), DVIR scope on the Samsara
token, and Love's.

## Learn

`/learn` (any signed-in user, Learn in the menu): 49 topics in three groups. The file prefix sets the group: `s` study plan, none = Topics (28 pages, each one subject, merging what was written for Kaido with her Claude Docs manual "Fleet From Scratch"; the manual's part of a page starts at "More detail" or headings marked "(in depth)"), and `p` Parts A to Z (20 pages from the same manual). The Topics are for someone new to fleet maintenance, from what a
truck is made of to breakdown calls, DOT, invoices and a glossary. Each topic is a Markdown-like file in
`app/learn/NN-name.md` (first line title, second line summary), rendered by `app/learn.py`: `## ` headings,
`|` tables, `- ` and `1. ` lists, `**bold**`, images as `![caption](file)` from `app/static/learn/`, and
`@video Title | search words` lines, which become YouTube search links, and `[text](https://...)` links. Photos come from Wikimedia
Commons under their free licenses; author and license are in `app/learn/credits.json` and show under each
photo. The diagrams (`*.svg`) were drawn for Kaido. Search on `/learn?q=` matches every word across topics.
The manual PDF is served from `uploads/learn/Fleet_From_Scratch.pdf` at `/learn/fleet-from-scratch.pdf` (sign-in required; the file is not in git). Edit a file and restart `kaido.service` to see the change (topics are cached in memory).
