"""
Token Management, Caching, and Authentication for Samian ERP.

Supports multi-layer caching:
1. In-memory dictionary cache (intra-process)
2. Django cache backend / Redis (inter-process & Celery worker sharing)
3. Disk-based persistent file (persistence across app restarts)

Includes automatic detection of 'soft' auth failures (HTTP 200 with code 401 inside JSON body).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
import requests

from .config import (
    SAMIAN_TOKEN_CACHE_KEY_PREFIX,
    DEFAULT_TOKEN_CACHE_TIMEOUT,
    SamianSettings,
)
from .exceptions import SamianAuthError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global In-Memory Token Cache
# ---------------------------------------------------------------------------
_CACHED_SCOPED_TOKENS: dict[str, str] = {}
_SOFT_ERROR_MAX_BYTES = 8192


def _sanitize_scope(scope: str | None) -> str:
    """Turn a token scope into a filesystem & cache-key safe suffix."""
    if not scope:
        return ""
    safe = "".join(ch if (ch.isalnum() or ch in ".-") else "_" for ch in scope)
    return f".{safe}"


def _token_cache_key(scope: str | None) -> str:
    """Generate Django cache key for a given server scope."""
    return f"{SAMIAN_TOKEN_CACHE_KEY_PREFIX}{_sanitize_scope(scope)}"


def _get_token_file_candidates(scope: str | None) -> list[Path]:
    """Return primary log-dir file and /tmp fallback for the token scope."""
    filename = f".samian_erp_token{_sanitize_scope(scope)}"
    candidates: list[Path] = []
    try:
        from django.conf import settings
        base_dir = getattr(settings, "BASE_DIR", None)
        if base_dir:
            log_dir = Path(base_dir) / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            candidates.append(log_dir / filename)
    except Exception:
        pass

    candidates.append(Path("/tmp") / filename)
    return candidates


def soft_auth_failure(resp: requests.Response) -> bool:
    """
    Check if Samian ERP rejected the token inside an HTTP 200 response.

    Samian list endpoints frequently respond with:
    HTTP 200: {"status": false, "code": 401, "developerMessage": "InvalidUser", "data": null}
    """
    if resp.status_code != 200:
        return False

    content = resp.content or b""
    if len(content) > _SOFT_ERROR_MAX_BYTES:
        return False

    try:
        body = resp.json()
    except Exception:
        return False

    if not isinstance(body, dict):
        return False

    is_status_false = body.get("status") is False
    has_401_code = str(body.get("code")) in ("401", "403")
    is_invalid_user = body.get("developerMessage") in ("InvalidUser", "Unauthorized", "AccessDenied")

    return is_status_false and (has_401_code or is_invalid_user)


class SamianTokenManager:
    """
    Manages token caching across Memory, Django Cache (Redis), and Disk.
    """

    @classmethod
    def get_token(cls, scope: str | None = None) -> str | None:
        """
        Retrieve token with priority:
        1. In-memory
        2. Django cache (Redis)
        3. Disk file
        """
        scope_key = scope or "default"

        # 1. In-Memory
        token = _CACHED_SCOPED_TOKENS.get(scope_key)
        if token and token.strip():
            return token.strip()

        # 2. Django Cache
        try:
            from django.core.cache import cache
            cached_token = cache.get(_token_cache_key(scope))
            if cached_token and isinstance(cached_token, str) and cached_token.strip():
                clean = cached_token.strip()
                _CACHED_SCOPED_TOKENS[scope_key] = clean
                return clean
        except Exception as exc:
            logger.debug("Failed reading Samian token from Django cache: %s", exc)

        # 3. Disk File
        for path in _get_token_file_candidates(scope):
            try:
                if path.is_file():
                    content = path.read_text(encoding="utf-8").strip()
                    if content:
                        _CACHED_SCOPED_TOKENS[scope_key] = content
                        try:
                            from django.core.cache import cache
                            cache.set(_token_cache_key(scope), content, timeout=DEFAULT_TOKEN_CACHE_TIMEOUT)
                        except Exception:
                            pass
                        return content
            except Exception as exc:
                logger.debug("Failed reading Samian token from disk file %s: %s", path, exc)

        return None

    @classmethod
    def set_token(cls, token: str, scope: str | None = None, timeout: int = DEFAULT_TOKEN_CACHE_TIMEOUT) -> None:
        """
        Save token across Memory, Django Cache, and Disk.
        """
        cleaned = (token or "").strip()
        if not cleaned:
            return

        scope_key = scope or "default"

        # 1. In-Memory
        _CACHED_SCOPED_TOKENS[scope_key] = cleaned

        # 2. Django Cache
        try:
            from django.core.cache import cache
            cache.set(_token_cache_key(scope), cleaned, timeout=timeout)
        except Exception as exc:
            logger.debug("Failed writing Samian token to Django cache: %s", exc)

        # 3. Disk File
        for path in _get_token_file_candidates(scope):
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(cleaned, encoding="utf-8")
                try:
                    path.chmod(0o666)
                except Exception:
                    pass
            except Exception as exc:
                logger.debug("Failed persisting Samian token to %s: %s", path, exc)

    @classmethod
    def clear_token(cls, scope: str | None = None) -> None:
        """
        Invalidate token on 401 or logout.
        """
        scope_key = scope or "default"

        # 1. In-Memory
        _CACHED_SCOPED_TOKENS.pop(scope_key, None)

        # 2. Django Cache
        try:
            from django.core.cache import cache
            cache.delete(_token_cache_key(scope))
        except Exception as exc:
            logger.debug("Failed deleting Samian token from Django cache: %s", exc)

        # 3. Disk File
        for path in _get_token_file_candidates(scope):
            try:
                if path.is_file():
                    path.unlink(missing_ok=True)
            except Exception as exc:
                logger.debug("Failed unlinking Samian token file %s: %s", path, exc)


def login(config: SamianSettings, session: requests.Session | None = None) -> str:
    """
    Authenticate against Samian ERP (POST /v2/account/erpweb/login) and return access token.
    """
    if not config.username or not config.password:
        raise SamianAuthError("Samian credentials missing: username and password are required.")

    sess = session or requests.Session()
    url = f"{config.base_url}/v2/account/erpweb/login"
    payload = {"username": config.username, "password": config.password}
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (compatible; MongSamianClient/2.0)",
    }

    logger.info("Authenticating with Samian ERP at %s for user '%s'...", url, config.username)
    try:
        resp = sess.post(url, json=payload, headers=headers, timeout=config.timeout)
    except requests.RequestException as exc:
        raise SamianAuthError(f"Network error during Samian login: {exc}") from exc

    if resp.status_code != 200:
        raise SamianAuthError(
            f"Samian login failed with HTTP {resp.status_code}: {resp.text[:500]}",
            status_code=resp.status_code,
            response_data=resp.text,
            endpoint="v2/account/erpweb/login",
        )

    try:
        data = resp.json()
    except Exception as exc:
        raise SamianAuthError(f"Invalid JSON in Samian login response: {resp.text[:300]}") from exc

    token = None
    if isinstance(data, dict):
        inner = data.get("data")
        if isinstance(inner, dict):
            token = inner.get("token") or inner.get("access_token")
        elif isinstance(inner, str):
            token = inner
        if not token:
            token = data.get("token") or data.get("access_token")

    if not token:
        raise SamianAuthError(
            f"No token found in Samian login response: {data}",
            response_data=data,
            endpoint="v2/account/erpweb/login",
        )

    token_str = str(token).strip()
    SamianTokenManager.set_token(token_str, scope=config.token_scope, timeout=config.token_cache_timeout)
    logger.info("Samian login successful. Token acquired and cached for scope '%s'.", config.token_scope)
    return token_str


def ensure_authenticated_token(
    config: SamianSettings,
    session: requests.Session | None = None,
    force_refresh: bool = False,
) -> str:
    """
    Return valid bearer token from cache or perform login.
    """
    if not force_refresh:
        cached = SamianTokenManager.get_token(config.token_scope)
        if cached:
            return cached

    return login(config, session)
