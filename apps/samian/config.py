"""
Configuration and settings for Samian ERP API Client.

CRITICAL ARCHITECTURE NOTE:
- Port 8087 is Samian ERP's DEVELOPMENT server.
- Port 8086 is strictly RESERVED FOR PRODUCTION and MUST NOT be used in development.
- The default base URL is permanently configured to http://78.109.198.8:8087.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Default to development server (Port 8087). NEVER port 8086!
DEFAULT_SAMIAN_BASE_URL = "http://78.109.198.8:8087"
PRODUCTION_SAMIAN_PORT = "8086"
DEVELOPMENT_SAMIAN_PORT = "8087"

DEFAULT_SAMIAN_TIMEOUT = 60
DEFAULT_TOKEN_CACHE_TIMEOUT = 60 * 60 * 24 * 30  # 30 days
SAMIAN_TOKEN_CACHE_KEY_PREFIX = "samian_erp_auth_token"


@dataclass
class SamianSettings:
    """
    Structured settings container for Samian ERP API connection.
    """
    base_url: str = DEFAULT_SAMIAN_BASE_URL
    username: str = ""
    password: str = ""
    timeout: int = DEFAULT_SAMIAN_TIMEOUT
    token_scope: str | None = None
    token_cache_timeout: int = DEFAULT_TOKEN_CACHE_TIMEOUT
    allow_production_server: bool = False
    extra_headers: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        # Normalize URL
        self.base_url = self.base_url.rstrip("/")

        # Validate against accidental production usage
        parsed = urlparse(self.base_url)
        if str(parsed.port) == PRODUCTION_SAMIAN_PORT and not self.allow_production_server:
            msg = (
                f"SAFETY GUARD TRIGGERED: Attempted to connect to Samian Production Port "
                f"({PRODUCTION_SAMIAN_PORT}) at {self.base_url}. "
                f"Development and staging MUST connect to port {DEVELOPMENT_SAMIAN_PORT}."
            )
            logger.critical(msg)
            raise ValueError(msg)

        if not self.token_scope:
            self.token_scope = parsed.netloc or self.base_url


def get_samian_settings(
    base_url: str | None = None,
    username: str | None = None,
    password: str | None = None,
    timeout: int | None = None,
    token_scope: str | None = None,
    allow_production: bool = False,
) -> SamianSettings:
    """
    Resolve Samian ERP configuration with the following priority:
    1. Explicit function arguments
    2. Django settings (settings.SAMIAN_BASE_URL, settings.SAMIAN_API_URL, etc.)
    3. OS Environment variables (SAMIAN_BASE_URL, SAMIAN_USERNAME, etc.)
    4. Safe Defaults (http://78.109.198.8:8087)
    """
    django_settings = None
    try:
        from django.conf import settings
        django_settings = settings
    except Exception:
        pass

    resolved_base_url = (
        base_url
        or getattr(django_settings, "SAMIAN_BASE_URL", None)
        or getattr(django_settings, "SAMIAN_API_URL", None)
        or os.getenv("SAMIAN_BASE_URL")
        or os.getenv("SAMIAN_API_URL")
        or DEFAULT_SAMIAN_BASE_URL
    )

    resolved_username = (
        username
        or getattr(django_settings, "SAMIAN_USERNAME", None)
        or os.getenv("SAMIAN_USERNAME")
        or ""
    )

    resolved_password = (
        password
        or getattr(django_settings, "SAMIAN_PASSWORD", None)
        or os.getenv("SAMIAN_PASSWORD")
        or ""
    )

    resolved_timeout = (
        timeout
        or getattr(django_settings, "SAMIAN_TIMEOUT", None)
        or int(os.getenv("SAMIAN_TIMEOUT", str(DEFAULT_SAMIAN_TIMEOUT)))
    )

    allow_prod = (
        allow_production
        or getattr(django_settings, "SAMIAN_ALLOW_PRODUCTION", False)
        or os.getenv("SAMIAN_ALLOW_PRODUCTION", "False").lower() in ("true", "1")
    )

    return SamianSettings(
        base_url=resolved_base_url,
        username=resolved_username,
        password=resolved_password,
        timeout=resolved_timeout,
        token_scope=token_scope,
        allow_production_server=allow_prod,
    )
