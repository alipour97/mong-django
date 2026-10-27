"""
Cached values that are slow to build (the product listing, the admin product
index): built once, then refreshed in the background.

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
    cache.set(key, (built_at, value), None)
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
    entry = cache.get(key)
    if entry is not None:
        built_at, value = entry
        if time.time() - built_at > ttl:
            threading.Thread(target=_refresh, args=(key, build), daemon=True, name=f"warm:{key}").start()
        return value
    with _lock(key):
        entry = cache.get(key)  # built while we waited
        if entry is not None:
            return entry[1]
        return _build(key, build)


def invalidate(key: str) -> None:
    """Mark stale: the next get answers with the current value and rebuilds it."""
    with _guard:
        _generation[key] = _generation.get(key, 0) + 1
    entry = cache.get(key)
    if entry is not None:
        cache.set(key, (0.0, entry[1]), None)


def drop(key: str) -> None:
    """Forget the value entirely (the next get builds and waits)."""
    invalidate(key)
    cache.delete(key)
