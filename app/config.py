import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env_file():
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_env_file()


def _int(name, default):
    raw = os.environ.get(name, "")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


class Config:
    ENV = os.environ.get("APP_ENV", "development")
    PORT = _int("PORT", 8790)
    HOST = os.environ.get("HOST", "127.0.0.1")
    APP_URL = os.environ.get("APP_URL", "http://localhost:8790")
    DATABASE_URL = os.environ.get("DATABASE_URL", "")
    SECRET_KEY = os.environ.get("SECRET_KEY", "")
    ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "")
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    TRUST_DAYS = _int("TRUST_DAYS", 30)
    CODE_TTL_MINUTES = _int("CODE_TTL_MINUTES", 10)
    SESSION_IDLE_HOURS = _int("SESSION_IDLE_HOURS", 12)
    SESSION_MAX_HOURS = _int("SESSION_MAX_HOURS", 168)
    MAX_PASSWORD_ATTEMPTS = _int("MAX_PASSWORD_ATTEMPTS", 5)
    MAX_CODE_ATTEMPTS = _int("MAX_CODE_ATTEMPTS", 5)
    LOCKOUT_MINUTES = _int("LOCKOUT_MINUTES", 15)
    TIMEZONE = os.environ.get("TIMEZONE", "America/Chicago")
    BEHIND_PROXY = os.environ.get("BEHIND_PROXY", "false").lower() == "true"
    SAMSARA_BASE_URL = os.environ.get("SAMSARA_BASE_URL", "https://api.samsara.com")


config = Config()
IS_PROD = config.ENV == "production"

if not config.DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")
if len(config.SECRET_KEY) < 32:
    raise RuntimeError("SECRET_KEY must be at least 32 characters")
if len(config.ENCRYPTION_KEY) < 32:
    raise RuntimeError("ENCRYPTION_KEY must be at least 32 characters")
