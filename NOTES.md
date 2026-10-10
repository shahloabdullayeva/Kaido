# Where Kaido stands — 30 Sep 2026

## Live

- **https://kaido.shahlo.blog** — the address, Let's Encrypt cert, renews itself

The second hostname, `kaido.89.39.94.118.sslip.io`, was **removed on 12 Sep** at
her request; its Caddy block is gone and the name no longer answers. It had been
the way in while her ISP's DNS cache still held a negative answer for
kaido.shahlo.blog. If that ever happens again, the block can be pasted back from
`/etc/caddy/Caddyfile.bak.20260912-053830` and reloaded — sslip.io resolves any
name with an IP in it, so it needs no DNS of its own.

When kaidofleet.com is bought: `./bin/golive.sh kaidofleet.com` (add A records for
`@` and `www` to 89.39.94.118 first).

## Running by itself

| What | How |
|---|---|
| App | `kaido.service` — gunicorn, 3 workers, 127.0.0.1:8790, behind Caddy |
| Telegram linking | `kaido-bot.service` — listens for `/link CODE` |
| Samsara sync | cron, every 15 minutes, `bin/sync.sh` → `sync.log` |

All enabled at boot. `systemctl status kaido` / `journalctl -u kaido -f` to look.

## Accounts

- **Charlotte** — platform owner, sees every company. Telegram linked.
- **John** — admin at LLAP Logistics. Telegram linked, so he gets the follow-up,
  reminders sent to admins, and stop-lamp alerts.

Sign-in: password and a picture captcha, then a 6-digit Telegram code every time.
Trusted devices were removed on 10 Oct 2026.
Both temporary passwords have travelled through chat — change them.

## Data in there now

LLAP Logistics LLC, synced from Samsara org 7009346: **35 trucks**, all VG55NA
gateways, average 760k miles. **30 drivers**, parsed out of the Samsara vehicle
names, 26 assigned to their truck. Fault codes flowing — 75 open on the first
sync, and the 15-minute job opens and closes them on its own.

The two demo companies (House Fleet, Bright Line Carriers) and their test user were
deleted on 30 Sep. **Add company** (top bar, or the Company page) is open to Charlotte
and John only (`users.can_add_companies`); both become admins of every new company.

## Built on 12 Sep — where to send a truck

The work-order form now finds shops near the truck — or near any address you
type or point you click on the map, which is what the 9 demo-company trucks need
since only the 35 LLAP trucks have a Samsara feed. Positions come from Samsara on
every sync (35 of 35 trucks are reporting one), shops from OpenStreetMap, and the
map is Leaflet served from `static/vendor` — nothing from Google, nothing to pay
for. Distance, diesel cost of the round trip, opening hours and what this company
has paid at that shop before are all on the list. README → *Where to send it* has
the detail.

**Google Maps was not used at first** (see 30 Sep evening below — it is now optional).
Places would have been about $32 per 1,000 lookups plus a billing account; OpenStreetMap
is free and answers the same question. What
OSM is worse at is opening hours — most big truck stops carry no hours tag at all,
and those read "hours not listed" rather than a guess.

**The AI line for each shop is on** — her own key went into `.env` on 12 Sep with
$5 of credit on it, and the app is built to make that last:

- A lookup costs about **$0.0025** (Haiku 4.5, ~1,200 tokens in, ~280 out), so $5
  is roughly **2,000 lookups**.
- `AI_DAILY_USD=0.20` is a hard daily cap. Spend is priced and recorded in
  `ai_usage` on every call; at the cap the notes stop for the day and the shop
  list carries on without them. **Worst case the $5 lasts 25 days**, and only if
  she runs ~80 lookups every single day.
- Answers are cached seven days, so reopening the same truck in the same place is
  free.
- `./venv/bin/python manage.py ai-spend` prints the whole picture: per day, all
  time, cost each, and how many lookups the remaining credit buys.

## Also on 12 Sep — the dashboard map

The dashboard now opens on a map of the whole fleet: 35 LLAP trucks, each dot
coloured by whether anything is wrong with it, hover for unit and driver, click
for the driver, position, age of the reading, faults and a link to the truck.
Companies with no telematics (the two demo ones) get a line explaining that
rather than an empty map.

## Built on 30 Sep

- **Follow-up.** One Telegram message per company per day (default 07:00 company time, set on
  the Company page): open breakdowns, overdue service, work that was due, reminders due, new
  fault codes, service due soon, papers expiring.
  Stop-lamp faults go out the moment the sync sees them. `bin/followup.sh` runs every 5 minutes.
- **Reminders on everything.** Every truck, driver, work order, breakdown and fault page has a
  Reminders box: pick a date and time, it arrives on Telegram (just you, or every admin).
- **Any truck, any driver.** The work order form takes outside trucks and outside drivers,
  saved with their carrier so they can be picked next time. They stay out of the fleet map and
  totals and have their own filter on the Trucks page. The driver can be changed on any order.
- **Reports.** Maintenance, fuel, breakdowns, faults and fleet status, filtered by dates, truck,
  driver and own/outside, downloadable as PDF, Excel or CSV. Each work order and breakdown has
  its own PDF.
- **Service baselines.** Trucks → Service baselines: pick a service (oil, PM-A/B/C, air dryer,
  transmission, differential, coolant, DPF), type the last miles or date, or upload a sheet.
- **EFS import.** Fuel → Import from EFS takes the eManager Transaction Report (CSV or Excel).
  Matches by unit, then card last 4; re-importing the same file is safe.
- **Claude.** Plain-English explanation on every fault page, stored per code so it is paid for
  once. An oil suggestion on oil work orders from the engine read off the VIN (NHTSA decoder,
  42 trucks decoded). A chat box on every truck and work order that sees the truck's record.
  All of it shares the $0.20 daily cap.
- **Company lock.** Postgres row-level security on every company table: inside a company's
  pages the database refuses other companies' rows even if a query forgets its filter.
- **Nightly backup** at 03:30 into /root/backups/fleet, 14 days kept. `pg_dump` needs
  `--enable-row-security` now that the company lock is on, or it refuses to run.
- **OpenStreetMap rules.** Tiles get the site as Referer (the page used to block it with a
  `<meta name="referrer">` tag, which is why OSM showed its usage-policy notice), the
  attribution links to osm.org/copyright, and Nominatim and Overpass calls are spaced at
  least 1.1 s and 2 s apart across all workers (`osm_calls` table).

- **81 work types in 13 systems.** Preventive, inspections & compliance, engine,
  aftertreatment (DPF, DEF, SCR/NOx, regen), transmission & drivetrain, brakes & air, tires &
  wheels, steering & suspension, electrical, cab & body, trailer, road service, other. Grouped
  roughly along the ATA/TMC VMRS system codes. The list lives in `app/work_types.py` only — the
  database no longer checks it, so adding a type is one line there. The Maintenance page
  filters by system and the maintenance report has a System column.

- **Due tracking for 8 more services.** PM-A 15k, PM-B 45k, PM-C 150k, air dryer 60k or 12 mo,
  transmission fluid 60k, differential 60k, coolant 150k or 36 mo, DPF cleaning 300k. Defaults
  are the midpoints of published Class 8 schedules; each company can change them on Trucks →
  Service intervals (`service_intervals` table). Severe-duty trucks are due 25% sooner on miles.
  A PM-B also counts as a PM-A, a PM-C as both, and a "next due" typed on a work order wins.
  Nothing is counted for a truck until one of that service is on record — the truck page's
  Service schedule links to the baseline page for each one. Overdue and due-soon items go into
  the dashboard, the truck list, the daily follow-up and the fleet report.

- **Shop finder, step by step.** The list comes back first (OpenStreetMap only), then Claude's
  pick and notes (`/maintenance/shops/<id>/advice`) and any missing street addresses
  (`/maintenance/shops/address`, Nominatim reverse lookup, cached 90 days in `geocodes`) fill in
  while a percentage bar runs. Every shop has a Google Maps link, a Call button (`tel:`) when
  OpenStreetMap lists a phone, and "Show on map", which zooms to it and enlarges its pin.
  Most OSM shops have no phone listed; Google Maps is the fallback for that.

## Fixed and built on 30 Sep, evening

- **Shop finder used the Samsara position even after an address was typed.** The typed
  place was never stored, so reopening a work order (or it reloading for an oil change)
  went back to Samsara, and "Try again" after an error did too. The place is now saved on
  the work order (`shop_where`, `shop_lat`, `shop_lon`), the first screen has the address
  box next to the button, and there is an explicit "Back to where Samsara has …".
- **Google Maps** for the shop finder is built but **off by choice**: Google wanted a $30
  prepayment to open billing, and Kaido is to stay free. Leave `GOOGLE_MAPS_API_KEY` empty;
  OpenStreetMap does the search. If ever wanted: README → Google Maps.
- **Saved shops** — Maintenance → Saved shops. John's Google Maps links go in there; they
  are listed first in every search within 100 miles.
- **Error log** at `logs/errors.log`, secrets stripped, rotated weekly.
- **Telegram bot token was being written to the journal** whenever Telegram could not be
  reached (the request URL carries it), and the bot crashed and restarted each time. It now
  redacts, waits and retries. The token is in old journal lines from 30 Sep — rotate it
  with @BotFather if that matters.
- **Postgres restarts caused "AdminShutdown" errors** on the next sign-in (30 Sep 06:57).
  The pool now checks each connection before use.
- Leftover `db/migrate.js` (from a Node version, pointing at a `src/` that does not exist)
  removed. openpyxl's "no default style" warning silenced.

## Next, in the order worth doing

1. **Service baselines.** 35 trucks still have no oil change on record, and none have the other
   eight services yet. Trucks → Service baselines takes them one service at a time; it needs
   the numbers. Check the default intervals against the trucks' OEM manuals too.
2. **EFS automatic feed.** The upload works today. For hands-off, ask EFS for a data feed
   username and password for your own software, then Kaido can pull on a schedule.
3. **kaidofleet.com** when it is bought — `bin/golive.sh kaidofleet.com`.

## Known gaps

- **DVIR is scope-gated.** Every defect endpoint answers 405 with the current token.
  Add the *Read DVIRs* scope in Samsara if drivers file inspections there.
- **The Samsara org has no tags,** so per-carrier token scoping is not possible yet.
  BMG and LLAP name prefixes look like two carriers sharing one org — worth deciding
  whether they should be two companies here.
- **The Samsara token in use should be rotated** — it went through a chat.
- **Shop hours are only as good as OpenStreetMap.** A shop with no `opening_hours`
  tag shows "hours not listed" — phone ahead. Nothing in the app invents them.
- **Overpass is a free service with no SLA.** Answers are cached for seven days per
  0.01° map cell, and a stale answer is served when it is busy; if it is down and
  nothing is cached, the panel says so.

## PTI (1 Oct 2026)
- Drivers do pre/post-trip on their phone from a per-truck link (`/pti/<token>`, no login), printed as QR stickers from PTI → Print QR stickers. Replacing a truck's link kills the old sticker.
- Checklist covers the 11 FMCSA 396.11 items plus common walkaround items. A defect needs a note; photos are optional and shrunk to 1600px.
- Defects send a Telegram alert. An admin signs off (repaired / not needed), and the next driver must confirm they read it. The daily follow-up lists defects not signed off.
- The PTI page shows trucks that moved 10+ mi today with no pre-trip.
- Samsara DVIRs now use the real endpoints `/dvirs/stream` and `/defects/stream` (the old `/fleet/defects/stream` guess was wrong). Neither org had a single DVIR in 90 days, so drivers are not doing them in the Samsara app.
- Importing trucks from Samsara now runs a sync right away (BOOKIT showed 0 miles until the next cron).
- Backups: Mon+Thu 03:30 server time (database + uploads/ photos), 4 weeks kept in /root/backups/fleet on the same server, then a Telegram summary to each company's admins (PTIs, AI checks, review, AI spend). AI cap stays $0.20/day (her decision, 1 Oct).
- Truck Telegram groups: one group per truck (driver + office). Add @kaidofleet_bot and send `/truck <code>` (code on the truck page); the driver sends `/unit` once to be tagged. A group only ever gets its own truck's reminders. Pre-trip/post-trip on the company's picked days (default Mon+Thu, 06:00/20:00, US company timezone), plus a one-off nudge any day the truck drives 10+ mi with no pre-trip. Never post a fleet-wide list to a group: that went to Unit 003's group once on 1 Oct.
