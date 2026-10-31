"""
Zarinpal payment gateway v4 (request.json, StartPay, verify.json). Amounts in rial.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

TIMEOUT = 30
NO_ANSWER_CODE = -1000
BAD_REPLY_CODE = -1001
MAX_RIAL = 1_000_000_000  # 100 million toman (-41)
UUID_LEN = 36  # a merchant_id

# The error list in Zarinpal's docs (errors.code) -> what we keep on the payment / tell the customer.
ERRORS = {
    -9: "خطای اعتبارسنجی (مرچنت، آدرس بازگشت، توضیحات یا مبلغ نامعتبر)",
    -10: "آی‌پی یا مرچنت کد پذیرنده صحیح نیست",
    -11: "مرچنت کد فعال نیست",
    -12: "تلاش بیش از حد مجاز در زمان کوتاه",
    -13: "محدودیت تراکنش درگاه",
    -14: "آدرس بازگشت با دامنه‌ی ثبت‌شده‌ی درگاه مغایرت دارد",
    -15: "درگاه پرداخت تعلیق شده است",
    -16: "سطح تایید پذیرنده پایین‌تر از نقره‌ای است",
    -17: "محدودیت پذیرنده در سطح آبی",
    -18: "استفاده از درگاه روی این دامنه مجاز نیست",
    -19: "ایجاد تراکنش برای این درگاه ممکن نیست",
    -40: "پارامتر expire_in نامعتبر است",
    -41: "حداکثر مبلغ پرداختی ۱۰۰ میلیون تومان است",
    -50: "مبلغ پرداخت‌شده با مبلغ فاکتور یکسان نیست",
    -51: "پرداخت ناموفق",
    -52: "خطای غیرمنتظره در زرین‌پال",
    -53: "پرداخت متعلق به این مرچنت کد نیست",
    -54: "اتوریتی نامعتبر است",
    -55: "تراکنش یافت نشد",
}
# Request errors worth showing to the customer as they are; others get a general message.
CUSTOMER_FACING = {-9, -41}


@dataclass
class Result:
    code: int
    message: str
    authority: str = ""
    ref_id: str = ""
    card_pan: str = ""
    raw: str = ""

    @property
    def ok(self) -> bool:
        return self.code == 100

    @property
    def already_verified(self) -> bool:
        return self.code == 101


def _base() -> str:
    return "https://sandbox.zarinpal.com/pg/" if settings.ZARINPAL_SANDBOX else "https://payment.zarinpal.com/pg/"


def start_url(authority: str) -> str:
    """The payment page; pay.mong.ir (a CNAME to Zarinpal) is the branded one, not on the sandbox."""
    branded = settings.ZARINPAL_STARTPAY_BASE_URL
    return f"{branded if branded and not settings.ZARINPAL_SANDBOX else _base() + 'StartPay'}/{authority}"


def _post(path: str, body: dict) -> Result:
    try:
        resp = requests.post(f"{_base()}{path}", json=body, timeout=TIMEOUT, headers={"Accept": "application/json"})
    except requests.RequestException as exc:
        logger.warning("zarinpal %s: no answer (%s)", path, type(exc).__name__)
        return Result(NO_ANSWER_CODE, "ارتباط با زرین‌پال برقرار نشد.")
    try:
        reply = resp.json()
    except ValueError:
        return Result(BAD_REPLY_CODE, "پاسخ نامعتبر از زرین‌پال", raw=resp.text[:2000])
    # Success: {"data": {"code": 100, "authority": ...}, "errors": []}. Failure: {"data": [], "errors": {"code": -9, ...}}
    data = reply.get("data") if isinstance(reply.get("data"), dict) else {}
    errors = reply.get("errors") if isinstance(reply.get("errors"), dict) else {}
    code = data.get("code", errors.get("code"))
    if not isinstance(code, int):
        return Result(BAD_REPLY_CODE, "پاسخ نامعتبر از زرین‌پال", raw=resp.text[:2000])
    message = ERRORS.get(code, str(errors.get("message") or data.get("message") or "خطای نامشخص"))
    return Result(code, message, str(data.get("authority") or ""), str(data.get("ref_id") or ""),
                  str(data.get("card_pan") or ""), resp.text[:2000])


def request(merchant_id: str, amount: int, description: str, callback_url: str, mobile: str, order_id: str) -> Result:
    # auto_verify off: Zarinpal settles only on our verify, so an order that is never recorded is refunded.
    metadata: dict = {"auto_verify": False, "order_id": order_id}
    if len(mobile) == 11 and mobile.startswith("09"):
        metadata["mobile"] = mobile
    return _post("v4/payment/request.json", {"merchant_id": merchant_id, "amount": amount, "currency": "IRR",
                                             "description": description, "callback_url": callback_url, "metadata": metadata})


def verify(merchant_id: str, amount: int, authority: str) -> Result:
    return _post("v4/payment/verify.json", {"merchant_id": merchant_id, "amount": amount, "authority": authority})
