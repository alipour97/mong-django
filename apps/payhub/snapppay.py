"""
SnappPay API v2.1 (snappay/Ordinary Documents/Rest API Documents). Amounts in rial.

Every call answers a Reply, never raises: a timeout or a non-JSON body is an
answer too, and what to do about it is decided in service.py. Each call gets a
fresh JWT because the document asks not to cache it. Every call, whatever came
of it, is kept in SnappLog; a failure to keep it never touches the payment.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass, field

import requests
from django.conf import settings

from .models import SnappLog

logger = logging.getLogger(__name__)

TIMEOUT = 30  # document, "Verify request handling"
NO_ANSWER = "پاسخی از اسنپ‌پی دریافت نشد."
SECRETS = {"password", "access_token", "refresh_token"}


@dataclass
class Reply:
    """{"successful": true, "response": {...}} or {"successful": false, "errorData": {...}}."""

    http: int = 0
    body: dict = field(default_factory=dict)
    raw: str = ""
    no_answer: bool = False

    @property
    def ok(self) -> bool:
        return 200 <= self.http < 300 and self.body.get("successful") is True

    def value(self, name: str):
        response = self.body.get("response")
        return response.get(name) if isinstance(response, dict) else None

    @property
    def error_data(self) -> dict:
        data = self.body.get("errorData")
        return data if isinstance(data, dict) else {}

    @property
    def code(self) -> int | None:
        code = self.error_data.get("errorCode")
        return code if isinstance(code, int) else None

    @property
    def message(self) -> str:
        if self.no_answer:
            return NO_ANSWER
        return str(self.error_data.get("message") or self.body.get("message") or "خطا در ارتباط با اسنپ‌پی.")

    @property
    def transaction_status(self) -> str | None:
        """transaction-status in an error's data (error list, code 1011), upper case like Get Payment Status."""
        data = self.error_data.get("data")
        for source in (data if isinstance(data, dict) else {}, self.error_data):
            for key, value in source.items():
                if key.lower().replace("_", "-") in ("transaction-status", "transactionstatus") and value:
                    return str(value).upper()
        return None

    @property
    def status(self) -> str | None:
        """status of a Get Payment Status answer."""
        value = self.value("status")
        return str(value).upper() if value else None

    def for_caller(self) -> str:
        """SnappPay's own JSON, or one of the same shape, for the old site."""
        if not self.no_answer and self.raw.lstrip().startswith("{"):
            return self.raw
        return json.dumps({"successful": False, "errorData": {"errorCode": -1, "message": self.message, "data": None}},
                          ensure_ascii=False)

    def brief(self) -> str:
        return f"http={self.http} {self.raw[:500]}"


def configured() -> bool:
    return bool(settings.SNAPPAY_BASE_URL and settings.SNAPPAY_CLIENT_ID and settings.SNAPPAY_CLIENT_SECRET
                and settings.SNAPPAY_USERNAME and settings.SNAPPAY_PASSWORD)


def format_mobile(mobile: str | None) -> str | None:
    """+989121234567, the only form SnappPay takes (error 1005)."""
    digits = "".join(ch for ch in str(mobile or "") if ch in "0123456789")
    if digits.startswith("0098"):
        digits = digits[4:]
    elif digits.startswith("98") and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = digits[1:]
    return f"+98{digits}" if len(digits) == 10 and digits.startswith("9") else None


def _hidden(fields: dict) -> dict:
    return {key: "***" if key in SECRETS else value for key, value in fields.items()}


def _keep(method: str, path: str, sent: dict, started: float, reply: Reply, text: str = "", error: str = "") -> None:
    """Headers stay out: they hold the client secret and the JWT."""
    answer = reply.body.get("response")
    answer = answer if isinstance(answer, dict) else {}
    try:
        SnappLog.objects.create(
            method=method, path=path, request=_hidden(sent), http_status=reply.http or None,
            successful=reply.ok or bool(reply.body.get("access_token")),  # the OAuth answer has no "successful"
            response=json.dumps(_hidden(reply.body), ensure_ascii=False) if SECRETS & reply.body.keys() else text,
            error=error, duration_ms=int((time.monotonic() - started) * 1000),
            payment_token=str(sent.get("paymentToken") or answer.get("paymentToken") or "")[:255],
            transaction_id=str(sent.get("transactionId") or answer.get("transactionId") or "")[:64],
        )
    except Exception:
        logger.exception("snapppay %s: could not keep the log", path)


def _send(method: str, path: str, headers: dict, timeout: int = TIMEOUT, **kwargs) -> Reply:
    sent = {**(kwargs.get("params") or {}), **(kwargs.get("data") or {}), **(kwargs.get("json") or {})}
    started = time.monotonic()
    try:
        resp = requests.request(method, f"{settings.SNAPPAY_BASE_URL}{path}", headers=headers, timeout=timeout, **kwargs)
    except requests.RequestException as exc:
        logger.warning("snapppay %s: no answer (%s)", path, type(exc).__name__)
        reply = Reply(no_answer=True)
        _keep(method, path, sent, started, reply, error=type(exc).__name__)
        return reply
    try:
        body = resp.json()
    except ValueError:  # e.g. the "Access Denied" page of a source IP that is not whitelisted
        body = {}
    reply = Reply(http=resp.status_code, body=body if isinstance(body, dict) else {}, raw=resp.text[:4000])
    _keep(method, path, sent, started, reply, resp.text)
    return reply


def _access_token() -> tuple[str, Reply]:
    basic = base64.b64encode(f"{settings.SNAPPAY_CLIENT_ID}:{settings.SNAPPAY_CLIENT_SECRET}".encode()).decode()
    reply = _send("POST", "/api/online/v1/oauth/token", {"Authorization": f"Basic {basic}"},
                  data={"grant_type": "password", "scope": "online-merchant", "username": settings.SNAPPAY_USERNAME,
                        "password": settings.SNAPPAY_PASSWORD})
    return str(reply.body.get("access_token") or ""), reply


def _call(method: str, path: str, **kwargs) -> Reply:
    token, failed = _access_token()
    if not token:
        logger.warning("snapppay access token refused: http=%s", failed.http)
        return Reply(http=failed.http, body=failed.body, no_answer=failed.no_answer, raw="")
    return _send(method, path, {"Authorization": f"Bearer {token}"}, **kwargs)


def eligible(amount: int) -> Reply:
    # paymentMethodTypes stays out: the customer sees every method active for them.
    return _call("GET", "/api/online/offer/v1/eligible", params={"amount": amount})


def payment_token(body: dict) -> Reply:
    return _call("POST", "/api/online/payment/v1/token", json=body)


def verify(token: str) -> Reply:
    return _call("POST", "/api/online/payment/v1/verify", json={"paymentToken": token})


def settle(token: str) -> Reply:
    return _call("POST", "/api/online/payment/v1/settle", json={"paymentToken": token})


def revert(token: str) -> Reply:
    return _call("POST", "/api/online/payment/v1/revert", json={"paymentToken": token})


def cancel(token: str) -> Reply:
    return _call("POST", "/api/online/payment/v1/cancel", json={"paymentToken": token})


def update(body: dict) -> Reply:
    return _call("POST", "/api/online/payment/v1/update", json=body)


def status(token: str) -> Reply:
    return _call("GET", "/api/online/payment/v1/status", params={"paymentToken": token})
