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
    reminded = reminders.send_due()
    alerted = followup.send_fault_alerts()
    sent = followup.run()
    from app import pti_driver
    drivers = pti_driver.run()
    if reminded or alerted or sent or drivers:
        print(f"reminders {reminded}, fault alerts {alerted}, follow-ups {sent}, driver PTI messages {drivers}")
    return 0


def handle_group_update(update, send):
    from app import pti_driver
    member = update.get("my_chat_member")
    if member:
        status = (member.get("new_chat_member") or {}).get("status")
        chat = member.get("chat") or {}
        if status in ("left", "kicked") and chat.get("id"):
            pti_driver.forget_group(chat["id"])
        return True
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    if chat.get("type") not in ("group", "supergroup"):
        return False
    if message.get("migrate_to_chat_id"):
        pti_driver.move_group(chat["id"], message["migrate_to_chat_id"])
        return True
    parts = (message.get("text") or "").split()
    if not parts or parts[0].split("@")[0] != "/drivers":
        return True
    if len(parts) < 2:
        send(chat["id"], "Send /drivers followed by the code from the Company page in Kaido.")
        return True
    company = pti_driver.claim_group(parts[1], chat)
    if not company:
        send(chat["id"], "That code is not valid. Copy it again from the Company page in Kaido.")
        return True
    send(chat["id"], f"Connected to {company['name']}. PTI reminders for the drivers will come to this group.")
    return True


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


def main():
    parser = argparse.ArgumentParser(description="Kaido fleet management")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate", help="apply db/schema.sql").set_defaults(func=cmd_migrate)

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

    sync = sub.add_parser("sync", help="pull from Samsara")
    sync.add_argument("--company")
    sync.add_argument("--all", action="store_true")
    sync.set_defaults(func=cmd_sync)

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
        logs.get("manage").exception("manage.py %s failed", " ".join(sys.argv[1:]))
        code = 1
    sys.exit(code)


if __name__ == "__main__":
    main()
