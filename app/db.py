from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import config

pool = ConnectionPool(config.DATABASE_URL, min_size=1, max_size=10, kwargs={"row_factory": dict_row}, open=True)


def current_company():
    try:
        from flask import g, has_app_context
        if not has_app_context() or getattr(g, "unscoped", False):
            return ""
        company = getattr(g, "company", None)
        return str(company["id"]) if company else ""
    except Exception:
        return ""


@contextmanager
def unscoped():
    from flask import g
    previous = getattr(g, "unscoped", False)
    g.unscoped = True
    try:
        yield
    finally:
        g.unscoped = previous


@contextmanager
def cursor():
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select set_config('kaido.company_id', %s, true)", (current_company(),))
            yield cur


def rows(sql, params=None):
    with cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchall()


def one(sql, params=None):
    with cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchone()


def execute(sql, params=None):
    with cursor() as cur:
        cur.execute(sql, params or ())
        return cur.rowcount


def insert(sql, params=None):
    with cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchone()
