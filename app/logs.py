import logging
import re
import warnings
from logging.handlers import WatchedFileHandler

from .config import ROOT

ERROR_LOG = ROOT / "logs" / "errors.log"

SECRETS = [
    (re.compile(r"/bot\d+:[A-Za-z0-9_-]+"), "/bot<token>"),
    (re.compile(r"([?&](?:key|token|api_key)=)[^&\s\"']+"), r"\1<redacted>"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1<redacted>"),
    (re.compile(r"(X-Goog-Api-Key['\"]?:\s*['\"]?)[A-Za-z0-9_-]+"), r"\1<redacted>"),
]


def redact(text):
    for pattern, replacement in SECRETS:
        text = pattern.sub(replacement, text)
    return text


class Redacting(logging.Formatter):
    def format(self, record):
        return redact(super().format(record))


_ready = False


def setup(process):
    """Send WARNING and above from every part of Kaido to logs/errors.log, secrets stripped."""
    global _ready
    if _ready:
        return
    _ready = True
    warnings.filterwarnings("ignore", message="Workbook contains no default style", module="openpyxl")
    ERROR_LOG.parent.mkdir(exist_ok=True)
    handler = WatchedFileHandler(ERROR_LOG, encoding="utf-8")
    handler.setLevel(logging.WARNING)
    handler.setFormatter(Redacting(f"%(asctime)s %(levelname)s [{process}] %(name)s: %(message)s",
                                   "%Y-%m-%d %H:%M:%S%z"))
    root = logging.getLogger()
    root.addHandler(handler)
    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)
    stream = logging.StreamHandler()
    stream.setLevel(logging.WARNING)
    stream.setFormatter(Redacting("%(levelname)s %(name)s: %(message)s"))
    root.addHandler(stream)


def get(name):
    return logging.getLogger(name)
