import requests

from .config import config
from .logs import get, redact

API = "https://api.telegram.org"
log = get("telegram")


class TelegramDown(Exception):
    pass


def enabled():
    return bool(config.TELEGRAM_BOT_TOKEN)


def send(chat_id, text, **extra):
    if not chat_id:
        return {"ok": False, "reason": "no_chat_id"}
    if not enabled():
        flat = text.replace("\n", " | ")
        print(f"[telegram:disabled] to {chat_id}: {flat}")
        return {"ok": False, "reason": "no_token"}
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    payload.update(extra)
    try:
        response = requests.post(
            f"{API}/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage", json=payload, timeout=10
        )
        data = response.json()
        if not data.get("ok"):
            log.warning("send to %s failed: %s", chat_id, data.get("description"))
        return {"ok": bool(data.get("ok")), "reason": data.get("description"),
                "message_id": (data.get("result") or {}).get("message_id")}
    except (requests.RequestException, ValueError) as err:
        reason = redact(str(err))
        log.warning("send to %s failed: %s", chat_id, reason)
        return {"ok": False, "reason": reason}


def get_updates(offset=None):
    if not enabled():
        return []
    params = {"timeout": 25}
    if offset:
        params["offset"] = offset
    try:
        response = requests.get(f"{API}/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates", params=params, timeout=35)
        data = response.json()
    except (requests.RequestException, ValueError) as err:
        # The exception text carries the URL, and the URL carries the bot token.
        raise TelegramDown(redact(str(err))) from None
    if not data.get("ok"):
        raise TelegramDown(data.get("description") or f"HTTP {response.status_code}")
    return data.get("result", [])
