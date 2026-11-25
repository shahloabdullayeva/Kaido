from flask import Blueprint, g, jsonify, redirect, render_template, request

from .. import search
from ..auth import login_required
from ..tenancy import company_required

bp = Blueprint("search", __name__)


@bp.get("/search")
@login_required
@company_required
def index():
    text = request.args.get("q") or ""
    groups = search.find(g.company["id"], text)
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify({"groups": groups})
    flat = [item for group in groups for item in group["items"]]
    if len(flat) == 1 and not flat[0].get("external"):
        return redirect(flat[0]["href"])
    return render_template("search.html", title="Search", active="", q=text, groups=groups)
