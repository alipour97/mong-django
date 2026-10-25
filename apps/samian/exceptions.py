"""
Custom Exception Classes for Samian ERP API Client.
"""
from __future__ import annotations
from typing import Any


class SamianAPIError(Exception):
    """
    Base exception for all Samian ERP API errors.
    """
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response_data: Any = None,
        endpoint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response_data = response_data
        self.endpoint = endpoint

    def __str__(self) -> str:
        parts = [self.message]
        if self.status_code is not None:
            parts.append(f"(HTTP {self.status_code})")
        if self.endpoint:
            parts.append(f"[Endpoint: {self.endpoint}]")
        return " ".join(parts)


class SamianAuthError(SamianAPIError):
    """
    Raised on authentication failure, invalid credentials, or expired tokens.
    """


class SamianUploadError(SamianAPIError):
    """
    Raised on file/photo/attachment upload failures to Samian ERP.
    """


class SamianValidationError(SamianAPIError):
    """
    Raised when parameters, payloads, or API responses fail validation.
    """


class SamianNetworkError(SamianAPIError):
    """
    Raised on connection errors, DNS lookup failures, or network timeouts.
    """


class SamianNotFoundError(SamianAPIError):
    """
    Raised when a requested resource (product, color, transaction) is not found (HTTP 404).
    """
