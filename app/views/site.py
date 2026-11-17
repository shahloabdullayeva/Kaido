from flask import Blueprint, Response, send_from_directory

bp = Blueprint("site", __name__)


@bp.get("/robots.txt")
def robots():
    body = "User-agent: *\nDisallow: /\n"
    return Response(body, mimetype="text/plain")


@bp.get("/favicon.ico")
def favicon():
    return send_from_directory(bp.root_path + "/../static", "favicon.png", mimetype="image/png")
