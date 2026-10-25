"""
Core HTTP Client for Samian ERP REST API.

Provides:
- Session management and connection pooling
- Bearer token authentication and transparent 401 re-login retry
- Detection and recovery from 'soft' 401 envelopes
- Generic manual_request for arbitrary endpoints
- Safe generator for paginated endpoints via skip/takeCount
- Helper functions for unpacking responses and building filter payloads
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Iterator
import requests

from .auth import (
    SamianTokenManager,
    ensure_authenticated_token,
    login as auth_login,
    soft_auth_failure,
)
from .config import SamianSettings, get_samian_settings
from .exceptions import (
    SamianAPIError,
    SamianAuthError,
    SamianNetworkError,
    SamianNotFoundError,
)

logger = logging.getLogger(__name__)


def extract_records(payload: Any) -> list[dict[str, Any]]:
    """
    Normalize any Samian list response into a plain list of record dicts.

    Samian returns arrays under various keys depending on the endpoint:
    - {"data": [...]}
    - {"data": {"items": [...]}}
    - {"data": {"rows": [...]}}
    - [{"id": 1, ...}]
    """
    if payload is None:
        return []
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        data = payload.get("data", payload)
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
        if isinstance(data, dict):
            for key in ("items", "rows", "list", "result", "records", "data"):
                inner = data.get(key)
                if isinstance(inner, list):
                    return [r for r in inner if isinstance(r, dict)]
            # Single-record response
            if data and not any(isinstance(v, (list, dict)) for v in data.values()):
                return [data]
            return [data] if data else []
    return []


def extract_total_count(payload: Any) -> int | None:
    """
    Extract the total record count reported by a Samian list response.
    """
    if not isinstance(payload, dict):
        return None
    candidates = [payload]
    data = payload.get("data")
    if isinstance(data, dict):
        candidates.append(data)
    for container in candidates:
        for key in ("totalCount", "totalcount", "total", "count", "recordsTotal"):
            value = container.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
    return None


def samian_filters(*conditions: tuple[str, str, Any]) -> str:
    """
    Build the 'filters' query parameter format required by Samian list endpoints.

    Format: [["field", "op", "value"], "and", ["field2", "op2", "value2"]]
    Example:
        >>> samian_filters(("isactive", "=", True), ("warehouse_id", "=", 1))
        '[["isactive","=",true],"and",["warehouse_id","=",1]]'
    """
    parts: list[Any] = []
    for field, op, value in conditions:
        if isinstance(value, datetime):
            from django.utils import timezone
            if timezone.is_aware(value):
                value = timezone.localtime(value)
            value = value.strftime("%Y-%m-%d %H:%M:%S")
        if parts:
            parts.append("and")
        parts.append([field, op, value])
    return json.dumps(parts, ensure_ascii=False, separators=(",", ":"))


class SamianClient:
    """
    Core HTTP Client for communicating with Samian ERP.
    """

    def __init__(
        self,
        base_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: int | None = None,
        token_scope: str | None = None,
        settings: SamianSettings | None = None,
    ) -> None:
        self.config = settings or get_samian_settings(
            base_url=base_url,
            username=username,
            password=password,
            timeout=timeout,
            token_scope=token_scope,
        )
        self._session = requests.Session()
        self._token: str | None = None

    @property
    def base_url(self) -> str:
        return self.config.base_url

    @property
    def timeout(self) -> int:
        return self.config.timeout

    @property
    def token_scope(self) -> str:
        return self.config.token_scope or "default"

    def login(self, username: str | None = None, password: str | None = None) -> str:
        """
        Authenticate with Samian ERP and cache the resulting Bearer token.
        """
        if username:
            self.config.username = username
        if password:
            self.config.password = password

        self._token = auth_login(self.config, self._session)
        return self._token

    def _ensure_authenticated(self, force_refresh: bool = False) -> str:
        """
        Ensure a valid token is loaded into memory or acquired.
        """
        if not self._token or force_refresh:
            self._token = ensure_authenticated_token(
                self.config, self._session, force_refresh=force_refresh
            )
        return self._token

    def _request(
        self,
        method: str,
        endpoint: str,
        retry_on_401: bool = True,
        **kwargs: Any,
    ) -> requests.Response:
        """
        Execute an HTTP request with Bearer authorization and transparent 401 retry.
        Handles both HTTP 401 status code and Samian's soft 401 (HTTP 200 with code 401).
        """
        token = self._ensure_authenticated()

        headers = kwargs.pop("headers", {}) or {}
        headers.setdefault("Authorization", f"Bearer {token}")
        headers.setdefault("Accept", "application/json, text/plain, */*")
        headers.setdefault("User-Agent", "Mozilla/5.0 (compatible; MongSamianClient/2.0)")
        if self.config.extra_headers:
            headers.update(self.config.extra_headers)

        kwargs.setdefault("timeout", self.config.timeout)

        normalized_endpoint = endpoint.strip().lstrip("/")
        if not normalized_endpoint.startswith("v2/"):
            normalized_endpoint = f"v2/{normalized_endpoint}"

        url = f"{self.config.base_url}/{normalized_endpoint}"

        try:
            resp = self._session.request(method.upper(), url, headers=headers, **kwargs)
        except requests.RequestException as exc:
            logger.error("Samian network error during %s %s: %s", method, url, exc)
            raise SamianNetworkError(
                f"Failed connecting to Samian ERP ({url}): {exc}",
                endpoint=normalized_endpoint,
            ) from exc

        # Check for 401 Unauthorized (standard status or soft failure inside 200)
        is_401 = resp.status_code == 401 or soft_auth_failure(resp)
        if is_401 and retry_on_401:
            logger.warning("Samian 401 detected for %s. Clearing cached token and re-authenticating...", url)
            SamianTokenManager.clear_token(self.config.token_scope)
            self._token = None
            new_token = self.login()
            headers["Authorization"] = f"Bearer {new_token}"
            resp = self._session.request(method.upper(), url, headers=headers, **kwargs)

        return resp

    def manual_request(
        self,
        endpoint: str,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        data: Any = None,
        files: Any = None,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
        raw: bool = False,
    ) -> Any:
        """
        Execute an authenticated request against any Samian endpoint.

        Args:
            endpoint: e.g. "product/productmain", "/v2/wm/stock"
            method: GET, POST, PUT, DELETE
            params: Query parameters dict
            json_body: JSON payload
            data: Form-encoded or raw payload
            files: Multipart files payload
            headers: Optional additional headers
            timeout: Call-specific timeout
            raw: When True, returns requests.Response unparsed

        Returns:
            Parsed JSON dict/list or requests.Response if raw=True
        """
        req_headers = dict(headers or {})
        if json_body is not None:
            req_headers.setdefault("Content-Type", "application/json")

        kwargs: dict[str, Any] = {}
        if params is not None:
            kwargs["params"] = params
        if json_body is not None:
            kwargs["json"] = json_body
        if data is not None:
            kwargs["data"] = data
        if files is not None:
            kwargs["files"] = files
        if timeout is not None:
            kwargs["timeout"] = timeout

        logger.debug("Samian %s %s (params: %s)", method.upper(), endpoint, params)
        resp = self._request(method, endpoint, headers=req_headers, **kwargs)

        if raw:
            return resp

        # Error checks
        if resp.status_code == 404:
            raise SamianNotFoundError(
                f"Samian resource not found: {endpoint}",
                status_code=404,
                response_data=resp.text,
                endpoint=endpoint,
            )

        if resp.status_code >= 400:
            raise SamianAPIError(
                f"Samian {method.upper()} {endpoint} failed with HTTP {resp.status_code}: {resp.text[:500]}",
                status_code=resp.status_code,
                response_data=resp.text,
                endpoint=endpoint,
            )

        if soft_auth_failure(resp):
            raise SamianAuthError(
                f"Samian {method.upper()} {endpoint} rejected token after refresh: {resp.text[:500]}",
                status_code=401,
                response_data=resp.text,
                endpoint=endpoint,
            )

        try:
            return resp.json()
        except ValueError:
            return resp.text

    def iter_paginated(
        self,
        endpoint: str,
        *,
        take_count: int = 100,
        start_skip: int = 0,
        max_records: int | None = None,
        sort: str | None = "createdate",
        sort_type: str = "desc",
        extra_params: dict[str, Any] | None = None,
        method: str = "GET",
    ) -> Iterator[dict[str, Any]]:
        """
        Yield records page-by-page from a Samian list endpoint using skip/takeCount.

        Args:
            endpoint: Samian endpoint (e.g. "product/productmain")
            take_count: Page size (takeCount query param)
            start_skip: Starting offset (skip query param)
            max_records: Maximum total records to yield (None for all)
            sort: Sort column name (e.g. "createdate")
            sort_type: "asc" or "desc"
            extra_params: Additional query parameters (e.g. filters)
            method: HTTP verb ("GET" or "POST")
        """
        skip = start_skip
        yielded = 0

        while True:
            params: dict[str, Any] = {"skip": skip, "takeCount": take_count}
            if sort:
                params["sort"] = sort
                params["sortType"] = sort_type
            if extra_params:
                params.update(extra_params)

            payload = self.manual_request(endpoint, method=method, params=params)
            items = extract_records(payload)

            if not items:
                break

            for item in items:
                yield item
                yielded += 1
                if max_records is not None and yielded >= max_records:
                    return

            if len(items) < take_count:
                break

            skip += take_count


def get_samian_client(
    base_url: str | None = None,
    username: str | None = None,
    password: str | None = None,
    timeout: int | None = None,
    token_scope: str | None = None,
) -> SamianClient:
    """
    Factory helper to instantiate a SamianClient.
    """
    return SamianClient(
        base_url=base_url,
        username=username,
        password=password,
        timeout=timeout,
        token_scope=token_scope,
    )
