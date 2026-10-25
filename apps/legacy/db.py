"""
Read-only access to the legacy website database (DadehfaOnlineShop, SQL Server).

Nothing in this project may write to that database. Every statement sent through
the engine is checked before it reaches the server and anything that is not a
read is rejected.
"""
from __future__ import annotations

import re
import urllib.parse
from functools import lru_cache

from django.conf import settings
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

_ALLOWED_START = re.compile(r"^\s*(SELECT|WITH|SET\s+(TRANSACTION|NOCOUNT|LOCK_TIMEOUT|TEXTSIZE|ANSI_|QUOTED_|ARITHABORT|CONCAT_NULL|DATEFORMAT|LANGUAGE))\b", re.I)
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|ALTER|CREATE|EXEC|EXECUTE|GRANT|REVOKE|DENY|BACKUP|RESTORE|DBCC|INTO|sp_\w+|xp_\w+)\b",
    re.I,
)
_COMMENTS = re.compile(r"(--[^\n]*)|(/\*.*?\*/)", re.S)
_STRINGS = re.compile(r"N?'(?:[^']|'')*'")


class ReadOnlyViolation(RuntimeError):
    pass


def assert_read_only(statement: str) -> None:
    bare = _STRINGS.sub("''", _COMMENTS.sub(" ", statement))
    if not _ALLOWED_START.match(bare) or _FORBIDDEN.search(bare):
        raise ReadOnlyViolation(f"Only read statements are allowed on DadehfaOnlineShop: {statement[:200]!r}")


def _connection_url() -> str:
    cfg = settings.DADEHFA_DB
    missing = [k for k in ("HOST", "PORT", "NAME", "USER", "PASSWORD") if not cfg.get(k)]
    if missing:
        raise RuntimeError(f"DADEHFA_DB_* settings missing: {', '.join(missing)}")
    return (
        f"mssql+pymssql://{cfg['USER']}:{urllib.parse.quote_plus(cfg['PASSWORD'])}"
        f"@{cfg['HOST']}:{cfg['PORT']}/{cfg['NAME']}?charset=UTF8"
    )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    engine = create_engine(_connection_url(), pool_pre_ping=True, pool_size=2, max_overflow=2)

    @event.listens_for(engine, "before_cursor_execute")
    def _guard(conn, cursor, statement, parameters, context, executemany):
        assert_read_only(statement)

    @event.listens_for(engine, "connect")
    def _session_defaults(dbapi_conn, record):
        cur = dbapi_conn.cursor()
        cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
        cur.close()

    return engine


def fetch_all(sql: str, params: dict | None = None) -> list[dict]:
    """Run a SELECT and return rows as dicts. The transaction is always rolled back."""
    assert_read_only(sql)
    with get_engine().connect() as conn:
        try:
            result = conn.execute(text(sql), params or {})
            return [dict(r._mapping) for r in result]
        finally:
            conn.rollback()


def iter_rows(sql: str, params: dict | None = None, chunk: int = 2000):
    """Stream a large SELECT in chunks."""
    assert_read_only(sql)
    with get_engine().connect().execution_options(stream_results=True) as conn:
        try:
            result = conn.execute(text(sql), params or {})
            while rows := result.fetchmany(chunk):
                for r in rows:
                    yield dict(r._mapping)
        finally:
            conn.rollback()
