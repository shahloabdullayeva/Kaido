from flask import Blueprint, g, jsonify

from .. import cat
from ..auth import login_required

bp = Blueprint("cat", __name__)


@bp.get("/cat/pending")
@login_required
def pending():
    user_id = g.session["user_id"]
    response = jsonify(
        version=cat.VERSION,
        name=g.session["name"],
        notes=cat.pending(user_id),
        history=[
            {"id": note["id"], "kind": note["kind"], "message": note["message"], "sender": note["sender"],
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
