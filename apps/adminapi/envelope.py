"""
Admin API responses, shaped like the old AdminApi: {"data", "message", "status"}.
Errors keep that shape with an HTTP error code; the panel shows "message".
"""
from __future__ import annotations

from rest_framework.response import Response


def ok(data=None, message: str | None = None) -> Response:
    return Response({"data": data, "message": message, "status": True})


def fail(message: str, http_status: int = 400, data=None) -> Response:
    return Response({"data": data, "message": message, "status": False}, status=http_status)


def unauthorized(message: str | None = None) -> Response:
    return fail(message, 401)
