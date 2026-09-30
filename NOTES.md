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
- **John** — admin at LLAP Logistics. **Still needs to link Telegram** before he can
  sign in from a new browser: send `/link <code>` to @kaidofleet_bot. Generate a
  fresh code from Account → Get link code, or from the shell.

Sign-in: password, then a 6-digit Telegram code on any browser we have not seen.
`TRUST_DAYS=1`, so a browser is trusted for one day and then asks again.
Both temporary passwords have travelled through chat — change them.

## Data in there now

LLAP Logistics LLC, synced from Samsara org 7009346: **35 trucks**, all VG55NA
gateways, average 760k miles. **30 drivers**, parsed out of the Samsara vehicle
names, 26 assigned to their truck. Fault codes flowing — 75 open on the first
sync, and the 15-minute job opens and closes them on its own.

Two demo companies (House Fleet, Bright Line Carriers) hold made-up data and can
be deleted whenever.

## Built on 12 Sep — where to send a truck

The work-order form now finds shops near the truck — or near any address you
type or point you click on the map, which is what the 9 demo-company trucks need
since only the 35 LLAP trucks have a Samsara feed. Positions come from Samsara on
every sync (35 of 35 trucks are reporting one), shops from OpenStreetMap, and the
map is Leaflet served from `static/vendor` — nothing from Google, nothing to pay
for. Distance, diesel cost of the round trip, opening hours and what this company
has paid at that shop before are all on the list. README → *Where to send it* has
the detail.

**Google Maps was not used.** Places would have been about $32 per 1,000 lookups
plus a billing account; OpenStreetMap is free and answers the same question. What
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
  fault codes, service due soon, papers expiring. The two demo companies have it switched off.
  Stop-lamp faults go out the moment the sync sees them. `bin/followup.sh` runs every 5 minutes.
- **Reminders on everything.** Every truck, driver, work order, breakdown and fault page has a
  Reminders box: pick a date and time, it arrives on Telegram (just you, or every admin).
- **Any truck, any driver.** The work order form takes outside trucks and outside drivers,
  saved with their carrier so they can be picked next time. They stay out of the fleet map and
  totals and have their own filter on the Trucks page. The driver can be changed on any order.
- **Reports.** Maintenance, fuel, breakdowns, faults and fleet status, filtered by dates, truck,
  driver and own/outside, downloadable as PDF, Excel or CSV. Each work order and breakdown has
  its own PDF.
- **Oil baselines.** Trucks → Oil baselines: type the last oil-change miles or upload a sheet.
- **EFS import.** Fuel → Import from EFS takes the eManager Transaction Report (CSV or Excel).
  Matches by unit, then card last 4; re-importing the same file is safe.
- **Claude.** Plain-English explanation on every fault page, stored per code so it is paid for
  once. An oil suggestion on oil work orders from the engine read off the VIN (NHTSA decoder,
  42 trucks decoded). A chat box on every truck and work order that sees the truck's record.
  All of it shares the $0.20 daily cap.
- **Company lock.** Postgres row-level security on every company table: inside a company's
  pages the database refuses other companies' rows even if a query forgets its filter.
- **Nightly backup** at 03:30 into /root/backups/fleet, 14 days kept.

## Next, in the order worth doing

1. **Oil baselines.** 35 trucks still say "no service on record". The page is there; it needs
   the numbers.
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
