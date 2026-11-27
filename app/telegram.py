import json

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


def call(method, payload=None, files=None):
    if not enabled():
        print(f"[telegram:disabled] {method}")
        return {"ok": False, "reason": "no_token"}
    try:
        url = f"{API}/bot{config.TELEGRAM_BOT_TOKEN}/{method}"
        if files:
            data = {k: (v if isinstance(v, (str, int, float)) else json.dumps(v)) for k, v in (payload or {}).items()}
            response = requests.post(url, data=data, files=files, timeout=120)
        else:
            response = requests.post(url, json=payload or {}, timeout=10)
        data = response.json()
        if not data.get("ok"):
            log.warning("%s failed: %s", method, data.get("description"))
        result = data.get("result")
        return {"ok": bool(data.get("ok")), "reason": data.get("description"), "result": result,
                "message_id": result.get("message_id") if isinstance(result, dict) else None}
    except (requests.RequestException, ValueError) as err:
        reason = redact(str(err))
        log.warning("%s failed: %s", method, reason)
        return {"ok": False, "reason": reason}


def send_photo(chat_id, png, caption=None, **extra):
    if not chat_id:
        return {"ok": False, "reason": "no_chat_id"}
    payload = {"chat_id": chat_id, "parse_mode": "HTML", **extra}
    if caption:
        payload["caption"] = caption[:1024]
    return call("sendPhoto", payload, files={"photo": ("report.png", png, "image/png")})


def send_video(chat_id, video, caption=None, **extra):
    if not chat_id:
        return {"ok": False, "reason": "no_chat_id"}
    payload = {"chat_id": chat_id, "parse_mode": "HTML", "supports_streaming": "true", **extra}
    if caption:
        payload["caption"] = caption[:1024]
    return call("sendVideo", payload, files={"video": ("event.mp4", video, "video/mp4")})


def edit(chat_id, message_id, text, **extra):
    return call("editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": text,
                                    "parse_mode": "HTML", "disable_web_page_preview": True, **extra})


def answer(callback_id, text=None):
    return call("answerCallbackQuery", {"callback_query_id": callback_id, **({"text": text[:190]} if text else {})})
