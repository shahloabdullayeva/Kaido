import functools

from flask import g, redirect, request, url_for

from .audit import audit, client_ip
from .config import config
from .db import execute, insert, one
from .security import (
    burn_password_time, csrf_token, hash_password, random_code, random_token,
    sha256, verify_password,
)
from .telegram import send as send_telegram

SESSION_COOKIE = "fleet_sid"
PENDING_COOKIE = "fleet_pending"
NEXT_COOKIE = "fleet_next"
ANON_CSRF_COOKIE = "fleet_csrf"


def user_agent():
    return (request.headers.get("User-Agent") or "")[:300]


def device_label():
    ua = request.headers.get("User-Agent") or ""
    if "Windows" in ua:
        system = "Windows"
    elif "Android" in ua:
        system = "Android"
    elif "iPhone" in ua or "iPad" in ua:
        system = "iOS"
    elif "Mac OS X" in ua:
        system = "macOS"
    elif "Linux" in ua:
        system = "Linux"
    else:
        system = "Unknown OS"
    if "Edg/" in ua:
        browser = "Edge"
    elif "OPR/" in ua:
        browser = "Opera"
    elif "Firefox/" in ua:
        browser = "Firefox"
    elif "Chrome/" in ua:
        browser = "Chrome"
    elif "Safari/" in ua:
        browser = "Safari"
    else:
        browser = "Unknown browser"
    return f"{browser} on {system}"


def password_problem(password):
    if not isinstance(password, str) or len(password) < 12:
        return "Password must be at least 12 characters."
    if len(password) > 200:
        return "Password is too long."
    if not any(c.islower() for c in password) or not any(c.isupper() for c in password) or not any(c.isdigit() for c in password):
        return "Password needs an uppercase letter, a lowercase letter and a digit."
    return None


def throttle(key, limit, window_minutes, block_minutes):
    row = insert(
        """insert into throttle (key, count, first_at, last_at)
           values (%s, 1, now(), now())
           on conflict (key) do update set
             count = case
               when throttle.blocked_until is not null and throttle.blocked_until > now() then throttle.count
               when throttle.first_at < now() - make_interval(mins => %s) then 1
               else throttle.count + 1 end,
             first_at = case when throttle.first_at < now() - make_interval(mins => %s) then now() else throttle.first_at end,
             last_at = now(),
             blocked_until = case
               when throttle.blocked_until is not null and throttle.blocked_until > now() then throttle.blocked_until
               else null end
           returning *""",
        (key, window_minutes, window_minutes),
    )
    from datetime import datetime, timezone as tz
    now = datetime.now(tz.utc)
    if row["blocked_until"] and row["blocked_until"] > now:
        return True, row["blocked_until"]
    if row["count"] >= limit:
        blocked = insert(
            """update throttle set blocked_until = now() + make_interval(mins => %s), count = 0, first_at = now()
               where key = %s returning blocked_until""",
            (block_minutes, key),
        )
        return True, blocked["blocked_until"]
    return False, None


def throttle_status(key):
    from datetime import datetime, timezone as tz
    row = one("select blocked_until from throttle where key = %s", (key,))
    if row and row["blocked_until"] and row["blocked_until"] > datetime.now(tz.utc):
        return True, row["blocked_until"]
    return False, None


def throttle_clear(key):
    execute("delete from throttle where key = %s", (key,))


def find_user_by_email(email):
    return one("select * from users where lower(email) = lower(%s)", ((email or "").strip(),))


def user_locked(user):
    from datetime import datetime, timezone as tz
    return bool(user["locked_until"] and user["locked_until"] > datetime.now(tz.utc))


def register_failed_login(user):
    return insert(
        """update users set failed_logins = failed_logins + 1,
             locked_until = case when failed_logins + 1 >= %s then now() + make_interval(mins => %s) else locked_until end,
             updated_at = now()
           where id = %s returning failed_logins, locked_until""",
        (config.MAX_PASSWORD_ATTEMPTS, config.LOCKOUT_MINUTES, user["id"]),
    )


def clear_failed_logins(user_id):
    execute("update users set failed_logins = 0, locked_until = null, updated_at = now() where id = %s", (user_id,))


def create_session(user, device_id=None, company_id=None):
    token = random_token(32)
    session = insert(
        """insert into sessions (user_id, device_id, company_id, token_hash, csrf_secret, ip, user_agent, expires_at, absolute_expires_at)
           values (%s, %s, %s, %s, %s, %s, %s, now() + make_interval(hours => %s), now() + make_interval(hours => %s))
           returning *""",
        (
            user["id"], device_id, company_id, sha256(token), random_token(24),
            client_ip(), user_agent(), config.SESSION_IDLE_HOURS, config.SESSION_MAX_HOURS,
        ),
    )
    execute("update users set last_login_at = now() where id = %s", (user["id"],))
    return session, token


def load_session(token):
    if not token:
        return None
    row = one(
        """select s.*, u.email, u.name, u.platform_role, u.status, u.telegram_chat_id, u.can_add_companies,
                  u.theme, u.default_company_id, u.can_see_site
           from sessions s join users u on u.id = s.user_id
           where s.token_hash = %s and s.revoked_at is null
             and s.expires_at > now() and s.absolute_expires_at > now()""",
        (sha256(token),),
    )
    if not row or row["status"] != "active":
        return None
    execute(
        """update sessions set last_seen_at = now(),
             expires_at = least(now() + make_interval(hours => %s), absolute_expires_at), ip = %s
           where id = %s""",
        (config.SESSION_IDLE_HOURS, client_ip(), row["id"]),
    )
    row["csrf"] = csrf_token(row["csrf_secret"])
    return row


def revoke_session_token(token):
    if token:
        execute("update sessions set revoked_at = now() where token_hash = %s", (sha256(token),))


def revoke_all_sessions(user_id):
    execute("update sessions set revoked_at = now() where user_id = %s and revoked_at is null", (user_id,))


def create_challenge(user):
    execute(
        "update login_challenges set consumed_at = now() where user_id = %s and consumed_at is null and denied_at is null",
        (user["id"],),
    )
    code = random_code()
    handle = random_token(24)
    challenge = insert(
        """insert into login_challenges (user_id, code_hash, handle, ip, user_agent, expires_at)
           values (%s, %s, %s, %s, %s, now() + make_interval(mins => %s)) returning *""",
        (user["id"], sha256(code), handle, client_ip(), user_agent(), config.CODE_TTL_MINUTES),
    )
    deny_url = f"{config.APP_URL}/login/deny/{handle}"
    text = "\n".join([
        f"<b>Kaido sign-in code: {code}</b>",
        "",
        f"Device: {device_label()}",
        f"IP: {client_ip()}",
        f"Valid for {config.CODE_TTL_MINUTES} minutes, one use only.",
        "",
        f"Not you? Block it: {deny_url}",
    ])
    result = send_telegram(user["telegram_chat_id"], text)
    if not result["ok"] and config.ENV != "production":
        print(f"[dev] login code for {user['email']}: {code} (deny: {deny_url})")
    return challenge, result["ok"]


def load_challenge(handle):
    if not handle:
        return None
    return one(
        """select c.*, u.email, u.name, u.platform_role, u.telegram_chat_id, u.status
           from login_challenges c join users u on u.id = c.user_id
           where c.handle = %s and c.consumed_at is null and c.denied_at is null and c.expires_at > now()""",
        (handle,),
    )


def consume_challenge(challenge_id):
    execute("update login_challenges set consumed_at = now() where id = %s", (challenge_id,))


def bump_challenge_attempts(challenge_id):
    row = insert("update login_challenges set attempts = attempts + 1 where id = %s returning attempts", (challenge_id,))
    return row["attempts"] if row else 0


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not getattr(g, "session", None):
            return redirect(url_for("auth.login", next=request.full_path if request.query_string else request.path))
        return view(*args, **kwargs)
    return wrapped


def notify_login(user, method, extra=None):
    from datetime import datetime
    lines = [
        "<b>Kaido sign-in</b>",
        f"Account: {user['email']}",
        f"Device: {device_label()}",
        f"IP: {client_ip()}",
        f"Method: {method}",
        f"Time: {datetime.now().strftime('%d %b %Y %H:%M')}",
    ]
    if extra:
        lines.append(extra)
    send_telegram(user["telegram_chat_id"], "\n".join(lines))
