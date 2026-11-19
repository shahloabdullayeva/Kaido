from flask import Blueprint, abort, render_template, request

from .. import learn
from ..auth import login_required

bp = Blueprint("learn", __name__)


@bp.get("/learn")
@login_required
def index():
    query = (request.args.get("q") or "").strip()[:100]
    return render_template("learn/index.html", title="Learn", active="/learn", topics=learn.topics(), query=query,
                           hits=learn.search(query) if query else None)


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
