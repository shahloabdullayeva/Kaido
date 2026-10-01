import json

from flask import g, request

from .db import execute
from .logs import get


def client_ip():
    if not request:
        return None
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return (request.remote_addr or "").replace("::ffff:", "")


def audit(action, entity=None, entity_id=None, detail=None, company_id=None, user_id=None, actor=None):
    session = getattr(g, "session", None)
    try:
        execute(
            """insert into audit_log (company_id, user_id, actor, action, entity, entity_id, detail, ip)
               values (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                company_id if company_id is not None else (session["company_id"] if session else None),
                user_id if user_id is not None else (session["user_id"] if session else None),
                actor or (session["email"] if session else "anonymous"),
                action,
                entity,
                None if entity_id is None else str(entity_id),
                json.dumps(detail) if detail else None,
                client_ip(),
            ),
        )
    except Exception as err:
        get("audit").warning("could not write audit entry %s: %s", action, err)
