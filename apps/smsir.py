"""
SMS through sms.ir (the panel used the same account through Mong.Sms).

One-time codes go through the approved verify template (SMSIR_OTP_TEMPLATE_ID,
parameter SMSIR_OTP_PARAM); the API key is SMS_KEY in .env.
"""
from __future__ import annotations

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.sms.ir/v1/"


def normalize_mobile(mobile: str) -> str:
    mobile = (mobile or "").strip()
    if mobile.startswith("+98"):
        return "0" + mobile[3:]
    if mobile.startswith("0098"):
        return "0" + mobile[4:]
    if mobile.startswith("98") and len(mobile) == 12:
        return "0" + mobile[2:]
    if mobile and not mobile.startswith("0"):
        return "0" + mobile
    return mobile


def send_otp(mobile: str, code: str) -> bool:
    """Send a sign-in code. Returns whether sms.ir accepted it."""
    if not settings.SMSIR_API_KEY:
        logger.error("sms.ir: SMS_KEY is not set")
        return False
    payload = {
        "mobile": normalize_mobile(mobile),
        "templateId": settings.SMSIR_OTP_TEMPLATE_ID,
        "parameters": [{"name": settings.SMSIR_OTP_PARAM, "value": code}],
    }
    try:
        resp = requests.post(
            BASE_URL + "send/verify", json=payload, timeout=15,
            headers={"x-api-key": settings.SMSIR_API_KEY, "Accept": "application/json"},
        )
        body = resp.json() if resp.content else {}
    except (requests.RequestException, ValueError) as exc:
        logger.warning("sms.ir verify failed: %s", exc)
        return False
    ok = resp.ok and body.get("status") == 1
    if not ok:
        logger.warning("sms.ir verify rejected: HTTP %s %s", resp.status_code, body.get("message"))
    return ok


def send_text(mobiles: list[str], text: str) -> bool:
    """Plain text to one or more mobiles from SMSIR_LINE_NUMBER (sms.ir bulk send). Returns whether it was accepted."""
    mobiles = [normalize_mobile(m) for m in mobiles if m]
    if not mobiles:
        return True
    if not settings.SMSIR_API_KEY or not settings.SMSIR_LINE_NUMBER:
        logger.error("sms.ir: SMS_KEY or SMSIR_LINE_NUMBER is not set")
        return False
    payload = {"lineNumber": int(settings.SMSIR_LINE_NUMBER), "messageText": text, "mobiles": mobiles}
    try:
        resp = requests.post(
            BASE_URL + "send/bulk", json=payload, timeout=15,
            headers={"x-api-key": settings.SMSIR_API_KEY, "Accept": "application/json"},
        )
        body = resp.json() if resp.content else {}
    except (requests.RequestException, ValueError) as exc:
        logger.warning("sms.ir bulk failed: %s", exc)
        return False
    ok = resp.ok and body.get("status") == 1
    if not ok:
        logger.warning("sms.ir bulk rejected: HTTP %s %s", resp.status_code, body.get("message"))
    return ok
