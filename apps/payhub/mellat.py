"""Behpardakht IPG 1.38 (docs/behpardakht/ipg-tech-doc.pdf).

SOAP 1.1, case-sensitive parameters, amounts already in whole rial. The
official development host is the default; never fall back to production.
Credentials and SOAP bodies are deliberately absent from logs/events.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from xml.etree import ElementTree as ET

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
NAMESPACE = "http://interfaces.core.sw.bps.com/"
TEST_BASE = "https://pgw.dev.bpmellat.ir/pgwchannel"
LIVE_BASE = "https://bpm.shaparak.ir/pgwchannel"
TIMEOUT = 30
NO_ANSWER = -1000
BAD_REPLY = -1001
LONG_MAX = 2**63 - 1

ERRORS = {
    0: "عملیات موفق بود.",
    11: "شماره کارت نامعتبر است.",
    12: "موجودی کافی نیست.",
    17: "پرداخت توسط کاربر لغو شد.",
    21: "پذیرنده نامعتبر است.",
    23: "خطای امنیتی در درگاه پرداخت.",
    24: "اطلاعات کاربری پذیرنده نامعتبر است.",
    25: "مبلغ نامعتبر است.",
    31: "پاسخ درگاه پرداخت نامعتبر است.",
    32: "فرمت اطلاعات ارسالی نامعتبر است.",
    34: "خطای سیستمی در درگاه پرداخت.",
    35: "تاریخ نامعتبر است.",
    41: "شماره درخواست تکراری است.",
    42: "تراکنش خرید یافت نشد.",
    43: "تراکنش قبلاً تأیید شده است.",
    44: "درخواست تأیید یافت نشد.",
    45: "تراکنش قبلاً تسویه شده است.",
    46: "تراکنش تسویه نشده است.",
    47: "تراکنش تسویه یافت نشد.",
    48: "مبلغ تراکنش برگشت داده شده است.",
    51: "تراکنش تکراری است.",
    54: "تراکنش مرجع موجود نیست.",
    55: "تراکنش نامعتبر است.",
    61: "خطا در واریز وجه.",
    62: "دامنه آدرس بازگشت با دامنه ثبت‌شده پذیرنده مطابقت ندارد.",
    NO_ANSWER: "ارتباط با به‌پرداخت ملت برقرار نشد.",
    BAD_REPLY: "پاسخ نامعتبر از به‌پرداخت ملت.",
}


@dataclass
class Result:
    code: int
    authority: str = ""

    @property
    def message(self) -> str:
        return ERRORS.get(self.code, f"خطای درگاه به‌پرداخت ملت (کد {self.code}).")


def positive_long(value) -> bool:
    return bool(re.fullmatch(r"[0-9]{1,19}", str(value))) and 0 < int(value) <= LONG_MAX


def config(gateway=None) -> dict:
    from apps.website.models import BankGateway

    if gateway is None:
        gateway = BankGateway.objects.filter(bank__key="mellat", is_deleted=False, removed_at__isnull=True).order_by("-id").first()
    panel = gateway is not None and gateway.mellat_sandbox is not None
    return {
        "gateway": gateway,
        "terminal": (gateway.terminal_id if gateway else "") or settings.MELLAT_TERMINAL_ID,
        "username": gateway.mellat_username if panel else settings.MELLAT_USERNAME,
        "password": gateway.mellat_password if panel else settings.MELLAT_PASSWORD,
        "sandbox": gateway.mellat_sandbox if panel else settings.MELLAT_SANDBOX,
        "source": "panel" if panel else "environment",
    }


def terminal_id() -> str:
    return config()["terminal"]


def configured() -> bool:
    values = config()
    return bool(positive_long(values["terminal"]) and values["username"] and values["password"])


def base(sandbox: bool) -> str:
    return TEST_BASE if sandbox else LIVE_BASE


def _post(method: str, terminal: str, sandbox: bool, fields: dict, credentials=None) -> Result:
    envelope = ET.Element(f"{{{SOAP}}}Envelope")
    body = ET.SubElement(envelope, f"{{{SOAP}}}Body")
    operation = ET.SubElement(body, f"{{{NAMESPACE}}}{method}")
    username, password = credentials if credentials is not None else (settings.MELLAT_USERNAME, settings.MELLAT_PASSWORD)
    params = {"terminalId": terminal, "userName": username, "userPassword": password, **fields}
    for name, value in params.items():
        ET.SubElement(operation, name).text = str(value)
    try:
        response = requests.post(
            f"{base(sandbox)}/services/pgw", data=ET.tostring(envelope, encoding="utf-8", xml_declaration=True),
            headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": '""'},
            timeout=TIMEOUT, allow_redirects=False,
        )
    except requests.RequestException as exc:
        logger.warning("mellat %s: %s", method, type(exc).__name__)
        return Result(NO_ANSWER)
    content = response.content

    def bad_reply(reason: str) -> Result:
        logger.warning("mellat %s: invalid response reason=%s http=%s sandbox=%s bytes=%s",
                       method, reason, response.status_code, sandbox, len(content))
        return Result(BAD_REPLY)

    if not 200 <= response.status_code < 300:
        return bad_reply("http_status")
    # The service only returns small UTF-8 XML documents. Reject DTD/entity
    # declarations (including UTF-16 input) before parsing external input.
    if (len(content) > 65536 or b"\x00" in content or b"<!DOCTYPE" in content.upper()
            or b"<!ENTITY" in content.upper()):
        return bad_reply("unsupported_xml")
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return bad_reply("malformed_xml")
    if root.find(f"{{{SOAP}}}Body/{{{SOAP}}}Fault") is not None:
        return bad_reply("soap_fault")
    reply = root.find(f"{{{SOAP}}}Body/{{{NAMESPACE}}}{method}Response")
    if reply is None:
        return bad_reply("missing_operation_response")
    values = [child.text or "" for child in reply if child.tag in ("return", f"{{{NAMESPACE}}}return")]
    if len(values) != 1:
        return bad_reply("missing_or_duplicate_return")
    parts = values[0].strip().split(",")
    if not re.fullmatch(r"[0-9]{1,4}", parts[0]):
        return bad_reply("invalid_result_code")
    code = int(parts[0])
    if method == "bpPayRequest" and code == 0:
        if len(parts) != 2 or not re.fullmatch(r"[A-Za-z0-9]{1,255}", parts[1].strip()):
            return bad_reply("invalid_ref_id")
        return Result(code, parts[1].strip())
    return Result(code) if len(parts) == 1 else bad_reply("unexpected_result_fields")


def request(terminal: str, sandbox: bool, order_id: str, amount: int, callback: str, description: str, credentials=None) -> Result:
    now = timezone.localtime()
    return _post("bpPayRequest", terminal, sandbox, {
        "orderId": order_id, "amount": amount, "localDate": now.strftime("%Y%m%d"),
        "localTime": now.strftime("%H%M%S"), "additionalData": description[:1000],
        "callBackUrl": callback, "payerId": "0",
    }, credentials)


def transaction(method: str, record) -> Result:
    """Use only the original terminal, environment, sale id and reference."""
    if method not in ("bpVerifyRequest", "bpSettleRequest", "bpInquiryRequest", "bpReversalRequest"):
        raise ValueError("Unsupported Mellat operation")
    values = config(record.mellat_gateway) if record.mellat_gateway_id else None
    return _post(method, record.merchant_id, record.mellat_sandbox, {
        "orderId": record.gateway_transaction_id, "saleOrderId": record.gateway_transaction_id,
        "saleReferenceId": record.ref_id,
    }, (values["username"], values["password"]) if values else None)
