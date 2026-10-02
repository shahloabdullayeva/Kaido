from .db import execute, insert, one


def pending(user_id):
    note = one(
        """select id, kind, message from cat_notes
           where user_id = %s and done_at is null
           order by created_at limit 1""",
        (user_id,),
    )
    if note:
        execute("update cat_notes set shown_at = coalesce(shown_at, now()) where id = %s", (note["id"],))
    return note


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
