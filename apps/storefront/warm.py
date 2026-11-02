"""
Cached values that are slow to build (the product listing, the admin product
index, the category tree): built once, then refreshed in the background. The
value stays in this process as it is, since the cache would unpickle all of it
on every request; the cache holds only when it was built.

A fresh value is returned as is. A stale one (older than ttl, or invalidated
by an edit) is returned too, while one background thread builds the next one,
so no request waits for a rebuild. Only the very first build, with nothing
cached yet, makes requests wait, and they wait for one shared build.

An invalidation during a build marks that build's result stale, so it is
built again with the edit included.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from django.core.cache import cache
from django.db import close_old_connections, connection

log = logging.getLogger(__name__)

_values: dict[str, object] = {}
_locks: dict[str, threading.Lock] = {}
_generation: dict[str, int] = {}
_guard = threading.Lock()


def _lock(key: str) -> threading.Lock:
    with _guard:
        return _locks.setdefault(key, threading.Lock())


def _build(key: str, build: Callable) -> object:
    """Build and store; the caller holds the key's lock."""
    gen = _generation.get(key, 0)
    value = build()
    built_at = time.time() if _generation.get(key, 0) == gen else 0.0
    _values[key] = value
    cache.set(key, built_at, None)
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
        if time.time() - built_at > ttl:
            threading.Thread(target=_refresh, args=(key, build), daemon=True, name=f"warm:{key}").start()
        return _values[key]
    with _lock(key):
        if cache.get(key) is not None and key in _values:  # built while we waited
            return _values[key]
        return _build(key, build)


def invalidate(key: str) -> None:
    """Mark stale: the next get answers with the current value and rebuilds it."""
    with _guard:
        _generation[key] = _generation.get(key, 0) + 1
    if cache.get(key) is not None:
        cache.set(key, 0.0, None)


def drop(key: str) -> None:
    """Forget the value entirely (the next get builds and waits)."""
    invalidate(key)
    cache.delete(key)
