"""
How long each API request took and what it asked the database. Off unless REQUEST_TIMING is on.

Every request adds a Server-Timing header (the browser's Network tab shows it under Timing) and a
line in REQUEST_TIMING_FILE, which `python manage.py timing_report` sums up. The front's server
calls this API too, so its requests are measured here even though the browser never sees them.
"""
from __future__ import annotations

import json
import logging
import re
import time

from django.conf import settings
from django.core.exceptions import MiddlewareNotUsed
from django.db import connection
from django.test.utils import CaptureQueriesContext

logger = logging.getLogger(__name__)

NUMBERS = re.compile(r"\b\d+\b|'[^']*'")
SLOWEST = 3
USES_DATABASE = ("/api/", "/django-admin/")  # photos never touch it


def _summary(queries: list[dict]) -> tuple[float, list[dict], int]:
    """(database ms, slowest statements, statements repeated with other values)."""
    took = [(float(q["time"]) * 1000, q["sql"]) for q in queries]
    shapes = [NUMBERS.sub("?", sql) for _, sql in took]
    slow = [{"ms": round(ms, 1), "sql": sql[:300]} for ms, sql in sorted(took, key=lambda t: -t[0])[:SLOWEST]]
    return sum(ms for ms, _ in took), slow, len(shapes) - len(set(shapes))


class RequestTiming:
    def __init__(self, get_response):
        if not settings.REQUEST_TIMING:
            raise MiddlewareNotUsed
        self.get_response = get_response

    def __call__(self, request):
        started = time.perf_counter()
        connect_ms = 0.0
        if connection.connection is None and request.path.startswith(USES_DATABASE):
            connection.ensure_connection()
            connect_ms = (time.perf_counter() - started) * 1000
        with CaptureQueriesContext(connection) as captured:
            response = self.get_response(request)
        total_ms = (time.perf_counter() - started) * 1000
        db_ms, slow, repeated = _summary(captured.captured_queries)
        count = len(captured.captured_queries)
        response["Server-Timing"] = (f'total;dur={total_ms:.1f}, connect;dur={connect_ms:.1f}, '
                                     f'db;dur={db_ms:.1f};desc="{count} queries, {repeated} repeated"')
        response["Timing-Allow-Origin"] = "*"
        self.write({"at": time.time(), "method": request.method, "path": request.path, "status": response.status_code, "total": round(total_ms, 1),
                    "connect": round(connect_ms, 1), "db": round(db_ms, 1), "queries": count, "repeated": repeated, "slow": slow})
        return response

    def write(self, line: dict) -> None:
        try:
            with open(settings.REQUEST_TIMING_FILE, "a", encoding="utf8") as out:
                out.write(json.dumps(line, ensure_ascii=False) + "\n")
        except OSError:
            logger.exception("timing line not written")
