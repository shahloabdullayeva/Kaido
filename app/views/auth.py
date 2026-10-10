import hmac
from datetime import datetime, timezone

from flask import Blueprint, Response, abort, flash, g, redirect, render_template, request, url_for

from .. import captcha
from ..audit import audit, client_ip
from ..auth import (
    ANON_CSRF_COOKIE, NEXT_COOKIE, PENDING_COOKIE, SESSION_COOKIE,
    bump_challenge_attempts, clear_failed_logins, consume_challenge, create_challenge,
    create_session, device_label, find_user_by_email, load_challenge,
    login_required, notify_login, password_problem, register_failed_login,
    revoke_all_sessions, revoke_session_token, throttle,
    throttle_clear, throttle_status, user_locked,
)
from ..config import IS_PROD, config
from ..db import execute, insert, one, rows
from ..security import burn_password_time, hash_password, random_code, sha256, verify_password
from ..telegram import send as send_telegram
from ..tenancy import default_company_id

bp = Blueprint("auth", __name__)

GENERIC_FAIL = "Email or password is incorrect."


def safe_next(value):
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


def minutes_until(until):
    delta = until - datetime.now(timezone.utc)
    return max(1, int(delta.total_seconds() // 60) + 1)


def set_cookie(response, name, value, max_age):
    response.set_cookie(name, value, max_age=max_age, httponly=True, samesite="Lax", secure=IS_PROD, path="/")
    return response


def masked_telegram(user):
    if user.get("telegram_username"):
        return f"@{user['telegram_username']}"
    if user.get("telegram_chat_id"):
        return f"Telegram id ending {str(user['telegram_chat_id'])[-4:]}"
    return "your linked Telegram"


@bp.get("/login")
def login():
    if g.session:
        return redirect("/")
    errors = {
        "locked": "Too many attempts. Try again shortly.",
        "expired": "That sign-in attempt expired. Start again.",
        "attempts": "Too many wrong codes. Start again.",
        "denied": "That sign-in was blocked from Telegram.",
    }
    return render_template(
        "auth/login.html",
        title="Sign in",
        error=errors.get(request.args.get("error")),
        notice="You are signed out." if request.args.get("notice") == "signedout" else None,
        next=safe_next(request.args.get("next")),
        email="",
        captcha=captcha.create(),
    )


@bp.get("/login/captcha/<handle>.png")
def captcha_image(handle):
    data = captcha.image(handle)
    if not data:
        abort(404)
    response = Response(data, mimetype="image/png")
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.post("/login")
def login_submit():
    if g.session:
        return redirect("/")
    email = (request.form.get("email") or "").strip()[:200]
    password = request.form.get("password") or ""
    next_url = safe_next(request.form.get("next"))
    ip = client_ip()

    ip_key = f"login:ip:{ip}"
    user_key = f"login:email:{email.lower()}"

    blocked, until = throttle_status(ip_key)
    if blocked:
        audit("login.throttled", "user", None, {"email": email})
        return render_template(
            "auth/login.html", title="Slow down",
            error=f"Too many attempts from this network. Try again in {minutes_until(until)} minutes.",
            next=next_url, email=email, captcha=captcha.create(),
        ), 429

    def fail(message, status=401):
        return render_template("auth/login.html", title="Sign in", error=message, next=next_url, email=email,
                               captcha=captcha.create()), status

    throttle(ip_key, 20, 15, config.LOCKOUT_MINUTES)
    if not captcha.solve(request.form.get("captcha"), request.form.get("captcha_answer")):
        audit("login.bad_captcha", "user", None, {"email": email})
        return fail("The characters did not match the picture. Try this new one.", 400)

    user = find_user_by_email(email)
    if not user:
        burn_password_time()
        throttle(user_key, config.MAX_PASSWORD_ATTEMPTS, 15, config.LOCKOUT_MINUTES)
        audit("login.unknown_email", "user", None, {"email": email})
        return fail(GENERIC_FAIL)

    if user_locked(user):
        audit("login.locked", "user", user["id"], None, company_id=default_company_id(user["id"]), user_id=user["id"], actor=user["email"])
        return fail(f"Account temporarily locked. Try again in {minutes_until(user['locked_until'])} minutes.")

    if not verify_password(password, user["password_hash"]):
        state = register_failed_login(user)
        throttle(user_key, config.MAX_PASSWORD_ATTEMPTS, 15, config.LOCKOUT_MINUTES)
        audit("login.bad_password", "user", user["id"], {"attempts": state["failed_logins"]},
              company_id=default_company_id(user["id"]), user_id=user["id"], actor=user["email"])
        if state["locked_until"] and state["locked_until"] > datetime.now(timezone.utc):
            send_telegram(user["telegram_chat_id"], "\n".join([
                "<b>Kaido: account locked</b>",
                f"{config.MAX_PASSWORD_ATTEMPTS} wrong passwords for {user['email']}.",
                f"Locked for {config.LOCKOUT_MINUTES} minutes.",
                f"Last attempt from {ip} ({device_label()}).",
            ]))
        return fail(GENERIC_FAIL)

    if user["status"] != "active":
        audit("login.disabled", "user", user["id"], None, company_id=default_company_id(user["id"]),
              user_id=user["id"], actor=user["email"])
        return fail("This account is disabled. Contact an administrator.")

    clear_failed_logins(user["id"])
    throttle_clear(user_key)

    if not user["telegram_chat_id"] and config.ENV == "production":
        audit("login.no_telegram", "user", user["id"], None, company_id=default_company_id(user["id"]),
              user_id=user["id"], actor=user["email"])
        return fail("Your Telegram is not linked yet, so a code cannot be sent. Ask an administrator to finish setup.")

    challenge, delivered = create_challenge(user)
    audit("login.code_sent", "challenge", challenge["id"], {"delivered": delivered},
          company_id=default_company_id(user["id"]), user_id=user["id"], actor=user["email"])
    response = redirect("/login/verify")
    set_cookie(response, PENDING_COOKIE, challenge["handle"], config.CODE_TTL_MINUTES * 60)
    set_cookie(response, NEXT_COOKIE, next_url, config.CODE_TTL_MINUTES * 60)
    return response


@bp.get("/login/verify")
def verify():
    challenge = load_challenge(request.cookies.get(PENDING_COOKIE))
    if not challenge:
        return redirect("/login?error=expired")
    return render_template(
        "auth/verify.html",
        title="Enter code",
        error="That code is not right. Check the newest message." if request.args.get("error") == "code" else None,
        notice=None if challenge["telegram_chat_id"] else "Telegram is not linked for this account: the code is in the server log (development only).",
        destination=masked_telegram(challenge),
    )


@bp.post("/login/verify")
def verify_submit():
    handle = request.cookies.get(PENDING_COOKIE)
    challenge = load_challenge(handle)
    if not challenge:
        return redirect("/login?error=expired")
    code = (request.form.get("code") or "").strip()

    blocked, _ = throttle(f"code:{handle}", config.MAX_CODE_ATTEMPTS, config.CODE_TTL_MINUTES, config.LOCKOUT_MINUTES)
    if blocked:
        consume_challenge(challenge["id"])
        audit("login.code_blocked", "challenge", challenge["id"], None,
              company_id=default_company_id(challenge["user_id"]), user_id=challenge["user_id"], actor=challenge["email"])
        response = redirect("/login?error=attempts")
        response.delete_cookie(PENDING_COOKIE, path="/")
        return response

    if not hmac.compare_digest(sha256(code), bytes(challenge["code_hash"])):
        attempts = bump_challenge_attempts(challenge["id"])
        audit("login.code_wrong", "challenge", challenge["id"], {"attempts": attempts},
              company_id=default_company_id(challenge["user_id"]), user_id=challenge["user_id"], actor=challenge["email"])
        if attempts >= config.MAX_CODE_ATTEMPTS:
            consume_challenge(challenge["id"])
            response = redirect("/login?error=attempts")
            response.delete_cookie(PENDING_COOKIE, path="/")
            return response
        return redirect("/login/verify?error=code")

    consume_challenge(challenge["id"])
    throttle_clear(f"code:{handle}")
    user = one("select * from users where id = %s", (challenge["user_id"],))
    if not user or user["status"] != "active":
        return redirect("/login?error=expired")

    session, token = create_session(user, None, default_company_id(user["id"]))
    audit("login.success", "session", session["id"], {"method": "telegram_code"},
          company_id=session["company_id"], user_id=user["id"], actor=user["email"])
    send_telegram(user["telegram_chat_id"], "\n".join([
        "<b>Kaido sign-in confirmed</b>",
        f"{device_label()} from {client_ip()}",
        "Not you? Change your password now.",
    ]))

    response = redirect(safe_next(request.cookies.get(NEXT_COOKIE)))
    set_cookie(response, SESSION_COOKIE, token, config.SESSION_MAX_HOURS * 3600)
    response.delete_cookie(PENDING_COOKIE, path="/")
    response.delete_cookie(NEXT_COOKIE, path="/")
    return response


@bp.post("/login/resend")
def resend():
    handle = request.cookies.get(PENDING_COOKIE)
    challenge = load_challenge(handle)
    if not challenge:
        return redirect("/login?error=expired")
    blocked, _ = throttle(f"resend:{challenge['user_id']}", 3, 10, 10)
    if blocked:
        return redirect("/login/verify")
    user = one("select * from users where id = %s", (challenge["user_id"],))
    fresh, _delivered = create_challenge(user)
    audit("login.code_resent", "challenge", fresh["id"], None,
          company_id=default_company_id(user["id"]), user_id=user["id"], actor=user["email"])
    response = redirect("/login/verify")
    return set_cookie(response, PENDING_COOKIE, fresh["handle"], config.CODE_TTL_MINUTES * 60)


@bp.get("/login/deny/<handle>")
def deny(handle):
    return render_template("auth/deny.html", title="Block this sign-in", handle=handle,
                           lockout=config.LOCKOUT_MINUTES)


@bp.post("/login/deny/<handle>")
def deny_submit(handle):
    challenge = load_challenge(handle)
    if not challenge:
        return render_template("auth/blocked.html", title="Nothing to block",
                               notice="That request already expired. Nothing is pending.")
    execute("update login_challenges set denied_at = now() where id = %s", (challenge["id"],))
    execute(
        "update users set locked_until = now() + make_interval(mins => %s), failed_logins = 0 where id = %s",
        (config.LOCKOUT_MINUTES, challenge["user_id"]),
    )
    revoke_all_sessions(challenge["user_id"])
    audit("login.denied", "challenge", challenge["id"], {"by": "telegram_link"},
          company_id=default_company_id(challenge["user_id"]), user_id=challenge["user_id"], actor=challenge["email"])
    send_telegram(challenge["telegram_chat_id"], "\n".join([
        "<b>Sign-in blocked</b>",
        "Every session for your account was signed out.",
        "Change your password as soon as you can.",
    ]))
    return render_template("auth/blocked.html", title="Blocked",
                           notice="Blocked. Every session was signed out. Change your password next.")


@bp.post("/logout")
def logout():
    if g.session:
        audit("logout", "session", g.session["id"])
    revoke_session_token(request.cookies.get(SESSION_COOKIE))
    response = redirect("/login?notice=signedout")
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@bp.get("/account")
@login_required
def account():
    user = one("select * from users where id = %s", (g.session["user_id"],))
    sessions = rows(
        "select * from sessions where user_id = %s and revoked_at is null and expires_at > now() order by last_seen_at desc",
        (user["id"],),
    )
    pending_link = one(
        "select * from telegram_links where user_id = %s and used_at is null and expires_at > now() order by id desc limit 1",
        (user["id"],),
    )
    return render_template(
        "auth/account.html", title="Account", active="/account", user=user,
        sessions=sessions, pending_link=pending_link, masked=masked_telegram(user),
    )


@bp.post("/account/password")
@login_required
def change_password():
    user = one("select * from users where id = %s", (g.session["user_id"],))
    blocked, _ = throttle(f"pwchange:{user['id']}", 5, 15, 15)
    if blocked:
        flash("Too many attempts. Try again later.", "bad")
        return redirect("/account")
    if not verify_password(request.form.get("current") or "", user["password_hash"]):
        audit("password.bad_current", "user", user["id"])
        flash("Current password is incorrect.", "bad")
        return redirect("/account")
    new_password = request.form.get("next") or ""
    if new_password != (request.form.get("confirm") or ""):
        flash("The new passwords do not match.", "bad")
        return redirect("/account")
    problem = password_problem(new_password)
    if problem:
        flash(problem, "bad")
        return redirect("/account")
    execute("update users set password_hash = %s, updated_at = now() where id = %s", (hash_password(new_password), user["id"]))
    execute("update sessions set revoked_at = now() where user_id = %s and id <> %s and revoked_at is null", (user["id"], g.session["id"]))
    audit("password.changed", "user", user["id"])
    send_telegram(user["telegram_chat_id"], "\n".join([
        "<b>Kaido password changed</b>",
        f"From {device_label()} at {client_ip()}.",
        "Not you? Use the block link or call an admin.",
    ]))
    flash("Password changed. Other sessions were signed out.", "ok")
    return redirect("/account")


@bp.post("/account/telegram/code")
@login_required
def telegram_code():
    code = random_code()
    execute("update telegram_links set used_at = now() where user_id = %s and used_at is null", (g.session["user_id"],))
    execute(
        "insert into telegram_links (user_id, code, expires_at) values (%s, %s, now() + interval '30 minutes')",
        (g.session["user_id"], code),
    )
    audit("telegram.link_code", "user", g.session["user_id"])
    flash("Send the code to the bot within 30 minutes.", "info")
    return redirect("/account")


@bp.post("/account/telegram/unlink")
@login_required
def telegram_unlink():
    execute(
        "update users set telegram_chat_id = null, telegram_username = null, updated_at = now() where id = %s",
        (g.session["user_id"],),
    )
    audit("telegram.unlinked", "user", g.session["user_id"])
    flash("Telegram unlinked. Link it again before you sign out, or you cannot sign back in.", "warn")
    return redirect("/account")


@bp.post("/account/sessions/<int:session_id>/revoke")
@login_required
def revoke_one_session(session_id):
    execute("update sessions set revoked_at = now() where id = %s and user_id = %s", (session_id, g.session["user_id"]))
    audit("session.revoked", "session", session_id)
    flash("Session ended.", "ok")
    return redirect("/account")
