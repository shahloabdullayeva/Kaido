from flask import Blueprint, g, redirect, request

from .. import forms
from ..auth import login_required
from ..db import one
from ..tenancy import company_required

bp = Blueprint("breakdowns", __name__)


@bp.get("/breakdowns")
@login_required
@company_required
def index():
    return redirect("/maintenance")


@bp.get("/breakdowns/new")
@login_required
@company_required
def new():
    truck_id = forms.integer(request.args.get("truck_id"))
    return redirect("/maintenance/new" + (f"?truck_id={truck_id}" if truck_id else ""))


@bp.get("/breakdowns/<int:breakdown_id>")
@login_required
@company_required
def detail(breakdown_id):
    order = one("select id from maintenance_orders where from_breakdown_id = %s and company_id = %s",
                (breakdown_id, g.company["id"]))
    return redirect(f"/maintenance/{order['id']}" if order else "/maintenance")
