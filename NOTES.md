# Where Kaido stands — 12 Sep 2026

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

## Next, in the order worth doing

1. **The reminder engine.** The app computes oil and DOT-annual due dates but tells
   nobody. A morning Telegram digest per company is what turns it from a record
   book into something that warns you. Biggest single win left.
2. **Oil baselines.** Every truck says "no service on record", so no oil reminder can
   fire yet. Needs one real last-oil-change odometer per truck, entered once.
3. **EFS fuel feeds.** They are the parent account over 6 carriers and data sharing
   is available — needs the eManager switch and one sample file to write the parser.
4. **AI fault triage.** Plain-English explanation of a fault plus what to do. Deferred
   on purpose until the basics are solid; `advisor.py` is where it would go.

## Known gaps

- **DVIR is scope-gated.** Every defect endpoint answers 405 with the current token.
  Add the *Read DVIRs* scope in Samsara if drivers file inspections there.
- **The Samsara org has no tags,** so per-carrier token scoping is not possible yet.
  BMG and LLAP name prefixes look like two carriers sharing one org — worth deciding
  whether they should be two companies here.
- **Row-level security** is not on. Scoping is enforced in the query layer, and every
  cross-company check passes, but the database itself would still allow a bad query.
  Belongs in the hardening pass.
- **The Samsara token in use should be rotated** — it went through a chat.
- **Shop hours are only as good as OpenStreetMap.** A shop with no `opening_hours`
  tag shows "hours not listed" — phone ahead. Nothing in the app invents them.
- **Overpass is a free service with no SLA.** Answers are cached for seven days per
  0.01° map cell, and a stale answer is served when it is busy; if it is down and
  nothing is cached, the panel says so.
