import requests

from .config import config

API = "https://api.telegram.org"


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
            print(f"[telegram] send failed: {data.get('description')}")
        return {"ok": bool(data.get("ok")), "reason": data.get("description")}
    except requests.RequestException as err:
        print(f"[telegram] send error: {err}")
        return {"ok": False, "reason": str(err)}


def get_updates(offset=None):
    if not enabled():
        return []
    params = {"timeout": 25}
    if offset:
        params["offset"] = offset
    response = requests.get(f"{API}/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates", params=params, timeout=35)
    data = response.json()
    return data.get("result", []) if data.get("ok") else []
