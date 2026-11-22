from flask import Blueprint, flash, g, redirect, render_template, request, send_file

from .. import documents, forms
from ..audit import audit
from ..auth import login_required
from ..db import execute, insert, one, rows
from ..tenancy import at_least, company_required

bp = Blueprint("documents", __name__)

OWNER_COLUMN = {"driver": "driver_id", "truck": "truck_id", "trailer": "trailer_id"}


def owners(company_id):
    return {
        "driver": rows("select id, name as label from drivers where company_id = %s and status = 'active' order by name", (company_id,)),
        "truck": rows("""select id, unit_number as label from trucks where company_id = %s and status <> 'sold'
                         order by lower(unit_number)""", (company_id,)),
        "trailer": rows("select id, unit_number as label from trailers where company_id = %s and status <> 'sold' order by lower(unit_number)",
                        (company_id,)),
    }


def owner_name(owner, owner_id, company_id):
    if owner == "driver":
        row = one("select name from drivers where id = %s and company_id = %s", (owner_id, company_id))
        return row and row["name"]
    if owner == "truck":
        row = one("select unit_number from trucks where id = %s and company_id = %s", (owner_id, company_id))
        return row and f"Unit {row['unit_number']}"
    if owner == "trailer":
        row = one("select unit_number from trailers where id = %s and company_id = %s", (owner_id, company_id))
        return row and f"Trailer {row['unit_number']}"
    return "Company"


@bp.get("/documents")
@login_required
@company_required
def index():
    owner = forms.pick(request.args.get("owner"), ["all", *documents.OWNERS], "all")
    status = forms.pick(request.args.get("status"), ["all", "expired", "soon", "ok"], "all")
    items = documents.listing(g.company["id"], owner, status)
    counts = {"expired": sum(1 for d in items if d["tone"] == "bad"), "soon": sum(1 for d in items if d["tone"] == "warn")}
    return render_template("documents/index.html", title="Documents", active="/trucks", items=items, owner=owner,
                           status=status, owners=documents.OWNERS, counts=counts, missing=documents.missing(g.company["id"]))


@bp.get("/documents/new")
@login_required
@company_required
def new():
    owner = forms.pick(request.args.get("owner"), list(documents.OWNERS), "driver")
    owner_id = forms.integer(request.args.get("id"))
    return render_template("documents/form.html", title="Add document", active="/trucks", doc={"owner": owner,
                           OWNER_COLUMN.get(owner, "x"): owner_id}, owner=owner, owner_id=owner_id, kinds=documents.KINDS,
                           owner_labels=documents.OWNERS, choices=owners(g.company["id"]),
                           back=request.args.get("back") or "/documents")


def values(source, owner):
    return {
        "kind": forms.pick(source.get("kind"), [k for k, _ in documents.KINDS[owner]], "other"),
        "title": forms.text(source.get("title"), 120),
        "number": forms.text(source.get("number"), 80),
        "state": forms.text(source.get("state"), 4),
        "issued_on": forms.day(source.get("issued_on")),
        "expires_on": forms.day(source.get("expires_on")),
        "note": forms.text(source.get("note"), 1000),
    }


def safe_back(value, fallback):
    return value if value and value.startswith("/") and not value.startswith("//") else fallback


@bp.post("/documents")
@login_required
@company_required
def create():
    company_id = g.company["id"]
    owner = forms.pick(request.form.get("owner"), list(documents.OWNERS), None)
    owner_id = forms.integer(request.form.get("owner_id"))
    back = safe_back(request.form.get("back"), "/documents")
    if not owner or (owner != "company" and not owner_name(owner, owner_id, company_id)):
        flash("Pick who the document belongs to.", "bad")
        return redirect(back)
    data = values(request.form, owner)
    try:
        stored = documents.save_file(company_id, request.files.get("file")) or {}
    except ValueError as err:
        flash(str(err), "bad")
        return redirect(back)
    doc = insert(
        """insert into documents (company_id, owner, driver_id, truck_id, trailer_id, kind, title, number, state, issued_on,
             expires_on, note, file_path, file_name, content_type, created_by)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id""",
        (company_id, owner, owner_id if owner == "driver" else None, owner_id if owner == "truck" else None,
         owner_id if owner == "trailer" else None, data["kind"], data["title"], data["number"], data["state"],
         data["issued_on"], data["expires_on"], data["note"], stored.get("file_path"), stored.get("file_name"),
         stored.get("content_type"), g.user["id"]),
    )
    audit("document.create", "document", doc["id"])
    flash(f"{data['title'] or documents.label(owner, data['kind'])} added.", "ok")
    return redirect(back)


def load(doc_id):
    return one("select * from documents where id = %s and company_id = %s", (doc_id, g.company["id"]))


@bp.get("/documents/<int:doc_id>")
@login_required
@company_required
def edit(doc_id):
    doc = load(doc_id)
    if not doc:
        return render_template("errors/404.html"), 404
    doc = documents.shape(one(documents.LIST_SQL + " where d.id = %s", (doc_id,)))
    return render_template("documents/form.html", title=doc["label"], active="/trucks", doc=doc, owner=doc["owner"],
                           owner_id=doc.get(OWNER_COLUMN.get(doc["owner"], "x")), kinds=documents.KINDS,
                           owner_labels=documents.OWNERS, choices=owners(g.company["id"]),
                           back=request.args.get("back") or doc["href"])


@bp.post("/documents/<int:doc_id>")
@login_required
@company_required
def update(doc_id):
    doc = load(doc_id)
    if not doc:
        return render_template("errors/404.html"), 404
    back = safe_back(request.form.get("back"), "/documents")
    if request.form.get("delete"):
        if not at_least(g.role, "admin"):
            flash("Only an admin can delete documents.", "bad")
            return redirect(back)
        documents.remove_file(doc)
        execute("delete from documents where id = %s", (doc_id,))
        audit("document.delete", "document", doc_id)
        flash("Document deleted.", "ok")
        return redirect(back)
    data = values(request.form, doc["owner"])
    try:
        stored = documents.save_file(g.company["id"], request.files.get("file"))
    except ValueError as err:
        flash(str(err), "bad")
        return redirect(f"/documents/{doc_id}")
    if stored:
        documents.remove_file(doc)
        execute("update documents set file_path = %s, file_name = %s, content_type = %s where id = %s",
                (stored["file_path"], stored["file_name"], stored["content_type"], doc_id))
    reset = data["expires_on"] != doc["expires_on"]
    execute(
        """update documents set kind = %s, title = %s, number = %s, state = %s, issued_on = %s, expires_on = %s, note = %s,
             notified_stage = case when %s then null else notified_stage end, updated_at = now() where id = %s""",
        (data["kind"], data["title"], data["number"], data["state"], data["issued_on"], data["expires_on"], data["note"],
         reset, doc_id),
    )
    audit("document.update", "document", doc_id)
    flash("Saved.", "ok")
    return redirect(back)


@bp.get("/documents/<int:doc_id>/file")
@login_required
@company_required
def file(doc_id):
    doc = load(doc_id)
    path = documents.file_of(doc)
    if not path:
        return render_template("errors/404.html"), 404
    response = send_file(path, mimetype=doc["content_type"], download_name=doc["file_name"] or path.name)
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response
