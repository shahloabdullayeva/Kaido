from flask import Blueprint, g, jsonify

from .. import cat
from ..auth import login_required

bp = Blueprint("cat", __name__)


@bp.get("/cat/pending")
@login_required
def pending():
    response = jsonify(name=g.session["name"], notes=cat.pending(g.session["user_id"]))
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.post("/cat/<int:note_id>/done")
@login_required
def done(note_id):
    cat.done(note_id, g.session["user_id"])
    return "", 204
