from urllib.parse import urlencode

from flask import Blueprint, flash, g, redirect, render_template, request, send_file

from .. import forms, pti, pti_ai, pti_driver
from ..audit import audit, client_ip
from ..auth import login_required, throttle
from ..db import one, rows
from ..db import insert as db_insert
from ..db import execute
from ..logs import get
from ..tenancy import company_required, role_required, scoped_truck

bp = Blueprint("pti", __name__)

STATES = ("ok", "defect", "na")


@bp.get("/pti")
@login_required
@company_required
def index():
    show = forms.pick(request.args.get("show"), ["open", "all", "defects", "review"], "all")
    day, board = pti.today_board(g.company)
    clause = ""
    if show == "open":
        clause = " and i.defect_count > 0 and i.certified_at is null"
    elif show == "defects":
        clause = " and i.defect_count > 0"
    elif show == "review":
        clause = " and i.review_status is null"
    items = rows(
        f"""select i.*, t.unit_number,
                   (select count(*) from inspection_photos p where p.inspection_id = i.id and p.kind = 'photo') as photo_count,
                   (select count(*) from inspection_photos p where p.inspection_id = i.id and p.kind = 'video') as video_count
            from inspections i left join trucks t on t.id = i.truck_id
            where i.company_id = %s{clause} order by i.submitted_at desc limit 300""",
        (g.company["id"],),
    )
    return render_template(
        "pti/list.html", title="PTI", active="/pti", items=items, show=show, board=board, day=day,
        missing=[t for t in board if t["missing"]], open_count=len(pti.open_defects(g.company["id"])),
        kinds=pti.KINDS,
    )


@bp.get("/pti/report/<int:inspection_id>")
@login_required
@company_required
def report(inspection_id):
    item = one(
        """select i.*, t.unit_number, t.make, t.model, t.year, u.name as certified_user, m.status as order_status
           from inspections i left join trucks t on t.id = i.truck_id
           left join users u on u.id = i.certified_by
           left join maintenance_orders m on m.id = i.maintenance_order_id
           where i.id = %s and i.company_id = %s""",
        (inspection_id, g.company["id"]),
    )
    if not item:
        return render_template("errors/404.html"), 404
    photos = rows("select * from inspection_photos where inspection_id = %s order by id", (inspection_id,))
    by_item = {}
    for photo in photos:
        by_item.setdefault(photo["item"] or "", []).append(photo)
    results = item["results"] or {}
    sections = []
    for number, (title, entries) in enumerate(pti.SECTIONS, 1):
        lines = [{"key": key, "label": label, **(results.get(key) or {})} for key, label in entries if key in results]
        if lines:
            sections.append((title, lines, f"section_{number}"))
    extra = [{"key": key, "label": pti.item_label(key), **value} for key, value in results.items()
             if key not in pti.ITEMS and isinstance(value, dict)]
    if extra:
        sections.append(("Reported in Samsara" if item["source"] == "samsara" else "Earlier checklist items", extra, None))
    history = rows(
        "select * from inspection_reviews where inspection_id = %s order by created_at desc, id desc",
        (inspection_id,),
    )
    reviewed = None
    if item["reviewed_previous_id"]:
        reviewed = one("select id, submitted_at, driver_name from inspections where id = %s", (item["reviewed_previous_id"],))
    return render_template(
        "pti/report.html", title=f"PTI #{item['id']}", active="/pti", item=item, sections=sections,
        defects=pti.defects_of(item), photos=by_item, kinds=pti.KINDS, certifications=pti.CERTIFICATIONS,
        reviewed=reviewed, history=history,
    )


@bp.post("/pti/report/<int:inspection_id>/certify")
@login_required
@role_required("admin")
def certify(inspection_id):
    certification = forms.pick(request.form.get("certification"), list(pti.CERTIFICATIONS), None)
    name = forms.required(request.form.get("certified_name"), 120)
    if not certification or not name:
        flash("Pick repaired or not needed, and put the name of who signs it off.", "bad")
        return redirect(f"/pti/report/{inspection_id}")
    done = pti.certify(g.company["id"], inspection_id, certification,
                       forms.text(request.form.get("certified_note"), 2000), name, g.session["user_id"])
    if done:
        audit("pti.certified", "inspection", inspection_id, {"certification": certification})
        flash("Signed off. The next driver will see this on their PTI.", "ok")
    return redirect(f"/pti/report/{inspection_id}")


@bp.post("/pti/report/<int:inspection_id>/work-order")
@login_required
@role_required("admin")
def work_order(inspection_id):
    item = one("select * from inspections where id = %s and company_id = %s", (inspection_id, g.company["id"]))
    if not item or not item["truck_id"]:
        return render_template("errors/404.html"), 404
    if item["maintenance_order_id"]:
        return redirect(f"/maintenance/{item['maintenance_order_id']}")
    found = pti.defects_of(item)
    text = "; ".join(d["label"] + (f": {d['note']}" if d["note"] else "") for d in found)
    order = db_insert(
        """insert into maintenance_orders (company_id, truck_id, kind, status, scheduled_for, odometer, description,
             driver_id, created_by)
           values (%s, %s, 'repair', 'scheduled', current_date, %s, %s, %s, %s) returning id""",
        (g.company["id"], item["truck_id"], item["odometer"], f"PTI #{inspection_id} defects — {text}"[:2000],
         item["driver_id"], g.session["user_id"]),
    )
    execute("update inspections set maintenance_order_id = %s where id = %s", (order["id"], inspection_id))
    audit("pti.work_order", "inspection", inspection_id, {"order": order["id"]})
    flash(f"Work order #{order['id']} opened from this PTI.", "ok")
    return redirect(f"/maintenance/{order['id']}")


@bp.post("/pti/report/<int:inspection_id>/review")
@login_required
@role_required("admin")
def review(inspection_id):
    item = one("select * from inspections where id = %s and company_id = %s", (inspection_id, g.company["id"]))
    if not item:
        return render_template("errors/404.html"), 404
    decision = forms.pick(request.form.get("decision"), ["approved", "rejected"], None)
    note = forms.text(request.form.get("review_note"), 1000)
    if not decision:
        return redirect(f"/pti/report/{inspection_id}")
    if decision == "rejected" and not note:
        flash("Write why it is rejected — the driver sees this in the truck's group.", "bad")
        return redirect(f"/pti/report/{inspection_id}")
    execute(
        """update inspections set review_status = %s, review_note = %s, reviewed_by = %s, reviewed_name = %s,
             reviewed_at = now() where id = %s and company_id = %s""",
        (decision, note, g.session["user_id"], g.session["name"], inspection_id, g.company["id"]),
    )
    execute(
        """insert into inspection_reviews (company_id, inspection_id, decision, note, reviewed_by, reviewed_name)
           values (%s, %s, %s, %s, %s, %s)""",
        (g.company["id"], inspection_id, decision, note, g.session["user_id"], g.session["name"]),
    )
    audit("pti.reviewed", "inspection", inspection_id, {"decision": decision})
    if decision == "rejected":
        told = pti_driver.rejected(item, note)
        flash("Rejected." + (" The driver was told in the truck's group to do it again." if told
                             else " This truck has no Telegram group, so tell the driver yourself."), "ok")
    else:
        flash("Approved.", "ok")
    return redirect(f"/pti/report/{inspection_id}")


@bp.post("/pti/report/<int:inspection_id>/ai-check")
@login_required
@role_required("admin")
def ai_check(inspection_id):
    item = one("select id from inspections where id = %s and company_id = %s", (inspection_id, g.company["id"]))
    if not item:
        return render_template("errors/404.html"), 404
    if pti_ai.over_budget():
        flash("Today's AI spending cap is used up, so the check cannot run again until tomorrow.", "bad")
        return redirect(f"/pti/report/{inspection_id}")
    execute("update inspections set ai_checked_at = null, ai_status = null where id = %s", (inspection_id,))
    result = pti_ai.review(inspection_id)
    audit("pti.ai_recheck", "inspection", inspection_id)
    flash("AI check done." if result else "The AI check could not run on these photos.", "ok" if result else "bad")
    return redirect(f"/pti/report/{inspection_id}")


@bp.get("/pti/photo/<int:photo_id>")
@login_required
@company_required
def photo(photo_id):
    item = one("select * from inspection_photos where id = %s and company_id = %s", (photo_id, g.company["id"]))
    path = pti.photo_file(item) if item else None
    if not path:
        return render_template("errors/404.html"), 404
    response = send_file(path, mimetype=item["content_type"], max_age=86400)
    response.headers["Cache-Control"] = "private, max-age=86400"
    return response


@bp.get("/pti/stickers")
@login_required
@role_required("admin")
def stickers():
    trucks = rows(
        """select * from trucks where company_id = %s and status <> 'sold' and not is_outside
           order by lower(unit_number)""",
        (g.company["id"],),
    )
    only = forms.integer(request.args.get("truck_id"))
    if only:
        trucks = [t for t in trucks if t["id"] == only] or [t for t in [scoped_truck(only)] if t]
    cards = []
    for truck in trucks:
        url = pti.link_for(pti.ensure_token(truck))
        cards.append({"unit": truck["unit_number"], "url": url, "svg": pti.qr_svg(url)})
    return render_template("pti/stickers.html", title="PTI stickers", cards=cards)


@bp.get("/pti/links")
@login_required
@role_required("admin")
def links():
    trucks = rows(
        """select t.*, d.name as driver_name from trucks t left join drivers d on d.id = t.driver_id
           where t.company_id = %s and t.status <> 'sold' and not t.is_outside
           order by lower(t.unit_number)""",
        (g.company["id"],),
    )
    cards = []
    for truck in trucks:
        url = pti.link_for(pti.ensure_token(truck))
        message = (f"Unit {truck['unit_number']} PTI link. Save it and open it before every trip, "
                   f"and after the trip too: {url}")
        cards.append({"id": truck["id"], "unit": truck["unit_number"], "driver": truck["driver_name"],
                      "url": url, "message": message,
                      "telegram": "https://t.me/share/url?" + urlencode({"url": url, "text": message})})
    everything = "\n".join(f"Unit {c['unit']}: {c['url']}" for c in cards)
    return render_template("pti/links.html", title="PTI links", active="/pti", cards=cards, everything=everything)


@bp.post("/trucks/<int:truck_id>/telegram/send")
@login_required
@role_required("admin")
def telegram_send(truck_id):
    truck = pti_driver.one_truck(g.company["id"], truck_id)
    if not truck or not truck["telegram_chat_id"]:
        flash("This truck has no Telegram group connected.", "bad")
        return redirect(f"/trucks/{truck_id}")
    kind = forms.pick(request.form.get("which"), ["morning", "evening"], "morning")
    ok = pti_driver.deliver(truck, kind)
    audit("pti.group_message", "truck", truck_id, {"kind": kind, "ok": ok})
    flash(f"Sent to {truck['telegram_chat_title'] or 'the group'}." if ok
          else "Telegram did not accept it. If the bot was removed from the group, connect it again.", "ok" if ok else "bad")
    return redirect(f"/trucks/{truck_id}")


@bp.post("/trucks/<int:truck_id>/telegram/disconnect")
@login_required
@role_required("admin")
def telegram_disconnect(truck_id):
    pti_driver.disconnect(g.company["id"], truck_id)
    audit("pti.group_removed", "truck", truck_id)
    flash("Group disconnected. No more PTI reminders will go there.", "ok")
    return redirect(f"/trucks/{truck_id}")


@bp.post("/trucks/<int:truck_id>/pti-link")
@login_required
@role_required("admin")
def new_link(truck_id):
    truck = scoped_truck(truck_id)
    if not truck:
        return render_template("errors/404.html"), 404
    pti.new_token(truck_id)
    audit("pti.link_replaced", "truck", truck_id)
    flash("New PTI link made. The old link and sticker no longer work — print a new one.", "ok")
    return redirect(f"/trucks/{truck_id}")


def driver_options(company_id):
    return rows(
        """select id, name from drivers where company_id = %s and status = 'active' and not is_outside
           order by lower(name)""",
        (company_id,),
    )


@bp.get("/pti/<token>")
def driver_form(token):
    truck = pti.truck_by_token(token)
    if not truck:
        return render_template("pti/gone.html", title="PTI"), 404
    previous = pti.previous_with_defects(truck["id"])
    latest = one(
        "select review_status, review_note, kind from inspections where truck_id = %s order by submitted_at desc limit 1",
        (truck["id"],),
    )
    redo = latest if latest and latest["review_status"] == "rejected" else None
    return render_template(
        "pti/driver.html", redo=redo, title=f"PTI · Unit {truck['unit_number']}", truck=truck, token=token,
        sections=pti.SECTIONS, drivers=driver_options(truck["company_id"]), previous=previous,
        previous_defects=pti.defects_of(previous) if previous else [], kinds=pti.KINDS,
        certifications=pti.CERTIFICATIONS, na_allowed=pti.NA_ALLOWED,
    )


@bp.post("/pti/<token>")
def driver_submit(token):
    truck = pti.truck_by_token(token)
    if not truck:
        return render_template("pti/gone.html", title="PTI"), 404
    blocked, _until = throttle(f"pti:{truck['id']}", 30, 60, 30)
    if blocked:
        return render_template("pti/gone.html", title="PTI", busy=True), 429
    back = f"/pti/{token}"
    driver_id = forms.integer(request.form.get("driver_id"))
    driver = None
    if driver_id:
        driver = one("select id, name from drivers where id = %s and company_id = %s", (driver_id, truck["company_id"]))
    driver_name = driver["name"] if driver else forms.text(request.form.get("driver_name"), 120)
    signed = forms.text(request.form.get("signed_name"), 120)
    if not driver_name or not signed:
        flash("Pick your name and sign with your full name at the bottom.", "bad")
        return redirect(back)
    previous = pti.previous_with_defects(truck["id"])
    if previous and not forms.checkbox(request.form.get("reviewed_previous")):
        flash("Tick the box to confirm you read the last report's defects.", "bad")
        return redirect(back)
    results = {}
    missing_notes = []
    for key in pti.ITEMS:
        state = forms.pick(request.form.get(f"item_{key}"), STATES, "ok")
        if state == "na" and key not in pti.NA_ALLOWED:
            state = "ok"
        note = forms.text(request.form.get(f"note_{key}"), 500)
        results[key] = {"state": state}
        if note:
            results[key]["note"] = note
        if state == "defect" and not note:
            missing_notes.append(pti.ITEMS[key])
    if missing_notes:
        flash("Write what is wrong for: " + ", ".join(missing_notes), "bad")
        return redirect(back)
    no_proof = [title for key, title in pti.SECTION_KEYS.items() if not pti.has_file(request.files.getlist(key))]
    no_proof += [pti.ITEMS[key] + " (defect)" for key, value in results.items()
                 if value["state"] == "defect" and not pti.has_file(request.files.getlist(f"photo_{key}"))]
    if no_proof:
        flash("A photo or video is required for: " + ", ".join(no_proof), "bad")
        return redirect(back)
    has_defect = any(value["state"] == "defect" for value in results.values())
    safe = request.form.get("safe_to_drive")
    if has_defect and safe not in ("yes", "no"):
        flash("You marked a defect. Say whether the truck is safe to drive.", "bad")
        return redirect(back)
    values = {
        "driver_id": driver["id"] if driver else None,
        "driver_name": driver_name,
        "kind": forms.pick(request.form.get("kind"), ["pre_trip", "post_trip"], "pre_trip"),
        "odometer": forms.integer(request.form.get("odometer")),
        "results": results,
        "safe_to_drive": (safe == "yes") if has_defect else True,
        "notes": forms.text(request.form.get("notes"), 2000),
        "signed_name": signed,
        "reviewed_previous_id": previous["id"] if previous else None,
    }
    session = getattr(g, "session", None)
    item = pti.create(truck, values, session["user_id"] if session else None, client_ip())
    saved = 0
    for field, uploads in request.files.lists():
        if field.startswith("photo_"):
            key = field[len("photo_"):]
        elif field in pti.SECTION_KEYS:
            key = field
        else:
            continue
        for upload in uploads:
            if saved >= pti.MAX_PHOTOS or not upload or not upload.filename:
                continue
            if pti.save_photo(truck["company_id"], item["id"], key, upload):
                saved += 1
    if item["defect_count"]:
        pti.alert(item["id"])
    try:
        pti_driver.completed(item)
    except Exception:
        get("pti").warning("group notice for inspection %s failed", item["id"], exc_info=True)
    audit("pti.submitted", "inspection", item["id"],
          {"unit": truck["unit_number"], "defects": item["defect_count"], "photos": saved},
          company_id=truck["company_id"], user_id=session["user_id"] if session else None,
          actor=driver_name)
    return render_template("pti/thanks.html", title="PTI sent", truck=truck, item=item, photos=saved,
                           defects=pti.defects_of(item), kinds=pti.KINDS)
