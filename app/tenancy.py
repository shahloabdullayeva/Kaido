import functools

from flask import g, render_template

from .db import execute, one, rows

ROLES = ["admin", "viewer"]
ROLE_LABELS = {
    "admin": "Admin",
    "viewer": "Read only",
}
RANK = {"admin": 2, "viewer": 1}


def at_least(role, minimum):
    return RANK.get(role, 0) >= RANK.get(minimum, 0)


def is_platform():
    session = getattr(g, "session", None)
    return bool(session and session["platform_role"])


def memberships_for(user_id, platform_role):
    if platform_role:
        return rows(
            """select c.id, c.name, c.status, c.is_house, 'admin' as role
               from companies c where c.status = 'active'
               order by c.is_house desc, lower(c.name)"""
        )
    return rows(
        """select c.id, c.name, c.status, c.is_house, m.role
           from memberships m join companies c on c.id = m.company_id
           where m.user_id = %s and c.status = 'active'
           order by c.is_house desc, lower(c.name)""",
        (user_id,),
    )


def default_company_id(user_id):
    row = one("select company_id from memberships where user_id = %s order by id limit 1", (user_id,))
    return row["company_id"] if row else None


def resolve_company():
    session = g.session
    companies = memberships_for(session["user_id"], session["platform_role"])
    g.companies = companies
    if not companies:
        g.company = None
        g.role = None
        return
    current = next((c for c in companies if c["id"] == session["company_id"]), None)
    if current is None:
        current = companies[0]
        execute("update sessions set company_id = %s where id = %s", (current["id"], session["id"]))
        session["company_id"] = current["id"]
    g.company = current
    g.role = current["role"]


def company_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not getattr(g, "company", None):
            return render_template("errors/no_company.html"), 403
        return view(*args, **kwargs)
    return wrapped


def role_required(minimum):
    def decorator(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            if not getattr(g, "company", None):
                return render_template("errors/no_company.html"), 403
            if not at_least(g.role, minimum):
                return render_template("errors/forbidden.html", needed=ROLE_LABELS.get(minimum, minimum)), 403
            return view(*args, **kwargs)
        return wrapped
    return decorator


def platform_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not is_platform():
            return render_template("errors/forbidden.html", needed="Platform staff"), 403
        return view(*args, **kwargs)
    return wrapped


def scoped_truck(truck_id):
    return one("select * from trucks where id = %s and company_id = %s", (truck_id, g.company["id"]))


def active_trucks():
    return rows(
        """select t.id, t.unit_number, t.status, t.odometer, t.driver_id,
                  d.name as driver_name, t.make, t.model, t.year
           from trucks t left join drivers d on d.id = t.driver_id
           where t.company_id = %s and t.status <> 'sold' order by lower(t.unit_number)""",
        (g.company["id"],),
    )


def active_drivers():
    return rows(
        "select id, name from drivers where company_id = %s and status = 'active' order by lower(name)",
        (g.company["id"],),
    )
