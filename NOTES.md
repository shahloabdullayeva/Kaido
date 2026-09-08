# Where Kaido stands — 9 Sep 2026

## Live

- **https://kaido.shahlo.blog** — main address, Let's Encrypt cert, renews itself
- **https://kaido.89.39.94.118.sslip.io** — same app, second hostname. Useful when a
  DNS cache has not caught up; sslip.io resolves any name with an IP in it.

Both stay live. When kaidofleet.com is bought: `./bin/golive.sh kaidofleet.com`
(add A records for `@` and `www` to 89.39.94.118 first), then the other two can go.

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

## Next, in the order worth doing

1. **The reminder engine.** The app computes oil and DOT-annual due dates but tells
   nobody. A morning Telegram digest per company is what turns it from a record
   book into something that warns you. Biggest single win left.
2. **Oil baselines.** Every truck says "no service on record", so no oil reminder can
   fire yet. Needs one real last-oil-change odometer per truck, entered once.
3. **EFS fuel feeds.** They are the parent account over 6 carriers and data sharing
   is available — needs the eManager switch and one sample file to write the parser.
4. **AI fault triage.** Plain-English explanation of a fault plus what to do. Deferred
   on purpose until the basics are solid.
5. **Google Maps** on the breakdown screen — nearby shops, detour distance, Love's.

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
