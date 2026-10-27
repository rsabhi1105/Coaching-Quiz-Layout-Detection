"""Postgres access (same DB as the platform). Django owns the schema: this tool never creates or alters tables."""

import psycopg

from .config import get_settings


def connect() -> psycopg.Connection:
    return psycopg.connect(get_settings().dsn, connect_timeout=5)


def check() -> dict:
    s = get_settings()
    with connect() as conn:
        version = conn.execute("select version()").fetchone()[0]
        tables = [r[0] for r in conn.execute(
            "select table_name from information_schema.tables "
            "where table_schema='public' and table_name like 'book%' order by 1").fetchall()]
    return {"dsn": s.safe_dsn(), "server": version.split(",")[0], "book_tables": tables}
