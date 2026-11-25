#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

from app.config import ROOT
from app.db import execute, insert, one, rows
from app.security import hash_password, random_token


def cmd_migrate(args):
    from app.db import cursor
    sql = (ROOT / "db" / "schema.sql").read_text()
    with cursor() as cur:
        cur.execute(sql.encode())
    print("schema applied")


def cmd_bootstrap(args):
    existing = one("select id from users where platform_role is not null limit 1")
    if existing and not args.force:
        print("A platform owner already exists. Use --force to add another.")
        return 1
    password = args.password or random_token(9)
    user = one("select * from users where lower(email) = lower(%s)", (args.email,))
    if user:
        execute("update users set platform_role = 'owner', name = %s, updated_at = now() where id = %s", (args.name, user["id"]))
        print(f"Promoted {args.email} to platform owner.")
    else:
        user = insert(
            "insert into users (email, name, password_hash, platform_role) values (%s, %s, %s, 'owner') returning *",
            (args.email.lower(), args.name, hash_password(password)),
        )
        print(f"Created platform owner {args.email}")
        print(f"Temporary password: {password}")
    if args.company:
        company = one("select * from companies where lower(name) = lower(%s)", (args.company,))
        if not company:
            company = insert(
                "insert into companies (name, is_house) values (%s, true) returning *", (args.company,)
            )
            print(f"Created company {company['name']}")
        exists = one("select id from memberships where user_id = %s and company_id = %s", (user["id"], company["id"]))
        if not exists:
            execute("insert into memberships (user_id, company_id, role) values (%s, %s, 'admin')", (user["id"], company["id"]))
    return 0


def cmd_company(args):
    company = insert(
        "insert into companies (name, dot_number, is_house) values (%s, %s, %s) returning *",
        (args.name, args.dot, args.house),
    )
    print(f"Created company #{company['id']}: {company['name']}")
    return 0


def cmd_user(args):
    company = None
    if args.company:
        company = one("select * from companies where lower(name) = lower(%s)", (args.company,))
        if not company:
            print(f"No company named {args.company}")
            return 1
    password = args.password or random_token(9)
    user = one("select * from users where lower(email) = lower(%s)", (args.email,))
    if user:
        print(f"User {args.email} already exists")
    else:
        user = insert(
            "insert into users (email, name, password_hash, platform_role) values (%s, %s, %s, %s) returning *",
            (args.email.lower(), args.name, hash_password(password), args.platform_role),
        )
        print(f"Created {args.email}")
        print(f"Temporary password: {password}")
    if args.telegram:
        execute("update users set telegram_chat_id = %s where id = %s", (args.telegram, user["id"]))
        print(f"Linked Telegram chat {args.telegram}")
    if company:
        exists = one("select id from memberships where user_id = %s and company_id = %s", (user["id"], company["id"]))
        if exists:
            execute("update memberships set role = %s where id = %s", (args.role, exists["id"]))
        else:
            execute("insert into memberships (user_id, company_id, role) values (%s, %s, %s)", (user["id"], company["id"], args.role))
        print(f"{args.email} is {args.role} at {company['name']}")
    return 0


def cmd_reset_password(args):
    from app.telegram import send

    user = one("select * from users where lower(email) = lower(%s)", (args.email,))
    if not user:
        print(f"No user {args.email}")
        return 1
    password = "K" + random_token(12) + "7a"
    execute(
        "update users set password_hash = %s, failed_logins = 0, locked_until = null, updated_at = now() where id = %s",
        (hash_password(password), user["id"]),
    )
    execute("update sessions set revoked_at = now() where user_id = %s and revoked_at is null", (user["id"],))
    execute("delete from throttle where key = %s", (f"login:email:{user['email'].lower()}",))
    sent = send(user["telegram_chat_id"], "\n".join([
        "<b>Kaido password reset</b>",
        f"Temporary password: <code>{password}</code>",
        "Sign in, change it on the Account page, then delete this message.",
    ]))
    if sent["ok"]:
        print(f"New password for {user['email']} sent to their Telegram. Every session was signed out.")
    else:
        print(f"Telegram did not deliver ({sent.get('reason')}). Temporary password: {password}")
    return 0


def cmd_sync(args):
    from app.sync import sync_all, sync_company
    if args.all:
        results = sync_all()
        if not results:
            print("No company has Samsara connected.")
        for name, result in results.items():
            print(f"{name}: {result}")
        return 0
    company = one("select * from companies where lower(name) = lower(%s)", (args.company,))
    if not company:
        print(f"No company named {args.company}")
        return 1
    print(sync_company(company["id"]))
    return 0


def cmd_safety(args):
    from app import safety
    for name, result in safety.run().items():
        print(f"{name} safety: {result}")
    return 0


def cmd_horizon_connect(args):
    from app import horizon
    company = one("select * from companies where lower(name) = lower(%s)", (args.company,))
    if not company:
        print(f"No company named {args.company}")
        return 1
    horizon.connect(company["id"], args.user, args.password, args.company_key)
    print(f"Horizon connected for {company['name']}")
    return 0


def cmd_horizon_sync(args):
    from app.horizon import sync_all, sync_company
    if args.all:
        results = sync_all()
        if not results:
            print("No company has Horizon connected.")
        for name, result in results.items():
            print(f"{name}: {result}")
        return 0
    company = one("select * from companies where lower(name) = lower(%s)", (args.company,))
    if not company:
        print(f"No company named {args.company}")
        return 1
    print(sync_company(company["id"]))
    return 0


def cmd_google_usage(args):
    from app import google_places
    from app.config import config
    if not google_places.available():
        print("GOOGLE_MAPS_API_KEY is not set — shop search uses OpenStreetMap.")
    print(f"Today: {google_places.calls_today()} of {config.GOOGLE_DAILY_CALLS} calls allowed")
    print("This month:")
    for item in google_places.month_usage():
        print(f"  {item['sku']:<24} {item['used']:>6} used, {item['free']:>6} free, est. ${item['cost']:.2f}")
    return 0


def cmd_ai_spend(args):
    from app.advisor import MODEL, spent_today, spent_total
    from app.config import config
    total, calls = spent_total()
    today = spent_today()
    days = rows(
        """select date_trunc('day', created_at)::date as day, count(*) as calls,
                  sum(cost_usd) as cost from ai_usage
           group by 1 order by 1 desc limit %s""",
        (args.days,),
    )
    print(f"Model {MODEL}, daily cap ${config.AI_DAILY_USD:.2f}")
    for day in days:
        print(f"  {day['day']}  {day['calls']:>4} lookups  ${float(day['cost']):.4f}")
    print(f"Today ${today:.4f} of ${config.AI_DAILY_USD:.2f}")
    print(f"All time ${total:.4f} over {calls} lookups")
    if calls:
        each = total / calls
        print(f"About ${each:.4f} each — ${args.credit:.2f} of credit is roughly {int(args.credit / each)} lookups")
        print(f"At the cap every day, ${args.credit:.2f} lasts {int(args.credit / config.AI_DAILY_USD)} days")
    cached = one("select count(*) as n from ai_cache where fetched_at > now() - make_interval(days => 7)")
    print(f"{cached['n']} answers cached and free to serve again")
    return 0


def cmd_followup(args):
    from app import followup, reminders
    if args.show:
        company = one("select * from companies where lower(name) = lower(%s)", (args.show,))
        if not company:
            print(f"No company called {args.show}")
            return 1
        from datetime import datetime
        today = datetime.now(reminders.zone_for(company["timezone"])).date()
        print(followup.build(company, today))
        return 0
    if args.send_now:
        company = one("select * from companies where lower(name) = lower(%s)", (args.send_now,))
        if not company:
            print(f"No company called {args.send_now}")
            return 1
        print(followup.run(force_company=company["id"]))
        return 0
    from app import billing
    billing.issue_missing()
    reminded = reminders.send_due()
    reminders.notify_due()
    alerted = followup.send_fault_alerts()
    sent = followup.run()
    from app import pti_driver
    drivers = pti_driver.run()
    from app import fuel_bot, fuel_report
    fueled, reports = {"offers": [], "refuels": 0, "receipts": 0}, {}
    try:
        fueled = fuel_bot.run()
        reports = fuel_report.run()
        from app import fuel_guard, trips
        guarded = fuel_guard.run()
        if guarded["alerts"]:
            print(f"fuel checks {guarded}")
        followed = trips.follow()
        if followed:
            print(f"trips {followed}")
    except Exception:
        from app.logs import get
        get("fuel").exception("fuel run failed")
    try:
        from app import health
        checked = health.run()
        if checked:
            print(f"health alerts {checked}")
    except Exception:
        from app.logs import get
        get("health").exception("health run failed")
    try:
        from app import documents
        noted = documents.run()
        if noted:
            print(f"document alerts {noted}")
    except Exception:
        from app.logs import get
        get("documents").exception("document alerts failed")
    if reminded or alerted or sent or drivers:
        print(f"reminders {reminded}, fault alerts {alerted}, follow-ups {sent}, driver PTI messages {drivers}")
    if fueled["offers"] or fueled["refuels"] or fueled["receipts"] or fueled.get("fueled") or reports:
        print(f"fuel offers {fueled['offers']}, fueled notes {fueled.get('fueled')}, refuels matched {fueled['refuels']}, receipts matched {fueled['receipts']}, reports {reports}")
    return 0


def handle_group_update(update, send):
    from app import pti_driver
    member = update.get("my_chat_member")
    if member:
        status = (member.get("new_chat_member") or {}).get("status")
        chat = member.get("chat") or {}
        if status in ("left", "kicked") and chat.get("id"):
            pti_driver.forget_group(chat["id"])
            from app.db import execute
            execute("delete from alert_groups where chat_id = %s", (chat["id"],))
        elif status == "administrator" and chat.get("is_forum"):
            from app import alert_group
            if alert_group.kaido_user(member.get("from") or {}) and not alert_group.chat_of_any(chat["id"]):
                alert_group.handle(chat, member.get("from") or {})
        return True
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    if chat.get("type") not in ("group", "supergroup"):
        return False
    if message.get("migrate_to_chat_id"):
        pti_driver.move_group(chat["id"], message["migrate_to_chat_id"])
        return True
    parts = (message.get("text") or "").split()
    command = parts[0].split("@")[0] if parts else ""
    if command == "/alerts":
        from app import alert_group
        try:
            alert_group.handle(chat, message.get("from") or {}, message.get("message_id"))
        except Exception:
            from app.logs import get
            get("telegram-bot").exception("/alerts in %s failed", chat["id"])
            send(chat["id"], "Something went wrong setting up alerts here.")
        return True
    if command == "/unit":
        _truck, reply = pti_driver.claim_unit(chat["id"], message.get("from") or {}, " ".join(parts[1:]))
        send(chat["id"], reply, reply_to_message_id=message.get("message_id"))
        return True
    if command == "/rename":
        linked = pti_driver.group_trucks(chat["id"])
        if len(linked) != 1:
            send(chat["id"], "This group is not connected to one truck. Send /truck with the code from the truck's page first.")
        elif not pti_driver.rename_group(chat["id"], linked[0]).get("ok"):
            send(chat["id"], "The bot needs to be an admin with \"Change group info\" to rename the group.")
        return True
    if command.startswith("/fuel"):
        from app import fuel_bot
        from app.logs import get
        try:
            fuel_bot.handle_command(command, chat["id"], message)
        except Exception:
            get("telegram-bot").exception("fuel command %s failed", command)
            send(chat["id"], "Something went wrong with that. The office has been told.")
        return True
    if not command.startswith("/"):
        from app import trips
        try:
            trips.from_group_post(chat["id"], message)
        except Exception:
            from app.logs import get
            get("telegram-bot").exception("load post in %s failed", chat["id"])
        return True
    if command not in ("/truck", "/drivers"):
        return True
    if len(parts) < 2:
        send(chat["id"], "Send /truck followed by the code from the truck's page in Kaido.")
        return True
    truck = pti_driver.claim_group(parts[1], chat)
    if not truck:
        send(chat["id"], "That code is not valid. Copy it again from the truck's page in Kaido.")
        return True
    send(chat["id"], f"Connected to Unit {truck['unit_number']} ({truck['company_name']}). "
                     "PTI reminders for this truck only will come here. Driver: send /unit once so they tag you.")
    renamed = pti_driver.rename_group(chat["id"], truck)
    if not renamed.get("ok"):
        send(chat["id"], "To name this group after the unit, make the bot an admin with \"Change group info\" "
                         "and send /rename, or rename it by hand.")
    return True


def cmd_alerts_history(args):
    from app import alert_group
    print(alert_group.send_history(args.chat))
    return 0


def cmd_summary(args):
    from app import summary
    print(summary.run(args.backup or []))
    return 0


def cmd_saved_shop_details(args):
    import time
    from app import shops
    todo = rows(
        """select distinct round(latitude, 5) as lat, round(longitude, 5) as lon from saved_shops
           where address is null and details_checked_at is null limit %s""",
        (args.limit,),
    )
    filled = failed = 0
    for spot in todo:
        try:
            label = shops.reverse(spot["lat"], spot["lon"])
        except Exception as err:
            failed += 1
            print(f"{spot['lat']},{spot['lon']}: {err}")
            if failed >= 10:
                break
            time.sleep(5)
            continue
        execute(
            """update saved_shops set address = coalesce(address, %s), details_checked_at = now()
               where round(latitude, 5) = %s and round(longitude, 5) = %s""",
            (label, spot["lat"], spot["lon"]),
        )
        filled += 1 if label else 0
    print(f"addresses filled for {filled} of {len(todo)} places, {failed} failed")
    return 0


def cmd_pti_cleanup(args):
    from app import pti
    print(f"removed {pti.cleanup_media()} PTI photos/videos older than {pti.KEEP_MEDIA_DAYS} days")
    return 0


def cmd_telegram(args):
    import time
    from app.logs import get
    from app.telegram import TelegramDown, enabled, get_updates, send
    log = get("telegram-bot")
    if not enabled():
        print("TELEGRAM_BOT_TOKEN is not set in .env")
        return 1
    offset = None
    print("Listening for /link codes. Ctrl-C to stop.")
    failures = 0
    while True:
        try:
            updates = get_updates(offset)
            failures = 0
        except TelegramDown as err:
            failures += 1
            if failures in (1, 10) or failures % 100 == 0:
                log.warning("Telegram unreachable (%s in a row): %s", failures, err)
            time.sleep(min(60, 5 * failures))
            continue
        for update in updates:
            offset = update["update_id"] + 1
            if update.get("callback_query"):
                from app import fuel_bot, trips
                try:
                    query = update["callback_query"]
                    if (query.get("data") or "").startswith("t"):
                        trips.handle_callback(query)
                    else:
                        fuel_bot.handle_callback(query)
                except Exception:
                    log.exception("fuel button failed")
                continue
            if handle_group_update(update, send):
                continue
            message = update.get("message") or {}
            text = (message.get("text") or "").strip()
            chat = message.get("chat") or {}
            chat_id = chat.get("id")
            if not chat_id or not text:
                continue
            parts = text.split()
            if parts[0] in ("/link", "/start") and len(parts) > 1:
                code = parts[1]
                link = one(
                    "select * from telegram_links where code = %s and used_at is null and expires_at > now()",
                    (code,),
                )
                if not link:
                    send(chat_id, "That code is not valid or has expired. Generate a new one on your account page.")
                    continue
                execute("update telegram_links set used_at = now() where id = %s", (link["id"],))
                execute(
                    "update users set telegram_chat_id = %s, telegram_username = %s, updated_at = now() where id = %s",
                    (chat_id, chat.get("username"), link["user_id"]),
                )
                user = one("select name from users where id = %s", (link["user_id"],))
                send(chat_id, f"Linked. Sign-in codes for {user['name']} will arrive here.")
            elif parts[0] == "/start":
                send(chat_id, "Send /link followed by the code from your Kaido account page.")


def cmd_fuel_directory(args):
    from app import fuel
    states = [s.strip().upper() for s in args.states.split(",")] if args.states else None
    done = fuel.load_directory(states)
    failed = [state for state, count in done.items() if count is None]
    print(f"stations saved: {sum(c for c in done.values() if c)}; failed states: {','.join(failed) or 'none'}")
    return 1 if failed else 0


def cmd_fuel_prepare(args):
    from app import fuel
    company = one("select id from companies where lower(name) = lower(%s)", (args.company,)) if args.company else None
    company_id = company["id"] if company else None
    print(f"purchases matched to stations: {fuel.enrich(company_id)}")
    print(f"purchases checked for cheaper stops: {fuel.analyse(company_id, recheck=args.recheck)}")
    return 0


def cmd_fuel(args):
    from app import fuel_bot
    print(fuel_bot.run(force=args.force))
    return 0


def cmd_fuel_report(args):
    from app import fuel_report
    company = one("select * from companies where lower(name) = lower(%s)", (args.company,)) if args.company else None
    print(fuel_report.run(company=company, send=not args.dry_run, force=args.force))
    return 0


def cmd_eia_prices(args):
    from app import eia
    print(eia.run())
    print({"states_saved": eia.snapshot_states()})
    return 0


def cmd_brand_prices(args):
    from app import brand_prices
    only = [s.strip().upper() for s in args.states.split(",")] if args.states else None
    print(brand_prices.run(args.brand or None, limit=args.limit, only=only))
    return 0


def cmd_trip(args):
    from app import trips
    from app.fuel_bot import TRUCK_SQL
    company = one("select * from companies where lower(name) = lower(%s)", (args.company,))
    if not company:
        print(f"No company named {args.company}")
        return 1
    text = Path(args.file).read_text() if args.file else sys.stdin.read()
    if args.truck in ("random", "nearest"):
        picked = trips.random_active_truck(company["id"]) if args.truck == "random" \
            else trips.nearest_active_truck(company["id"], trips.parse_load(text))
        found = [picked] if picked else []
    else:
        found = [t for t in rows(TRUCK_SQL + " where t.company_id = %s and t.status <> 'sold'", (company["id"],))
                 if t["unit_number"].split()[0].lstrip("0") == args.truck.lstrip("0")]
    if not found:
        print(f"No unit {args.truck}")
        return 1
    from datetime import datetime, timezone
    found.sort(key=lambda t: t["located_at"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    trip = trips.build(company["id"], found[0], trips.parse_load(text), text=text)
    print(f"trip #{trip['id']}")
    print(trips.message(trip, found[0]))
    if args.send:
        print(trips.send_to_driver(trip["id"]))
    return 0


def cmd_fuel_demo(args):
    from app import fuel, fuel_demo
    company = one("select * from companies where lower(name) = lower(%s)", (args.company,))
    if not company:
        print(f"No company named {args.company}")
        return 1
    if args.remove:
        print(f"removed {fuel_demo.remove(company['id'])} demo purchases")
        return 0
    if fuel_demo.count(company["id"]):
        print("This company already has demo purchases. Remove them first with --remove.")
        return 1
    print(f"added {fuel_demo.generate(company['id'], args.days)} demo purchases")
    print(f"checked for cheaper stops: {fuel.analyse(company['id'])}")
    return 0


def cmd_cat(args):
    from app import cat
    user = one("select id, name from users where lower(email) = lower(%s) or lower(name) = lower(%s)", (args.to, args.to))
    if not user:
        print(f"no user {args.to}", file=sys.stderr)
        return 1
    message = args.message if args.message is not None else sys.stdin.read()
    message = message.strip()
    if not message:
        print("empty message", file=sys.stderr)
        return 1
    sender = None
    if args.sender:
        sender = one("select id from users where lower(email) = lower(%s) or lower(name) = lower(%s)", (args.sender, args.sender))
        if not sender:
            print(f"no user {args.sender}", file=sys.stderr)
            return 1
    note_id = cat.send(user["id"], message, args.kind, sender["id"] if sender else None)
    print(f"cat #{note_id} on its way to {user['name']}; an open page shows it within 15 seconds")


def cmd_demo(args):
    company = one("select * from companies where lower(name) = lower(%s)", (args.company,))
    if not company:
        print(f"No company named {args.company}")
        return 1
    from datetime import date, datetime, timedelta
    import random
    drivers = []
    for name, phone in [("Ruslan Karimov", "+1 405 555 0142"), ("Jamie Ortega", "+1 918 555 0177"),
                        ("Bekzod Rasulov", "+1 405 555 0198")]:
        driver = insert(
            """insert into drivers (company_id, name, phone, license_number, license_state, license_expires, medical_expires, status)
               values (%s, %s, %s, %s, 'OK', %s, %s, 'active') returning *""",
            (company["id"], name, phone, f"D{random.randint(100000, 999999)}",
             date.today() + timedelta(days=random.randint(20, 400)),
             date.today() + timedelta(days=random.randint(10, 300))),
        )
        drivers.append(driver)
    specs = [
        ("214", "Freightliner", "Cascadia", 2021, 512340, "3AKJHHDR2MSMY1234"),
        ("218", "Volvo", "VNL 860", 2022, 341880, "4V4NC9EH8NN123456"),
        ("305", "Peterbilt", "579", 2020, 688120, "1XPBDP9X0LD654321"),
        ("312", "Kenworth", "T680", 2023, 145600, "1XKYDP9X4PJ987654"),
    ]
    for index, (unit, make, model, year, odo, vin) in enumerate(specs):
        truck = insert(
            """insert into trucks (company_id, unit_number, vin, make, model, year, status, odometer, odometer_at,
                 driver_id, annual_inspection_on, registration_expires, insurance_expires)
               values (%s, %s, %s, %s, %s, %s, 'active', %s, now(), %s, %s, %s, %s) returning *""",
            (company["id"], unit, vin, make, model, year, odo, drivers[index % len(drivers)]["id"],
             date.today() - timedelta(days=random.randint(30, 340)),
             date.today() + timedelta(days=random.randint(15, 300)),
             date.today() + timedelta(days=random.randint(40, 320))),
        )
        service_odo = odo - random.randint(4000, 26000)
        insert(
            """insert into maintenance_orders (company_id, truck_id, kind, status, performed_on, odometer, vendor, cost, description)
               values (%s, %s, 'oil', 'done', %s, %s, %s, %s, %s) returning id""",
            (company["id"], truck["id"], date.today() - timedelta(days=random.randint(20, 120)), service_odo,
             "TA Truck Service", round(random.uniform(320, 480), 2), "Oil and filter change, chassis lube"),
        )
        running = odo
        for week in range(6):
            gallons = round(random.uniform(110, 160), 2)
            price = round(random.uniform(3.35, 4.15), 3)
            running -= random.randint(700, 1100)
            insert(
                """insert into fuel_transactions (company_id, truck_id, driver_id, purchased_at, gallons,
                     price_per_gallon, total, odometer, location, state, card_last4)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id""",
                (company["id"], truck["id"], truck["driver_id"],
                 datetime.now() - timedelta(days=week * 7 + random.randint(0, 3)),
                 gallons, price, round(gallons * price, 2), running,
                 random.choice(["Love's, Oklahoma City", "Pilot, Amarillo", "TA, Little Rock", "Love's, Joplin"]),
                 random.choice(["OK", "TX", "AR", "MO"]), f"{random.randint(1000, 9999)}"),
            )
    breakdown = insert(
        """insert into breakdowns (company_id, truck_id, driver_id, occurred_at, status, severity, location, description, load_number)
           values (%s, (select id from trucks where company_id = %s and unit_number = '305'),
             (select id from drivers where company_id = %s limit 1), now() - interval '6 hours', 'in_shop', 'high',
             'I-40 mile marker 128, eastbound', 'Loss of power, check engine light, driver reports white smoke', 'L-88213')
           returning *""",
        (company["id"], company["id"], company["id"]),
    )
    execute(
        "insert into breakdown_updates (breakdown_id, company_id, note, status) values (%s, %s, %s, %s)",
        (breakdown["id"], company["id"], "Tow booked with Big Rig Recovery, ETA 45 minutes.", "towing"),
    )
    execute("update trucks set status = 'shop' where id = %s", (breakdown["truck_id"],))
    print(f"Demo data added to {company['name']}")
    return 0


def cmd_recalls(args):
    from app import recalls
    print(recalls.run(notify=not args.quiet))


def main():
    parser = argparse.ArgumentParser(description="Kaido fleet management")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate", help="apply db/schema.sql").set_defaults(func=cmd_migrate)
    recall_parser = sub.add_parser("recalls", help="check NHTSA recalls for every VIN")
    recall_parser.add_argument("--quiet", action="store_true")
    recall_parser.set_defaults(func=cmd_recalls)

    boot = sub.add_parser("bootstrap", help="create the first platform owner")
    boot.add_argument("--email", required=True)
    boot.add_argument("--name", required=True)
    boot.add_argument("--company", help="also create this company and make the owner an admin of it")
    boot.add_argument("--password")
    boot.add_argument("--force", action="store_true")
    boot.set_defaults(func=cmd_bootstrap)

    company = sub.add_parser("add-company", help="add a carrier")
    company.add_argument("--name", required=True)
    company.add_argument("--dot")
    company.add_argument("--house", action="store_true")
    company.set_defaults(func=cmd_company)

    user = sub.add_parser("add-user", help="create a user and attach them to a company")
    user.add_argument("--email", required=True)
    user.add_argument("--name", required=True)
    user.add_argument("--company")
    user.add_argument("--role", default="viewer")
    user.add_argument("--platform-role", dest="platform_role", default=None)
    user.add_argument("--telegram", type=int)
    user.add_argument("--password")
    user.set_defaults(func=cmd_user)

    reset = sub.add_parser("reset-password", help="set a new temporary password and send it to the user's Telegram")
    reset.add_argument("email")
    reset.set_defaults(func=cmd_reset_password)

    sync = sub.add_parser("sync", help="pull from Samsara")
    sync.add_argument("--company")
    sync.add_argument("--all", action="store_true")
    sync.set_defaults(func=cmd_sync)
    sub.add_parser("safety", help="pull Samsara safety events and speeding").set_defaults(func=cmd_safety)

    hconnect = sub.add_parser("horizon-connect", help="store Horizon ELD credentials for a company")
    hconnect.add_argument("--company", required=True)
    hconnect.add_argument("--user", required=True)
    hconnect.add_argument("--password", required=True)
    hconnect.add_argument("--company-key", dest="company_key")
    hconnect.set_defaults(func=cmd_horizon_connect)

    hsync = sub.add_parser("horizon-sync", help="pull drivers, vehicles and HOS from Horizon ELD")
    hsync.add_argument("--company")
    hsync.add_argument("--all", action="store_true")
    hsync.set_defaults(func=cmd_horizon_sync)

    sub.add_parser("google-usage", help="Google Maps calls today and this month").set_defaults(func=cmd_google_usage)

    spend = sub.add_parser("ai-spend", help="what the AI notes have cost so far")
    spend.add_argument("--days", type=int, default=14)
    spend.add_argument("--credit", type=float, default=5.0)
    spend.set_defaults(func=cmd_ai_spend)

    follow = sub.add_parser("followup", help="send due reminders, stop-lamp alerts and the daily follow-up")
    follow.add_argument("--show", metavar="COMPANY", help="print today's follow-up for a company without sending it")
    follow.add_argument("--send-now", dest="send_now", metavar="COMPANY", help="send today's follow-up for a company right away")
    follow.set_defaults(func=cmd_followup)

    sub.add_parser("telegram-bot", help="link Telegram accounts").set_defaults(func=cmd_telegram)
    hist = sub.add_parser("alerts-history", help="send past alerts into a linked alerts group")
    hist.add_argument("--chat", type=int, required=True)
    hist.set_defaults(func=cmd_alerts_history)
    sub.add_parser("pti-cleanup", help="delete PTI photos/videos past the FMCSA 3 months").set_defaults(func=cmd_pti_cleanup)
    details_parser = sub.add_parser("saved-shop-details", help="fill missing saved-shop addresses from OpenStreetMap")
    details_parser.add_argument("--limit", type=int, default=2000)
    details_parser.set_defaults(func=cmd_saved_shop_details)
    summary_parser = sub.add_parser("summary", help="send the twice-weekly summary to company admins")
    summary_parser.add_argument("--backup", nargs="*")
    summary_parser.set_defaults(func=cmd_summary)


    fdir = sub.add_parser("fuel-directory", help="load truck stops from OpenStreetMap, state by state")
    fdir.add_argument("--states", help="comma-separated, e.g. NV,AZ (default: all)")
    fdir.set_defaults(func=cmd_fuel_directory)
    fprep = sub.add_parser("fuel-prepare", help="match purchases to stations and find cheaper stops nearby")
    fprep.add_argument("--company")
    fprep.add_argument("--recheck", action="store_true")
    fprep.set_defaults(func=cmd_fuel_prepare)
    frun = sub.add_parser("fuel", help="send fuel stop suggestions to low trucks and match refuels")
    frun.add_argument("--force", action="store_true")
    frun.set_defaults(func=cmd_fuel)
    sub.add_parser("eia-prices", help="weekly regional diesel averages from the EIA").set_defaults(func=cmd_eia_prices)
    fbrand = sub.add_parser("brand-prices", help="today's pump prices from truck-stop brand websites")
    fbrand.add_argument("--brand", action="append", help="loves (default: every brand)")
    fbrand.add_argument("--states", help="comma-separated, e.g. TX,OK")
    fbrand.add_argument("--limit", type=int)
    fbrand.set_defaults(func=cmd_brand_prices)
    trip = sub.add_parser("trip", help="plan a load: route, fuel stops, hours, ETAs")
    trip.add_argument("--company", required=True)
    trip.add_argument("--truck", required=True, help="unit number, random (any truck live on Samsara) or nearest (closest live truck to the pickup)")
    trip.add_argument("--file", help="the load text (default: read from stdin)")
    trip.add_argument("--send", action="store_true", help="send the plan to the truck's Telegram group")
    trip.set_defaults(func=cmd_trip)
    fdemo = sub.add_parser("fuel-demo", help="placeholder fuel purchases marked demo, or --remove them")
    fdemo.add_argument("--company", required=True)
    fdemo.add_argument("--days", type=int, default=28)
    fdemo.add_argument("--remove", action="store_true")
    fdemo.set_defaults(func=cmd_fuel_demo)
    frep = sub.add_parser("fuel-report", help="weekly fuel reports for drivers and the office")
    frep.add_argument("--company")
    frep.add_argument("--dry-run", dest="dry_run", action="store_true")
    frep.add_argument("--force", action="store_true")
    frep.set_defaults(func=cmd_fuel_report)

    cat_parser = sub.add_parser("cat", help="send a note the cat brings to someone in the app")
    cat_parser.add_argument("--to", required=True, help="email or name")
    cat_parser.add_argument("--from", dest="sender", help="email or name shown as the sender in history")
    cat_parser.add_argument("--kind", choices=["note", "reminder"], default="note")
    cat_parser.add_argument("message", nargs="?", help="the text; read from stdin when left out")
    cat_parser.set_defaults(func=cmd_cat)

    demo = sub.add_parser("demo", help="add sample trucks, drivers, fuel and a breakdown")
    demo.add_argument("--company", required=True)
    demo.set_defaults(func=cmd_demo)

    args = parser.parse_args()
    from app import logs
    logs.setup(args.command)
    try:
        code = args.func(args) or 0
    except KeyboardInterrupt:
        code = 130
    except Exception:
        logs.get("manage").exception("manage.py %s failed", args.command)
        code = 1
    sys.exit(code)


if __name__ == "__main__":
    main()
