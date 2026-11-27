# Where Kaido stands — 30 Sep 2026

## Live

- **https://kaidofleet.com** — the address since 13 Oct 2026, Let's Encrypt cert, renews itself
- `www.kaidofleet.com` and the old `kaido.shahlo.blog` both redirect to it, path kept, so links
  already sent over Telegram (PTI, reports, sign-in alerts) still open. That redirect block was
  added to `/etc/caddy/Caddyfile` by hand; `bin/golive.sh` only writes the block for the domain itself.
- Sessions belong to the host, so everyone signs in once more on the new address.

## Running by itself

| What | How |
|---|---|
| App | `kaido.service` — gunicorn, 3 workers, 127.0.0.1:8790, behind Caddy |
| Telegram linking | `kaido-bot.service` — listens for `/link CODE` |
| Samsara sync | cron, every 15 minutes, `bin/sync.sh` → `logs/sync.log` |

All enabled at boot. `systemctl status kaido` / `journalctl -u kaido -f` to look.

## Accounts

- **Charlotte** — platform owner, sees every company. Telegram linked.
- **John** — admin at LLAP Logistics. Telegram linked, so he gets the follow-up,
  reminders sent to admins, and stop-lamp alerts.

Sign-in: password and a picture captcha, then a 6-digit Telegram code every time.
Trusted devices were removed on 10 Oct 2026.
The captcha is the built-in picture until `HCAPTCHA_SITE_KEY` and `HCAPTCHA_SECRET`
are in `.env`; then it is hCaptcha (click the pictures). Keys not added yet.
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
- **Fuel list order.** Click the Date column on Fuel to switch between newest first (the default)
  and oldest first (`?dir=asc`); the truck filter keeps the order.
- **EFS import.** Fuel → Import from EFS takes the eManager Transaction Report (CSV or Excel).
  Matches by unit, then by the number a unit starts with (a truck saved as "0638 Name (Carrier)"
  matches a file row for unit 638, when only one truck starts with that number), then card last 4;
  re-importing the same file is safe. The page names the company the file will go into: a file
  uploaded under the wrong company adds nothing and reports every row as "No truck found".
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

## Billing, account menu, saved-shop notes (10 Oct 2026)
- Price is $4 per truck per month with a $40 monthly minimum (Charlotte's decision; customers are Uzbek-run carriers). Both in `.env`-overridable config: `BILLING_RATE`, `BILLING_MINIMUM`.
- Billing page per company: this month's amount, invoice list, downloadable PDF. No payment page on purpose: no US entity yet, so no wire or ACH. Charlotte marks invoices paid from Platform → Billing or from the invoice itself.
- First invoices issued 10 Oct: KD-202610-003 (LLAP, 35 trucks, $140) and KD-202610-004 (BOOKIT, 36 trucks, $144), both due 24 Oct.
- BOOKIT's 36 includes the three trucks that exist twice (107, 5831, 777). Use Recount after cleaning them up, or set a price for the company.
- The invoice has no seller details beyond "Kaido" and the site address, and "Bill to" is only the company name: neither company has DOT, MC or a contact filled in on the Company page.
- Settings and Billing left the top bar; they are in the menu under the user's name with Account and Sign out.
- Saved shops: notes were in a one-line box that hid everything past a few words, dropped line breaks, and cut a note to 300 characters when the row was saved. Notes are now a full multi-line box up to 600 characters, and the name and phone columns are wide enough to read.

## New domain and editable service list (13 Oct 2026)
- Live on https://kaidofleet.com; www and kaido.shahlo.blog redirect to it (see "Live" at the top).
- The service list under each truck is editable by admins. For the whole company: Maintenance → Preventive maintenance list (add a service with an interval, remove one, put one back). For one truck: the truck's page → Service schedule → Edit list (add, remove or give it its own interval on that truck only).
- A service the company adds also shows in the work-order picker under Preventive maintenance. Built-in PM items that had no schedule before (grease, filters, fluids, valve adjustment, wash) can now be counted too: give them an interval on Trucks → Service intervals.
- Oil and the DOT annual are not part of this list. Oil's interval is on each truck, and the DOT annual comes from the inspection date.
- Nothing was changed in either company's list: both still show the same eight services as before.

## Front page, bell, no cat (13 Oct 2026, later)
- kaidofleet.com opened a public front page with a contact form. (Taken down again on 17 Nov 2026, see below.)
- The cat is gone from the notification center; it is a plain bell now.
- The 8pm daily notes are gone: the cron line, `bin/encourage.sh` and `app/encourage.py` were removed. Old ones stay in each person's "Earlier" list.
- Reminders set by hand now also show in the bell when they are due, with an Open button to the record. The reminder on BOOKIT unit 114's work order (#29, "upload invoice once Loves issues PO") was already due, so it was put in the bell for Charlotte and John.
- The daily follow-up on Telegram was not touched.
- Picture captcha: sign-in uses hCaptcha's click-the-pictures check since 13 Oct (keys in `.env`). The hCaptcha account is on a 14-day Pro trial that drops to the free plan on 27 Oct; nothing to pay. If hCaptcha is unreachable, sign-in is refused: emptying `HCAPTCHA_SECRET` and restarting brings the built-in letters picture back.


## Fuel desk, private site, new icon (17 Nov 2026)
- **Kaido is private now.** The public front page and its contact form are gone (spam from "SEO" sellers). `/` goes to sign-in, robots.txt blocks everything, every page says noindex. The icon is a plain navy square with a white K.
- **Fuel is the new focus.** README → Fuel has the full description. In short:
  - Samsara now gives Kaido every truck's **tank %**, heading and speed (30/30 BOOKIT trucks, 33/35 LLAP report it). Each sync also keeps a position track in `truck_positions`.
  - Truck stops come from OpenStreetMap (`manage.py fuel-directory`). The first full load ran on 17 Nov; Overpass was overloaded, so it went state by state.
  - Every EFS purchase is split into pump price, discount and what we really paid, matched to a station, and checked for a cheaper stop nearby (**missed savings**). BOOKIT, 1 Sep–13 Oct: 295 diesel fills, $11,743 in discounts, $307.67 missed on 17 fills.
  - **Fuel stop cards in the truck groups** with Accept / Skip (and a reason), driver preferences (`/fuelprefs`), `/fuel` on demand, `/fuelweek`, and weekly picture reports to drivers and admins.
  - Web: Fuel → Insights / Purchases / Driver suggestions / Prices / Fuel assistant. The truck page shows tank %, range, MPG and recent suggestions. Tank size is on the truck form (default 200 gal).
- **It is switched off for every company.** Turn it on in Fuel → Fuel assistant. Drivers only get cards in truck groups that are connected (`/truck` code, then `/unit`), and **no truck group is connected yet**.
- No live daily prices yet: suggestions use the prices the company paid in the last 90 days (age shown on the card), plus any price list uploaded on Fuel → Prices. BOOKIT's last EFS import is 13 Oct, so cards show October prices marked with their age until a new EFS report or price list is imported.
- The old-job shift bots (pfp-swap) were taken off cron the same night; nothing in Kaido depended on them.
- **Later on 17 Nov:** she wants prices fetched from the brand websites ("fine" with it). Love's is built:
  `manage.py brand-prices` reads every Love's travel stop page (about 620) for today's diesel and DEF price,
  parking spaces, showers, scale and repair. Cards then show "$5.160/gal est. (pump $5.619 now, −$0.46 your usual
  discount)", using the company's average discount at that brand. The **twice-a-day cron line and the first full
  fetch were not added by Claude** (the Claude Code safety check stopped it). Charlotte runs them herself:
  `/root/kaido/bin/brand-prices.sh` once, and the cron line `15 4,16 * * * /root/kaido/bin/brand-prices.sh`.
- Fuel → Prices has "Download a sample built from your purchases" for showing the price-list upload.
- TA / Petro added to the website prices the same night (367 locations). Pilot / Flying J blocks the server (403), so it is not fetched.
- **No emojis in any message Kaido sends** (her rule, 17 Nov): fuel cards, buttons, reports, PTI and summary messages are plain text. Stops are numbered "1.", buttons say "Take 1. ...", "Skip", "More stops".

## Trip planning (18 Nov 2026, after midnight)
- Paste a load, pick a truck, and Kaido routes it from the truck's position, picks the cheapest fuel stops and how many gallons to buy at each, simulates the driver's hours from Horizon, and gives ETAs against the windows. It sends the plan to the truck group with Accept / Problem buttons. README → Trip planning.
- First real test: the sample load 88M4295 (Browns Summit NC to Moreno Valley CA, $5,699) on a BOOKIT truck, trip #1. 2,658 mi (192 empty), 2 fuel stops (Love's Dickson TN 170 gal, Love's Amarillo 120 gal), about $1,518 of fuel, $102 under the route average. Horizon showed only 16.8 h left on the driver's 70-hour cycle, so the plan needs a 34-hour restart and delivers about 22 h late. That is the warning the planner exists for.
- Routing uses the free OSRM demo server (car profile, no truck restrictions such as low bridges or hazmat). A truck-aware router (e.g. a paid one or self-hosted OSRM with a truck profile) is the upgrade if it matters.
- Her rules for trips (18 Nov): **one truck stop at a time** ("when it's almost over or close should ask again"), re-plan when the driver skips, show the hours left on the ELD, and **fill the tank before expensive states like California**. All built; re-planned trip #2 for the sample load fills in AR, TX and NM and tops off in AZ before CA ($7.35 avg there).
- **Nothing is sent to any group until she says so** ("wait don't send message to group yet", 18 Nov). Trips #1 and #2 are drafts. Note that linking a truck group also starts the PTI reminders for that truck (company PTI setting), not only fuel.
- 18 Nov: plan a trip on "closest live truck" or "random live truck" (she asked for a random BOOKIT driver who is live on Samsara; random picked a truck in California for an NC pickup, so "closest" is the sensible one to show). Messages show the remaining fuel as gallons and miles. A truck group is renamed to its unit when connected (`/rename` to redo).
- 18 Nov: BOOKIT PTI reminders cut to **Mondays only** (first one Mon 23 Nov), at her request ("maybe once a week but not this week"). The "drove without a pre-trip" nudge now also only goes on the scheduled days; it used to go any day.
- 18 Nov: "driver ain't reading all this": every driver message (trip plan, next stop, /fuel card) cut to a few lines. The full detail stays on the trip page. Trip #5 (her test group, Unit 5831) was edited in place to the short form.
- 18 Nov: no trip overview to drivers ("all this pickup delivery info is sent to group already"). Send to driver posts only the fuel stop; late/restart warnings go to admins. The old overview in her test group was deleted and the fuel stop sent fresh.
- 18 Nov: after a fill-up the truck group gets a short "Fueled" note (station, % before/after, gallons, $, planned or not). Trip #5 had been set to declined by a tap on "Problem with plan → Other" on the old overview; set back to sent so the test keeps following the truck.
- 18 Nov: John showed the fuel-stop message from the app at his work (station, address, map, parking, miles ahead, % on arrival). Kaido's next-stop message now has the street address, % on arrival and truck spots too, on top of price, gallons, ELD hours and the Fuel there / Skip buttons.
- 18 Nov: fuel fraud and theft checks (EFS purchase vs Samsara tank and GPS, double fills, tank drop while parked). Admins get each on Telegram; Fuel → Fuel checks to review. Over BOOKIT's Sep–Oct history only one fired (two fills 15 min apart on 1 Oct). She said a pre-booking "is this load worth it" check is not needed in the bot since loads are already booked; the Trips page already shows rate after fuel.
- 18 Nov: removed the "How drivers use it" box from Fuel → Fuel assistant (she did not want it shown); that page now shows Connected trucks with tank and whether the driver fueled. Prices page showed only 194 stations (own purchases); it now includes today's website prices too, about 1,100.
- 18 Nov: explanation text removed across the app ("clear off all these junk words"): page-header descriptions, form hints and long notes. Headers keep only live numbers (counts, totals). Empty states are a few words. Driver-facing PTI pages, stickers and error pages keep their wording.
- 18 Nov: she cannot get a fresh EFS Transaction Report for BOOKIT ("they will leave soon anyway"), so BOOKIT has **360 demo purchases** (310 diesel, 50 DEF, 20 Oct–16 Nov, about $234k) from `manage.py fuel-demo`. They are marked demo everywhere; `manage.py fuel-demo --company BOOKIT --remove` deletes them and their prices. Samsara readings have a gap 5–16 Nov (server was off), filled with each truck's average day.
- 19 Nov: the Fueled note in her test group said "Not the planned stop (Love's #883)" with no station. Trip #5 is the sample NC to CA load on Unit 5831, but the truck was running its own load in Mississippi, and the note looked up the station from the reading after the fill (15 mi down the road). It now uses the point where the truck stood still (Love's #398, Tupelo MS for that fill), and skips the planned line when the truck is off the trip route. Record #1 in `fuel_refuels` was corrected; the Telegram message itself was not edited.
- 19 Nov: live trip map. Every trip has a no-login link (`/m/<token>`) showing the route, the truck now (refreshed each minute), pickup/delivery and fuel stops with ETAs, and where the driver rests. Fuel-stop messages carry a "Trip map" link; the trip page has a Live map button. Trips can also be planned from plain places (one place = fuel-only run, or "A to B") and from dispatch's load post in a truck group. That last one is behind "Plan trips from load posts in truck groups" on Fuel → Fuel assistant, **off**, and the bot only sees ordinary group messages where it is a group admin (privacy mode is on in BotFather).
- 19 Nov: explanation text removed from the pages seen before login (sign in, code, block, error pages, PTI driver page) and the leftover hints inside the app.
- 20 Nov: she is starting in a fleet maintenance department and wanted to learn the basics, "deep", with pictures and videos. Built Learn (`/learn`): 20 topics with tables, 22 pictures (Commons photos with credits plus 7 drawn diagrams) and YouTube search links per topic. Reefer and APU photos were not fetched (Commons rate limit).
- 20 Nov: Integrations said "66 of 41 trucks linked": it counted Samsara and Horizon links together. Now Samsara only, one per truck (BOOKIT 30 of 41, LLAP 35 of 35); the mapping table lists only Samsara vehicles.
- 20 Nov: "why do trips all show late": all five trips are the sample load whose pickup was 17 Nov, planned for drivers with about 18.5 h left on the 70-hour clock, so they needed a 34 h restart. The planner now also gives back hours each night as old days drop off the 8-day window (estimated as hours used / 8 per day, since Horizon gives no daily history).
- 20 Nov: her Claude Docs manual "Fleet From Scratch" (main tab, Parts A to Z, Study schedule) was converted into Learn as 47 more topics. Personal references (John's notes, Octane) were made general because every signed-in user sees Learn. The doc itself was not changed.
- 20 Nov: menu cut down at her request: Dashboard, Trucks (Drivers and Faults are tabs inside it), Fuel, Trips, Maintenance, PTI, Cases, Learn. Breakdowns are called **Cases** everywhere (URLs still `/breakdowns`). Reminders, Reports, Company, Integrations and Platform moved into the profile menu with Account, Settings and Billing.
- 20 Nov: all logs now live in `logs/` (sync, followup, backup, brand-prices, errors). `bin/*.sh`, the crontab backup line and `/etc/logrotate.d/kaido` point there. The Fleet From Scratch PDF is in `uploads/learn/` (not in git; it has personal names) and downloads from Learn for signed-in users only.
- 20 Nov: Learn had "Basics" and "Fleet From Scratch" covering the same subjects twice. Merged into one Topics group of 28 pages (one per subject), plus Parts A to Z and the study plan; the glossaries are one table of 98 terms.
- 20 Nov: fuel price fetch (Love's, TA/Petro) now runs from cron every day at 7:00 US Eastern (`CRON_TZ=America/New_York` line at the end of the crontab). The "tank dropped while parked" check now waits for the truck to run on and compares with the expected burn; rechecked against the four alerts so far it keeps Units 008 and 107 and clears the two gauge glitches (0851, 5226), which were marked ok.
- 20 Nov: EIA weekly regional diesel averages added as the last price fallback for trips (README → Fuel). She asked for current pump prices everywhere: only Love's and TA/Petro give those for free; for every other stop the real source is the fuel card network's daily price file (to build once she knows her new job's card) or a paid feed (OPIS, DTN, GasBuddy Business). A probe of other brand sites was blocked by the Claude Code safety check (it spoofed a browser user agent).
- 20 Nov: Fuel → Insights has a Diesel market section (EIA national and regional averages with weekly, monthly and yearly change, a 12-week chart, and Love's/TA pump averages per state saved daily). Asked for by her: national, per-state averages and whether prices went up or down.
- 20 Nov: every filter now opens on everything (her rule): work orders, cases, faults and fuel checks default to All, and Fuel insights has an All period (the default) beside 7, 30 and 90 days.
- 22 Nov: she wants a fuel place sent every time the tank runs low, wherever the driver is, and by the load when dispatch posted one that day. The low-fuel card already picks stations around the truck's location; it now steps aside when the truck is on an active trip's route (`trips.covers`), so the driver gets only the trip's next stop, never two messages. Trip #5 (sample load) does not cover Unit 5831 since the truck is off that route, so 5831 gets the location card. Turning the assistant on for BOOKIT from the shell was blocked by the safety check; she switches it on in Fuel → Fuel assistant.
- 22 Nov: truck health alerts built (README → Truck health alerts), sent on the first detection as she asked. First run sent 9: idling 4531 and 005, DEF 0% on 0353, no signal on 5028 and 17, battery low on 014, 7832 and 182, oil 13 psi at 1,389 rpm on 004B. 777 is a dead unit (last signal 25 Sep) and is skipped. No tire sensors in either fleet.
- 22 Nov: filler text cut from the web pages at her request ("Where the trucks are" over the dashboard map, map legend sentences, settings menu descriptions, intro paragraphs on PM list, saved shops and intervals, and similar subtitles).
- 22 Nov: the four draft sample trips (1-4) set to delivered; done trips now show as "delivered". Trip 5 was already cancelled.
- 23 Nov: hours, service-due, MPG-drop, safety and speeding alerts, a Safety tab under Trucks and an Alerts page in the top menu (README). Samsara tokens answer 403 for /fleet/hos/clocks and /fleet/hos/violations, so hours use Horizon (BOOKIT) only; LLAP needs the HOS read scope added to its token. No truck has a service baseline, so service alerts wait for Settings → Service baselines. First live run: MPG drop on BMG 020, 777 and 0638; one safety alert each company. About 34 instant safety alerts a day expected across both fleets.
- 23 Nov: Trailers under Trucks (number, type, VIN, plate, status, the truck it is with). Samsara has no trailers on either account, so they are entered by hand. Taken from fleetorly.com.
- 23 Nov: Documents with expiry dates and files for drivers, trucks, trailers and the company, with Telegram alerts at 30, 14, 7, 1 days and on the day, and a Missing list (README → Documents). The old licence/medical/registration/insurance date fields moved there (all were empty). Nothing is on file yet.
- 23 Nov: Status board under Trucks and a home yard address on the Company page (from fleetorly.com). No home yard is set yet, so no truck shows as Home.
- 23 Nov: shop finder place types (towing, tires, mobile mechanic, reefer, trailer, parking, truck wash), Text the job / Copy the job, and shop ratings on work orders (from fleetorly.com; its vendor marketplace, financing and fuel-card offers were left out). The OpenStreetMap shop cache was cleared because the query now also fetches truck parking and truck washes.
- 23 Nov: document alerts are off for every company (her request: nothing is logged yet). Turn on from the Documents page; existing papers then start from their current step instead of sending every missed one.
- 23 Nov: alerts group with one Telegram topic per issue (README → Alerts group). She made the group and the bot admin; it links when she sends /alerts there, then the past 314 alerts, follow-ups and summaries (both companies) are replayed. Office alerts then go to the group instead of DMs. Tire pressure alert added; Samsara accepts the `tirePressure` stat but no truck in either fleet reports it.
- 23 Nov: alerts group limited to BOOKIT at her request (`companies.alerts_group`, set true only for BOOKIT). LLAP alerts stay in DMs.

## Redesign along Fleetio lines (25 Nov 2026)
- Backup before starting: `/root/backups/fleet/pre-redesign-20261125.sql.gz` (database) and `pre-redesign-uploads-20261125.tar.gz`; git tag `pre-redesign-20261125` is the code before any change.
- Stage 1: Cases merged into work orders (README → Work orders). Cases tab removed from the menu. The old tables stay as an archive.
- Stage 2: short new-work-order form, trucks or trailers (dropped trailers with a location), cancelled status, delete with confirmation, comments thread with photos and automatic status lines, costs folded away (README → Work orders).
- Stages 3 and 9: one page for unit and driver, trailer pages, See-all links filtered to the unit or driver, unit numbers and driver names linked on the dashboard, lists, trips, board and alerts (README → Unit and driver page).
- Stage 10: idle time on the unit/driver page and in Fuel insights, from the engine state the sync already gets. No new Samsara endpoint, so counting starts 25 Nov 2026 (README → Unit and driver page).
- Stage 4: carrier group and label on trucks, unit names cut to the number, Group filters on Trucks/Alerts/Fuel/Safety, Demo filter on Fuel, driver names in Title Case. Test junk listed for Charlotte; nothing deleted (README → Groups and names).
- 25 Nov, her request: place suggestions while typing in Where to send it, typo-tolerant (README → Where to send it).
- 25 Nov: Samsara sync and safety pull every 5 minutes (was 15); Horizon stays every 15 minutes because it is an unofficial API. `bin/sync.sh` runs Horizon only on the quarter hour and holds a lock so runs never overlap. A run takes 5 to 10 seconds.
- 25 Nov: test driver "Testtesttesttestc" deleted; its Horizon login is marked `driver_links.ignored` so Horizon does not bring it back. Kept at her request: work orders, trips and duplicate units. Driver 138 "Sdfsdfds Sdfsdfsdfsd" is linked to Horizon logins bawar2781 and bawar278 (likely Bawar Qodratullah, unit 1022), so it was not deleted; asked her.
- 25 Nov: driver 138 renamed to Bawar Qodratullah and the name locked, at her request (Horizon still has the junk name on logins bawar2781/bawar278).
- Stage 5: Hours view, Faults engine codes only, grouped alerts with statuses and Acknowledge/Clear, Alerts default to open, speeding threshold 10 mph / 30 s (README → Alerts, hours and safety). Safety events older than 7 days set to cleared.
- Stage 6 (report only, nothing changed): Day Payton Leondas "took Love's / fuelled elsewhere". The taps were Charlotte and John in the Unit 5831 test group, not the driver. `fuel_bot.match_refuels` reuses one tank jump for several older offers (2 h look-back each run, 12 h offer window), so 3 real fills marked all 7 offers. It also measures from the point after the jump with a 2 mi radius, not where the truck stood. On 25 Nov he fuelled at TA Express Rock Springs, option 1 on the card, but the tapped Love's #888 made it "elsewhere". Proposed fixes waiting for her yes.
- Stage 8: comeback flags (60-day window, per shop) and downtime per work order, per truck and on the dashboard (README → Comebacks and downtime). No real comebacks in the 5 existing work orders.
- Stage 11: recalls by make/model/year from NHTSA (no exact-VIN API), weekly cron Mon 05:30, unit page, dashboard count, Trucks filter, one-click work order (README → Recalls). 1,244 possible recalls on 72 trucks after the first run.
- Stage 12: top-bar search with / and Ctrl+K (README → Search). Noticed two more junk drivers made from Samsara vehicle names: "Mercury" and "Bawar Qodratullah Octane Mercury"; not touched.
- Stage 13: map layer switcher (Dark, Street, Satellite; radar, weather alerts, shops, towing, parking, showers), running/all truck filter, NWS weather alerts with truck badges on the map, status board and unit page (README → The fleet map). Traffic is built but hidden until a TomTom key is in `.env` (free tier 50,000 tiles a day). Status board cards fixed: a unit link nested inside the card link broke the layout.
- 25 Nov, her request: reminders removed from work orders; work order page in two columns (details left, status steps and activity right); Ask Claude panel replaced by a Claude button that opens a side drawer (work order and unit pages); app-wide refresh with Inter, sentence-case badges and headers, no double rules (README → Work orders).
- 25 Nov, her request: Claude moved to the top bar next to the profile on every page, using the Claude logo she sent (`app/static/claude.png`, from svgstack.com), with the whole company as context plus the truck on screen (README → Work orders, Claude). Tested with one real question; it listed low-fuel trucks and trucks in weather alerts.
- 25 Nov, her requests: Claude chat history and attachments (photos, PDFs), work order title shows only the unit (truck, trailer or both), Fuel menu opens on Insights, mouse-wheel zoom on every map. Her new Kaido logo (sent as /tmp/kaido-logo.svg) is in the top bar, sign-in, PTI pages and favicon.
- 25 Nov, her request: Where to send it shows Find shop / Find towing instead of asking whether the truck can drive.
- 26 Nov, her request: /root/Shops.xlsx (6 sheets, 914 distinct shops) imported into saved shops for LLAP and BOOKIT with the new `manage.py import-shops`. Each company: 234 added, about 100 existing shops given a note or service, 4 not added for having no location (DANIELS Mobile Repair, K&L Road Truck Repair, El Mechanico Mobile Diesel Repair, Nashville Heavy duty diesel truck & trailer repair). New `saved_shops.service` column (towing, mobile service, tires) from the sheet names. Backup before: /root/backups/fleet/saved_shops-pre-import-20261126.csv.gz. DFK transportation then got the same 928 (copied from LLAP), so all three companies match.
- 26 Nov, her requests: fuel suggestions for every truck on Fuel → Driver suggestions (live suggestion + map with truck, trip route, numbered stations, best highlighted; Send to driver only when the truck's Telegram group is connected, otherwise it stays on the page). EFS only: she uploads the EFS network list on Fuel → Prices; until then only stations the company has paid at with EFS are suggested (LLAP has 1 such station, so it gets almost no suggestions until the list is in). Fixed: a tank under the reserve searched the full 150 mi (truck at 8% got a stop 149 mi away); now never less than 25 mi. Same store under two names deduped. Finished work orders get Save shop with a comment. Telegram sign-in code is now a tap-to-copy `<code>` line.
- 26 Nov, her request: shop finder Sort dropdown (closest default, open now, cheapest we paid, best rated, used before). Saved shops no longer always lead; they sort with the rest. Cheapest and best rated have little data yet (few work orders with a cost or rating), so they mostly fall back to distance; no shop prices exist otherwise.
- 26 Nov, her request: an × delete button on each Maintenance list row (she had Open / Done / Delete first, then asked for only the ×).
- 26 Nov, her request: work orders show time at shop (waiting = in shop to in progress, repair = in progress to done) instead of downtime; work order PDF starts with the attached invoice pages (pypdf added). Dashboard and unit-page downtime left as they were.
- 27 Nov, her request: harsh turn and crash videos from Samsara safety events go to a new "Harsh turn and crash videos" topic in the alerts group. Past events were marked sent so the group was not flooded. LLAP and DFK set to `alerts_group`; BOOKIT and LLAP stay in the existing group; she is making a DFK group (rename to "DFK transportation", bot admin, Topics on, /alerts) and title matching links only DFK there.
- 27 Nov, her request: uploading an invoice on a work order reads it with Claude and fills parts, labor, tax and fees, total, invoice number, paid with and next due (empty fields only). Tested on a Love's invoice: labor 551.96, fees 38.56 after discount, total 590.52, correct. Rating and shop comment stay manual.
- 27 Nov: her first invoice (order 45) was saved a minute before the reader went live, so the server now also reads an invoice saved onto an order with no costs; order 45 filled (part 150, labor 780, tax 60.30, total 990.30, INV-1551). "Where to send it" hidden once an order is done or cancelled, her request.
- 27 Nov 2026: Maintenance list dropped the # column and gained Owner (who opened it) and Resolved by (who set it done, new `resolved_by` column), sortable by clicking the heading, plus a Person filter.
- 27 Nov 2026: Learn redesigned: landing search and quick links, new "See it" group (dash lamps drawn as icons, leak and smoke colors with swatches, tire wear drawings, sounds/smells/feelings, normal readings) and "Issues by system" (20 pages, 212 issue cards with what it looks/sounds/smells like, causes, checks, what to do, cost and DOT status), plus /learn/issues with filters.
- 27 Nov 2026: `manage.py watch-fuel` + a cron for 27-28 Nov (Tashkent) DMs her when Anthony's unit 7181 (DFK) fuels. Samsara has had no data from 7181 since 25 Nov 21:07 UTC (gateway likely unplugged), so the tank-rise check is blind until it reports again; fuel purchases only show if an EFS report is imported. Remove the cron line after 28 Nov.
- 27 Nov 2026: DFK (`companies.safety_all`) sends every Samsara safety event and its video to its alerts group. The DFK group is still not linked: nothing from it has reached the bot. She needs to add @KaidoBot as admin with Manage topics, turn Topics on, name it with "DFK", and send /alerts there.
- 27 Nov 2026 (night): Stage 7 built, walkaround PTI with vision AI (README -> Walkaround PTI). Claude key is in .env now, Sonnet 5.5 (`AI_PHOTO_MODEL`). Tested end to end with a real check (3.9 s) and review ($0.012); test records removed. Not tested on a real phone yet: camera, speech, voice recording and the Telegram in-app browser need her phone. Videos are cut into frames on the phone because the server has no ffmpeg.
- 27 Nov 2026 (night): Learn redesigned again around 11 truck systems with hub pages, shelves, reading progress and Mark as read.
- 27 Nov 2026: Maintenance list un-squeezed at her request: priority under status, Owner and Resolved by in one column, short columns kept on one line, descriptions clamped to two lines.
- 27 Nov 2026: walkaround is pre-trip only, has no Skip button and no driver list (the public link no longer shows the company's driver names); the driver types a name.
- 27 Nov 2026: walkaround languages changed to English, Russian and Uzbek (Latin), her request; Spanish and French removed. Many phones have no Uzbek text-to-speech voice, so Uzbek is shown but not spoken there.
