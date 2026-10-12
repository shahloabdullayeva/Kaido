from flask import Blueprint, g, jsonify, redirect

from .. import cat
from ..auth import login_required
from ..db import execute

bp = Blueprint("cat", __name__)


@bp.get("/cat/pending")
@login_required
def pending():
    user_id = g.session["user_id"]
    response = jsonify(
        version=cat.VERSION,
        name=g.session["name"],
        notes=[dict(note, href=f"/cat/{note['id']}/open" if note["href"] else None) for note in cat.pending(user_id)],
        history=[
            {"id": note["id"], "kind": note["kind"], "message": note["message"], "sender": note["sender"], "href": f"/cat/{note['id']}/open" if note["href"] else None,
             "when": note["created_at"].isoformat()}
            for note in cat.history(user_id)
        ],
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.post("/cat/done-all")
@login_required
def done_all():
    cat.done_all(g.session["user_id"])
    return "", 204


@bp.post("/cat/<int:note_id>/done")
@login_required
def done(note_id):
    cat.done(note_id, g.session["user_id"])
    return "", 204


@bp.get("/cat/<int:note_id>/open")
@login_required
def open_note(note_id):
    note = cat.target(note_id, g.session["user_id"])
    if not note or not note["href"].startswith("/") or note["href"].startswith("//"):
        return redirect("/")
    if note["company_id"] and any(company["id"] == note["company_id"] for company in g.companies):
        execute("update sessions set company_id = %s where id = %s", (note["company_id"], g.session["id"]))
    return redirect(note["href"])
