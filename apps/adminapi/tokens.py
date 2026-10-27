"""
Admin access tokens: HS512 JWTs carrying the admin's id, valid ADMIN_TOKEN_MINUTES
(10 hours, like the old panel). A refresh token, stored hashed on AdminUser,
gets a fresh access token while the current one is still valid.
"""
from __future__ import annotations

import hashlib
from datetime import timedelta

import jwt
from django.conf import settings
from django.utils import timezone

ISSUER = "mong-admin"
ALGORITHM = "HS512"


def _key() -> bytes:
    # 64 bytes, the size HS512 wants, derived from SECRET_KEY.
    return hashlib.sha512((settings.SECRET_KEY + ":admin-api").encode()).digest()


def issue(user, minutes: int | None = None) -> dict:
    """The token payload the panel stores (AuthResault in the frontend)."""
    minutes = minutes or settings.ADMIN_TOKEN_MINUTES
    now = timezone.now()
    expires = now + timedelta(minutes=minutes)
    token = jwt.encode(
        {"sub": str(user.pk), "iss": ISSUER, "iat": int(now.timestamp()), "nbf": int(now.timestamp()),
         "exp": int(expires.timestamp())},
        _key(), algorithm=ALGORITHM,
    )
    return {
        "token": token,
        "tokenType": "Bearer",
        "issuedAt": now.isoformat(),
        "expires": expires.isoformat(),
        "expiresMinutes": float(minutes),
    }


def user_id(token: str) -> int | None:
    """The admin id in a valid, unexpired token, else None."""
    try:
        claims = jwt.decode(token, _key(), algorithms=[ALGORITHM], issuer=ISSUER, options={"require": ["exp", "sub"]})
    except jwt.PyJWTError:
        return None
    return int(claims["sub"]) if str(claims.get("sub", "")).isdigit() else None
