import hashlib
from pathlib import Path

from .db import execute, insert, rows


def _version():
    root = Path(__file__).parent
    digest = hashlib.sha1()
    for path in sorted([*root.glob("static/*.*"), *root.glob("templates/*.html")]):
        digest.update(f"{path.name}:{path.stat().st_mtime_ns}".encode())
    return digest.hexdigest()[:12]


VERSION = _version()


def pending(user_id):
    notes = rows(
        """select id, kind, message from cat_notes
           where user_id = %s and done_at is null
           order by created_at""",
        (user_id,),
    )
    if notes:
        execute(
            "update cat_notes set shown_at = coalesce(shown_at, now()) where id = any(%s)",
            ([note["id"] for note in notes],),
        )
    return notes


def send(user_id, message, kind="note", sent_by=None):
    return insert(
        "insert into cat_notes (user_id, kind, message, sent_by) values (%s, %s, %s, %s) returning id",
        (user_id, kind, message, sent_by),
    )["id"]


def done(note_id, user_id):
    return execute(
        "update cat_notes set done_at = now() where id = %s and user_id = %s and done_at is null",
        (note_id, user_id),
    )


def history(user_id, limit=20):
    return rows(
        """select n.id, n.kind, n.message, n.created_at, n.done_at, u.name as sender
           from cat_notes n left join users u on u.id = n.sent_by
           where n.user_id = %s and n.done_at is not null
           order by n.created_at desc limit %s""",
        (user_id, limit),
    )
