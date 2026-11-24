"""
SMS through sms.ir (the panel used the same account through Mong.Sms).

Messages go through approved verify templates: sign-in codes
(SMSIR_OTP_TEMPLATE_ID / SMSIR_OTP_PARAM) and the admins' paid-invoice notice
(SMSIR_INVOICE_TEMPLATE_ID / SMSIR_INVOICE_PARAM). The API key is SMS_KEY in .env.
"""
from __future__ import annotations

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.sms.ir/v1/"


def normalize_mobile(mobile: str) -> str:
    mobile = (mobile or "").strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    if mobile.startswith("+98"):
        return "0" + mobile[3:]
    if mobile.startswith("0098"):
        return "0" + mobile[4:]
    if mobile.startswith("98") and len(mobile) == 12:
        return "0" + mobile[2:]
    if mobile and not mobile.startswith("0"):
        return "0" + mobile
    return mobile


def _log_attempt(mobile: str, template_id: int, accepted: bool, result: str, http_status: int | None = None) -> None:
    # Logging must not change the outcome of sending a message, even inside a transaction.
    from django.db import DatabaseError, transaction
    from apps.adminapi.models import SmsLog

    try:
        with transaction.atomic():
            SmsLog.objects.create(mobile=mobile[:32], template_id=template_id, accepted=accepted,
                                  result=result, http_status=http_status)
    except DatabaseError:
        logger.exception("Could not save SMS log")


def send_verify(mobile: str, template_id: int, params: dict[str, str]) -> bool:
    """Send an approved template (sms.ir verify; no sender line needed). Returns whether sms.ir accepted it."""
    mobile = normalize_mobile(mobile)
    if not settings.SMSIR_API_KEY:
        logger.error("sms.ir: SMS_KEY is not set")
        _log_attempt(mobile, template_id, False, "missing_api_key")
        return False
    payload = {
        "mobile": mobile,
        "templateId": template_id,
        "parameters": [{"name": name, "value": str(value)} for name, value in params.items()],
    }
    try:
        resp = requests.post(
            BASE_URL + "send/verify", json=payload, timeout=15,
            headers={"x-api-key": settings.SMSIR_API_KEY, "Accept": "application/json"},
        )
        body = resp.json() if resp.content else {}
    except (requests.RequestException, ValueError) as exc:
        logger.warning("sms.ir verify failed: %s", exc)
        _log_attempt(mobile, template_id, False, "request_or_response_error")
        return False
    ok = resp.ok and body.get("status") == 1
    if not ok:
        logger.warning("sms.ir verify rejected (template %s): HTTP %s %s", template_id, resp.status_code, body.get("message"))
    _log_attempt(mobile, template_id, ok, "accepted" if ok else "rejected", resp.status_code)
    return ok


def send_otp(mobile: str, code: str) -> bool:
    """Send a sign-in code."""
    return send_verify(mobile, settings.SMSIR_OTP_TEMPLATE_ID, {settings.SMSIR_OTP_PARAM: code})


def send_invoice(mobile: str, number: str) -> bool:
    """Tell an admin a new invoice was paid (template SMSIR_INVOICE_TEMPLATE_ID)."""
    return send_verify(mobile, settings.SMSIR_INVOICE_TEMPLATE_ID, {settings.SMSIR_INVOICE_PARAM: number})
