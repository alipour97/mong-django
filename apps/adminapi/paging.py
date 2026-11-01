"""Request parsing and the old API's paged result shape."""
from __future__ import annotations

import math


def to_bool(value) -> bool | None:
    """'true'/'false'/1/0/True -> bool; missing or blank -> None."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes")


def to_int(value, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def int_list(values) -> list[int]:
    return [int(v) for v in values or [] if str(v).lstrip("-").isdigit()]


def one_page(items: list, total: int, page_number: int, page_size: int) -> dict:
    """PaginatedResult<T> for a page the source has already cut."""
    return {"totalCount": total, "totalPages": math.ceil(total / page_size), "pageNumber": page_number, "pageSize": page_size, "items": items}


def paginated(items: list, page_number: int, page_size: int, convert=None) -> dict:
    """PaginatedResult<T>: {totalCount, totalPages, pageNumber, pageSize, items} for one page of items."""
    page_number, page_size = max(page_number or 1, 1), max(page_size or 1, 1)
    page = items[(page_number - 1) * page_size: page_number * page_size]
    return {
        "totalCount": len(items),
        "totalPages": math.ceil(len(items) / page_size),
        "pageNumber": page_number,
        "pageSize": page_size,
        "items": [convert(x) for x in page] if convert else page,
    }


def sort_spec(q, allowed) -> tuple[str | None, bool]:
    """(SortBy, SortDesc) from the panel's table, SortBy only when it is one of allowed."""
    key = (q.get("SortBy") or "").strip()
    return (key if key in allowed else None), bool(to_bool(q.get("SortDesc")))


def sort_rows(rows: list, q, keys: dict) -> list:
    """Sorts all rows (before paging) by the column the panel asked for; keys maps SortBy -> value of a row.
    Rows without a value go last either way."""
    key, desc = sort_spec(q, keys)
    if key is None:
        return rows
    value = keys[key]
    present = [r for r in rows if value(r) is not None]
    missing = [r for r in rows if value(r) is None]
    return sorted(present, key=value, reverse=desc) + missing
