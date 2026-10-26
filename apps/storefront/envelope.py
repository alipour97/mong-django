"""
Response envelope used by the legacy .NET storefront API (api.mong.ir).

Every endpoint answers with:

    {"result": {"data": ..., "totalPages": N}, "statusCode": 200,
     "statusMessage": "...", "timestamp": <.NET ticks>}

Note that "not found" is HTTP 200 with statusCode 404 in the body, which the
frontend relies on.
"""
from __future__ import annotations

import time
from datetime import date, datetime

from django.utils import timezone
from rest_framework.response import Response

MSG_FETCHED = "اطلاعات با موفقیت دریافت شدند."
MSG_FETCHED_ONE = "اطلاعات با موفقیت دریافت شد."
MSG_SENT = "اطلاعات با موفقیت ارسال شد."
MSG_NOT_FOUND = "اطلاعات مورد نظر یافت نشد."
MSG_NOT_FOUND_REQUIRED = "اطلاعات مورد نیاز یافت نشد."
MSG_ERROR = "Something went wrong"

_EPOCH_TICKS = 621355968000000000  # .NET ticks at 1970-01-01


def dotnet_ticks() -> int:
    return _EPOCH_TICKS + int(time.time() * 10_000_000)


def envelope(data, *, total_pages: int = 0, status_code: int = 200, message: str = MSG_FETCHED, http_status: int = 200):
    return Response(
        {
            "result": {"data": data, "totalPages": total_pages},
            "statusCode": status_code,
            "statusMessage": message,
            "timestamp": dotnet_ticks(),
        },
        status=http_status,
    )


def ok(data, *, total_pages: int = 0, message: str = MSG_FETCHED):
    return envelope(data, total_pages=total_pages, message=message)


def not_found(data=None, *, http_status: int = 200, message: str = MSG_NOT_FOUND):
    """Most legacy endpoints answered "not found" with HTTP 200; a few (outfits) used HTTP 404."""
    return envelope(data, status_code=404, message=message, http_status=http_status)


def server_error():
    return envelope(None, status_code=500, message=MSG_ERROR, http_status=500)


# -----------------------------------------------------------------------------
# Value formatting the way the .NET API did it
# -----------------------------------------------------------------------------
def iso(dt: datetime | None) -> str | None:
    """ISO-8601 with offset, e.g. 2025-07-24T11:25:36.856666+00:00."""
    return dt.isoformat() if dt else None


def _g2j(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1]
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    return jy, jm, jd


def jalali(dt: datetime | date | None, with_time: bool = True) -> str | None:
    """Tehran-local Jalali string, e.g. 1404/08/30 20:30."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        dt = timezone.localtime(dt) if timezone.is_aware(dt) else dt
    jy, jm, jd = _g2j(dt.year, dt.month, dt.day)
    text = f"{jy:04d}/{jm:02d}/{jd:02d}"
    if with_time and isinstance(dt, datetime):
        text += f" {dt.hour:02d}:{dt.minute:02d}"
    return text
