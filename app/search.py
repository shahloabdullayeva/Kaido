import re

from .db import rows

LIMIT = 6
GROUPS = [("units", "Units"), ("drivers", "Drivers"), ("trailers", "Trailers"), ("work_orders", "Work orders"),
          ("shops", "Shops"), ("recalls", "Recalls")]


def find(company_id, text):
    text = " ".join((text or "").split())[:80]
    if len(text) < 2:
        return []
    like = f"%{text}%"
    digits = re.sub(r"\D", "", text)
    out = {}
    out["units"] = [{"label": r["unit_number"], "detail": " · ".join(p for p in [r["carrier_group"], r["driver_name"], r["plate"],
                                                                                  (r["vin"] or "")[-6:] and "VIN …" + r["vin"][-6:]] if p),
                     "href": f"/trucks/{r['id']}"} for r in rows(
        """select t.id, t.unit_number, t.carrier_group, t.plate, t.vin, d.name as driver_name from trucks t
           left join drivers d on d.id = t.driver_id
           where t.company_id = %(c)s and t.status <> 'sold'
             and (t.unit_number ilike %(like)s or coalesce(t.unit_label, '') ilike %(like)s or coalesce(t.vin, '') ilike %(like)s
                  or coalesce(t.plate, '') ilike %(like)s or coalesce(t.carrier_group, '') ilike %(like)s)
           order by (lower(t.unit_number) = lower(%(text)s)) desc, (t.unit_number ilike %(start)s) desc, t.is_outside,
                    lower(t.unit_number) limit %(n)s""",
        {"c": company_id, "like": like, "text": text, "start": text + "%", "n": LIMIT})]
    out["drivers"] = [{"label": r["name"], "detail": " · ".join(p for p in [r["unit_number"] and "unit " + r["unit_number"], r["phone"]] if p),
                       "href": f"/drivers/{r['id']}"} for r in rows(
        """select d.id, d.name, d.phone, (select unit_number from trucks t where t.driver_id = d.id limit 1) as unit_number
           from drivers d where d.company_id = %(c)s and (d.name ilike %(like)s or coalesce(d.phone, '') ilike %(like)s
                                                          or coalesce(d.telegram_username, '') ilike %(like)s)
           order by d.status, (d.name ilike %(start)s) desc, lower(d.name) limit %(n)s""",
        {"c": company_id, "like": like, "start": text + "%", "n": LIMIT})]
    out["trailers"] = [{"label": "Trailer " + r["unit_number"], "detail": " · ".join(p for p in [r["plate"], (r["vin"] or "")[-6:] and "VIN …" + r["vin"][-6:]] if p),
                        "href": f"/trailers/{r['id']}"} for r in rows(
        """select id, unit_number, plate, vin from trailers where company_id = %(c)s
             and (unit_number ilike %(like)s or coalesce(vin, '') ilike %(like)s or coalesce(plate, '') ilike %(like)s)
           order by lower(unit_number) limit %(n)s""",
        {"c": company_id, "like": like, "n": LIMIT})]
    number = int(text.lstrip("#")) if text.lstrip("#").isdigit() and len(text.lstrip("#")) <= 9 else None
    out["work_orders"] = [{"label": f"#{r['id']} {(r['description'] or '')[:60]}", "detail": " · ".join(p for p in [r["unit"], r["status"].replace("_", " "), r["vendor"]] if p),
                           "href": f"/maintenance/{r['id']}"} for r in rows(
        """select m.id, m.description, m.status, m.vendor,
                  case when m.asset_type = 'trailer' then tr.unit_number else t.unit_number end as unit
           from maintenance_orders m left join trucks t on t.id = m.truck_id left join trailers tr on tr.id = m.trailer_id
           where m.company_id = %(c)s and (m.id = %(num)s or m.description ilike %(like)s or coalesce(m.vendor, '') ilike %(like)s
                                           or coalesce(m.invoice_no, '') ilike %(like)s)
           order by (m.id = %(num)s) desc, m.reported_at desc limit %(n)s""",
        {"c": company_id, "like": like, "num": number, "n": LIMIT})]
    out["shops"] = [{"label": r["name"], "detail": " · ".join(p for p in [r["address"], r["phone"]] if p),
                     "href": r["maps_url"] or "/maintenance/saved-shops", "external": bool(r["maps_url"])} for r in rows(
        """select name, address, phone, maps_url from saved_shops where company_id = %(c)s
             and (name ilike %(like)s or coalesce(address, '') ilike %(like)s or coalesce(phone, '') ilike %(like)s)
           order by (name ilike %(start)s) desc, lower(name) limit %(n)s""",
        {"c": company_id, "like": like, "start": text + "%", "n": LIMIT})]
    out["recalls"] = [] if len(text) < 3 else [{"label": f"{r['campaign']} {(r['component'] or '').split(':')[0].title()}", "detail": f"unit {r['unit']} · {r['status'].replace('_', ' ')}",
                       "href": (f"/trucks/{r['truck_id']}#recalls" if r["truck_id"] else f"/trailers/{r['trailer_id']}#recalls")} for r in rows(
        """select v.truck_id, v.trailer_id, v.status, c.campaign, c.component, coalesce(t.unit_number, tr.unit_number) as unit
           from vehicle_recalls v join recall_campaigns c on c.campaign = v.campaign
           left join trucks t on t.id = v.truck_id left join trailers tr on tr.id = v.trailer_id
           where v.company_id = %(c)s and (c.campaign ilike %(like)s or c.component ilike %(like)s or c.summary ilike %(like)s)
           order by (v.status = 'open') desc, c.report_date desc limit %(n)s""",
        {"c": company_id, "like": like, "n": LIMIT})]
    return [{"key": key, "title": title, "items": out[key]} for key, title in GROUPS if out.get(key)]
