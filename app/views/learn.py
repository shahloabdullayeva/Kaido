from pathlib import Path

from flask import Blueprint, abort, render_template, request, send_file

from .. import learn
from ..auth import login_required

bp = Blueprint("learn", __name__)
MANUAL = Path(__file__).resolve().parents[2] / "uploads" / "learn" / "Fleet_From_Scratch.pdf"


@bp.get("/learn")
@login_required
def index():
    query = (request.args.get("q") or "").strip()[:100]
    return render_template("learn/index.html", title="Learn", active="/learn", topics=learn.topics(), groups=learn.grouped(), query=query, has_manual=MANUAL.exists(),
                           hits=learn.search(query) if query else None)


@bp.get("/learn/fleet-from-scratch.pdf")
@login_required
def manual():
    if not MANUAL.exists():
        abort(404)
    return send_file(MANUAL, mimetype="application/pdf", download_name="Fleet_From_Scratch.pdf")


@bp.get("/learn/<name>")
@login_required
def show(name):
    item = learn.topic(name)
    if not item:
        abort(404)
    items = learn.topics()
    place = items.index(item)
    return render_template("learn/show.html", title=item["title"], active="/learn", item=item, topics=items,
                           previous=items[place - 1] if place else None,
                           following=items[place + 1] if place + 1 < len(items) else None)
