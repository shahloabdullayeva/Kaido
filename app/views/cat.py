from flask import Blueprint, g

from .. import cat
from ..auth import login_required

bp = Blueprint("cat", __name__)


@bp.post("/cat/<int:note_id>/done")
@login_required
def done(note_id):
    cat.done(note_id, g.session["user_id"])
    return "", 204
