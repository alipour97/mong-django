"""
Cached values that are slow to build (the product listing, the admin product
index, the category tree): built once, then refreshed in the background. The
value stays in this process as it is, since the cache would unpickle all of it
on every request; the cache holds only when it was built.

A fresh value is returned as is. A stale one (older than ttl, or invalidated
by an edit) is returned too, while one background thread builds the next one,
so no request waits for a rebuild. Only the very first build, with nothing
cached yet, makes requests wait, and they wait for one shared build.

The web workers, the sync and the Django admin are separate processes with
separate memory, so an invalidation goes through the database: a counter per
key (website.CacheStamp), which each process reads at most every CHECK_SECONDS
so a request usually costs no query. A value built from an older counter is
stale, also when the invalidation came during its build.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from django.core.cache import cache
from django.db import close_old_connections, connection
from django.db.models import F

from apps.website.models import CacheStamp

log = logging.getLogger(__name__)

CHECK_SECONDS = 5

_values: dict[str, object] = {}
_built_from: dict[str, int] = {}  # key -> the counter its value was built from
_seen: dict[str, tuple[float, int]] = {}  # key -> when the counter was read, and its value
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def _lock(key: str) -> threading.Lock:
    with _guard:
        return _locks.setdefault(key, threading.Lock())


def _read_stamp(key: str) -> int:
    stamp = CacheStamp.objects.filter(key=key).values_list("stamp", flat=True).first() or 0
    _seen[key] = (time.time(), stamp)
    return stamp


def _stamp(key: str) -> int:
    read_at, stamp = _seen.get(key, (0.0, 0))
    return stamp if time.time() - read_at < CHECK_SECONDS else _read_stamp(key)


def _build(key: str, build: Callable) -> object:
    """Build and store; the caller holds the key's lock."""
    stamp = _read_stamp(key)
    value = build()
    _values[key] = value
    _built_from[key] = stamp
    cache.set(key, time.time(), None)
    return value


def _refresh(key: str, build: Callable) -> None:
    lock = _lock(key)
    if not lock.acquire(blocking=False):
        return  # already being built
    try:
        close_old_connections()
        _build(key, build)
    except Exception:
        log.exception("background rebuild of %s failed", key)
    finally:
        lock.release()
        connection.close()


def get(key: str, ttl: float, build: Callable):
    built_at = cache.get(key)
    if built_at is not None and key in _values:
        if time.time() - built_at > ttl or _built_from.get(key) != _stamp(key):
            threading.Thread(target=_refresh, args=(key, build), daemon=True, name=f"warm:{key}").start()
        return _values[key]
    with _lock(key):
        if cache.get(key) is not None and key in _values:  # built while we waited
            return _values[key]
        return _build(key, build)


def invalidate(key: str) -> None:
    """Mark stale in every process: the next get answers with the current value and rebuilds it."""
    if not CacheStamp.objects.filter(key=key).update(stamp=F("stamp") + 1):
        CacheStamp.objects.get_or_create(key=key, defaults={"stamp": 1})
    _seen.pop(key, None)


def drop(key: str) -> None:
    """Mark stale everywhere, and here forget the value too (the next get builds and waits)."""
    invalidate(key)
    cache.delete(key)
