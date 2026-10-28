"""
Paying a pre-invoice (Bank/*), site side: Zarinpal and SnappPay.

    GET  Bank/GetGateways                                  -> [{id, name, iconUrl, gatewayKey}] (active gateways from the panel)
    GET  Bank/PayInvoiceById?InvoiceId=&ShippingMethodId=&GateWayId=   -> the gateway page URL
    GET  Bank/SnappPayEligible?Amount=                     -> {eligible, title_message, description}
    GET  Bank/GiftCardPayInvoiceById?InvoiceId=&ShippingMethodId=      -> confirmation URL (only a zero-amount invoice)
    GET  Bank/ZarinpalCallback?Authority=&Status=          (Zarinpal returns the customer here)
    POST Bank/SnappPayCallback  transactionId, state, amount (SnappPay posts the customer here)

Each pay request is an InvoicePayment row. On return the payment is verified
(and settled, for SnappPay) once; then the invoice is successful and the
customer lands on /order-confirmation?success=...&InvoiceId=...&TrackingToken=...
like before. A paid invoice is not yet sent to Samian: that is the write phase
(Invoice.samian_transaction_id stays empty until then).
"""
from __future__ import annotations

import base64
import logging
import secrets
import threading
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.db import transaction
from django.http import HttpResponseRedirect
from django.utils import timezone

from apps import smsir
from apps.website.models import BankGateway, Invoice, InvoicePayment

from apps.adminapi.paging import to_int

from .account import CustomerView, answer
from .orders import S, assign_number
from .views import PublicView

logger = logging.getLogger(__name__)

ZARINPAL, SNAPPPAY = "zarinpal", "snapppay"
SUPPORTED = (ZARINPAL, SNAPPPAY)
TIMEOUT = 30
UUID_LEN = 36  # a Zarinpal merchant_id


def _active(key: str) -> BankGateway | None:
    """The gateway switched on in the panel's configs page for this bank key."""
    return BankGateway.objects.filter(bank__key=key, is_deleted=False).select_related("bank").order_by("-id").first()


def zarinpal_merchant() -> str:
    """The panel gateway's merchant id, else ZARINPAL_KEY from .env."""
    g = _active(ZARINPAL)
    for value in ((g.merchant, g.merchant_key, g.terminal_id) if g else ()):
        if len((value or "").strip()) == UUID_LEN:
            return value.strip()
    return settings.ZARINPAL_MERCHANT_ID


def _enabled(key: str) -> bool:
    if not _active(key):
        return False
    if key == ZARINPAL:
        return bool(zarinpal_merchant())
    # SnappPay's OAuth client, user and API address stay in .env.
    return bool(settings.SNAPPAY_BASE_URL and settings.SNAPPAY_CLIENT_ID and settings.SNAPPAY_USERNAME)


def _icon_url(b64: str) -> str:
    if not b64:
        return ""
    head = base64.b64decode(b64[:120])  # a 4-aligned prefix is enough to tell the type
    kind = "svg+xml" if b"<svg" in head or b"<?xml" in head else "jpeg" if head[:2] == b"\xff\xd8" else "png"
    return f"data:image/{kind};base64,{b64}"


def _confirmation(success: bool, inv: Invoice | None, token: str = "") -> str:
    """The site's result page; it shows InvoiceId as the invoice number."""
    shown = (inv.number or inv.id) if inv else ""
    query = {"success": "true" if success else "false", "TrackingToken": token, "InvoiceId": shown}
    return f"{settings.SITE_URL}/order-confirmation?{urlencode(query)}"


def _callback(name: str) -> str:
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/api/v1/Bank/{name}"


class GatewaysView(CustomerView):
    def get(self, request):
        out = []
        for key in SUPPORTED:
            if _enabled(key):
                g = _active(key)
                out.append({"id": g.id, "name": g.bank.name, "iconUrl": _icon_url(g.bank.icon), "gatewayKey": key})
        return answer(out)


def _payable_invoice(request, invoice_id) -> Invoice | None:
    return request.user.invoices.filter(id=invoice_id, state=S.PRE_INVOICE, is_deleted=False).first() if str(invoice_id or "").isdigit() else None


def _mark_paid(inv: Invoice) -> None:
    with transaction.atomic():
        inv.state, inv.paid_at = S.SUCCESSFUL, timezone.now()
        inv.save(update_fields=["state", "paid_at", "last_modified"])
        number = assign_number(inv)
    transaction.on_commit(lambda: _notify_admins(number))


def _notify_admins(number: str) -> None:
    """Texts the admins who have "send invoice SMS" on (invoice template, one SMS each), in the background."""
    from apps.adminapi.models import AdminUser

    mobiles = list(AdminUser.objects.filter(is_deleted=False, is_active=True, send_invoice_sms=True)
                   .exclude(cellphone="").values_list("cellphone", flat=True))

    def send():
        for mobile in mobiles:
            smsir.send_invoice(mobile, number)

    if mobiles:
        threading.Thread(target=send, daemon=True).start()


# -----------------------------------------------------------------------------
# Zarinpal (https://payment.zarinpal.com/pg/v4/payment/{request,verify}.json, amounts in rial)
# -----------------------------------------------------------------------------
# The error list in Zarinpal's docs (errors.code) -> what we keep on the payment / tell the customer.
ZARINPAL_ERRORS = {
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
ZARINPAL_MAX_RIAL = 1_000_000_000  # 100 million toman (-41)
# Request errors worth showing to the customer as they are; others get a general message.
CUSTOMER_FACING = {-9, -41}


class GatewayError(Exception):
    def __init__(self, message: str, customer_message: str | None = None):
        super().__init__(message)
        self.customer_message = customer_message


def zarinpal_error(body: dict) -> tuple[int | None, str]:
    """(code, Persian description) of a Zarinpal error reply."""
    err = body.get("errors") if isinstance(body.get("errors"), dict) else {}
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    code = err.get("code", data.get("code"))
    return code, ZARINPAL_ERRORS.get(code, str(err.get("message") or data.get("message") or "خطای نامشخص"))


def _zarinpal_base() -> str:
    return "https://sandbox.zarinpal.com" if settings.ZARINPAL_SANDBOX else "https://payment.zarinpal.com"


def zarinpal_request(inv: Invoice) -> str:
    """Creates the payment; returns the StartPay URL."""
    if inv.payable_amount > ZARINPAL_MAX_RIAL:
        raise GatewayError("over zarinpal limit", ZARINPAL_ERRORS[-41])
    body = {
        "merchant_id": zarinpal_merchant(), "amount": inv.payable_amount, "currency": "IRR",
        "callback_url": _callback("ZarinpalCallback"), "description": f"سفارش {inv.id} مانگ",
        "metadata": {"mobile": inv.customer.cellphone, "order_id": str(inv.id)},
    }
    resp = requests.post(f"{_zarinpal_base()}/pg/v4/payment/request.json", json=body, timeout=TIMEOUT,
                         headers={"Accept": "application/json"})
    reply = resp.json() or {}
    data = reply.get("data") if isinstance(reply.get("data"), dict) else {}
    if data.get("code") != 100 or not data.get("authority"):
        code, message = zarinpal_error(reply)
        raise GatewayError(f"zarinpal request {code}: {message}", message if code in CUSTOMER_FACING else None)
    InvoicePayment.objects.create(invoice=inv, gateway=ZARINPAL, amount=inv.payable_amount, authority=data["authority"])
    return f"{_zarinpal_base()}/pg/StartPay/{data['authority']}"


def zarinpal_verify(payment: InvoicePayment) -> dict:
    body = {"merchant_id": zarinpal_merchant(), "amount": payment.amount, "authority": payment.authority}
    resp = requests.post(f"{_zarinpal_base()}/pg/v4/payment/verify.json", json=body, timeout=TIMEOUT,
                         headers={"Accept": "application/json"})
    return resp.json() or {}


# -----------------------------------------------------------------------------
# SnappPay (OAuth password grant, then token -> verify -> settle; amounts in rial)
# -----------------------------------------------------------------------------
def _snapp_token() -> str:
    basic = base64.b64encode(f"{settings.SNAPPAY_CLIENT_ID}:{settings.SNAPPAY_CLIENT_SECRET}".encode()).decode()
    resp = requests.post(
        f"{settings.SNAPPAY_BASE_URL}/api/online/v1/oauth/token", timeout=TIMEOUT,
        headers={"Authorization": f"Basic {basic}"},
        data={"grant_type": "password", "scope": "online-merchant", "username": settings.SNAPPAY_USERNAME,
              "password": settings.SNAPPAY_PASSWORD},
    )
    token = (resp.json() or {}).get("access_token")
    if not token:
        raise RuntimeError(f"snapppay token: {resp.status_code}")
    return token


def _snapp(method: str, path: str, **kwargs) -> dict:
    resp = requests.request(method, f"{settings.SNAPPAY_BASE_URL}{path}", timeout=TIMEOUT,
                            headers={"Authorization": f"Bearer {_snapp_token()}"}, **kwargs)
    return resp.json() or {}


def snapp_eligible(amount: int) -> dict:
    return _snapp("GET", "/api/online/offer/v1/eligible", params={"amount": amount})


def snapp_request(inv: Invoice) -> str:
    lines = list(inv.lines.all())
    items = [{"amount": ln.price_after_reduction, "category": "پوشاک", "count": int(ln.qty), "id": ln.variant_id,
              "name": ln.name[:100], "commissionType": 100} for ln in lines]
    goods = sum(i["amount"] * i["count"] for i in items)
    transaction_id = f"M{inv.id}{secrets.token_hex(2).upper()}"[:10]
    body = {
        "amount": inv.payable_amount, "discountAmount": inv.deduction_amount, "externalSourceAmount": 0,
        "mobile": "+98" + inv.customer.cellphone[1:], "returnURL": _callback("SnappPayCallback"),
        "transactionId": transaction_id,
        "cartList": [{"cartId": inv.id, "cartItems": items, "isShipmentIncluded": False, "isTaxIncluded": True,
                      "shippingAmount": inv.delivery_amount, "taxAmount": 0, "totalAmount": goods + inv.delivery_amount}],
    }
    data = _snapp("POST", "/api/online/payment/v1/token", json=body)
    res = data.get("response") or {}
    if not data.get("successful") or not res.get("paymentToken"):
        raise RuntimeError(f"snapppay payment token: {str(data)[:300]}")
    InvoicePayment.objects.create(invoice=inv, gateway=SNAPPPAY, amount=inv.payable_amount, authority=res["paymentToken"],
                                  transaction_id=transaction_id)
    return res["paymentPageUrl"]


# -----------------------------------------------------------------------------
# Views
# -----------------------------------------------------------------------------
class PayView(CustomerView):
    def get(self, request):
        q = request.query_params
        inv = _payable_invoice(request, q.get("InvoiceId"))
        if not inv:
            return answer(None, 404, "فاکتور یافت نشد")
        if inv.payable_amount <= 0:
            return answer(None, 400, "این فاکتور مبلغی برای پرداخت ندارد.")
        g = BankGateway.objects.filter(id=to_int(q.get("GateWayId")), is_deleted=False).select_related("bank").first()
        key = g.bank.key if g else None
        if key not in SUPPORTED or not _enabled(key):
            return answer(None, 400, "درگاه پرداخت انتخاب‌شده فعال نیست.")
        try:
            url = zarinpal_request(inv) if key == ZARINPAL else snapp_request(inv)
        except GatewayError as exc:
            logger.warning("pay request refused for invoice %s: %s", inv.id, exc)
            return answer(None, 502, exc.customer_message or "اتصال به درگاه پرداخت برقرار نشد. لطفا دوباره تلاش کنید.")
        except Exception:
            logger.exception("pay request failed for invoice %s", inv.id)
            return answer(None, 502, "اتصال به درگاه پرداخت برقرار نشد. لطفا دوباره تلاش کنید.")
        return answer(url, message="در حال انتقال به درگاه پرداخت")


class SnappEligibleView(CustomerView):
    def get(self, request):
        amount = request.query_params.get("Amount")
        if not _enabled(SNAPPPAY) or not str(amount or "").isdigit():
            return answer({"eligible": False, "title_message": "", "description": ""})
        try:
            res = snapp_eligible(int(amount)).get("response") or {}
        except Exception:
            logger.exception("snapppay eligible failed")
            res = {}
        return answer({"eligible": bool(res.get("eligible")), "title_message": res.get("title_message", ""),
                       "description": res.get("description", "")})


class ZeroAmountView(CustomerView):
    """A pre-invoice with nothing to pay (once gift cards cover it) is finished without a gateway."""

    def get(self, request):
        inv = _payable_invoice(request, request.query_params.get("InvoiceId"))
        if not inv:
            return answer(None, 404, "فاکتور یافت نشد")
        if inv.payable_amount > 0:
            return answer(None, 400, "این فاکتور باید از درگاه پرداخت شود.")
        _mark_paid(inv)
        return answer(_confirmation(True, inv), message="پرداخت موفق با کارت هدیه.")


def _finish(payment: InvoicePayment, success: bool, reference: str = "", card: str = "", error: str = "") -> None:
    with transaction.atomic():
        payment.is_success, payment.reference, payment.card_pan = success, reference, card
        payment.error_message, payment.verified_at = error[:2000], timezone.now()
        payment.save()
        if success and payment.invoice.state == S.PRE_INVOICE:
            _mark_paid(payment.invoice)


class ZarinpalCallbackView(PublicView):
    def get(self, request):
        authority = request.query_params.get("Authority", "")
        payment = InvoicePayment.objects.select_related("invoice").filter(gateway=ZARINPAL, authority=authority).first()
        if not payment:
            return HttpResponseRedirect(_confirmation(False, None))
        if payment.verified_at:  # already handled (refresh or a second visit)
            return HttpResponseRedirect(_confirmation(payment.is_success, payment.invoice, payment.reference))
        if request.query_params.get("Status") != "OK":
            _finish(payment, False, error="لغو شده توسط کاربر")
            return HttpResponseRedirect(_confirmation(False, payment.invoice))
        try:
            reply = zarinpal_verify(payment)
        except Exception:
            # Left unverified: coming back to this URL verifies again (Zarinpal returns 101 if it already was).
            logger.exception("zarinpal verify failed for %s", authority)
            return HttpResponseRedirect(_confirmation(False, payment.invoice))
        data = reply.get("data") if isinstance(reply.get("data"), dict) else {}
        ok_ = data.get("code") in (100, 101)  # 101: verified before
        error = "" if ok_ else "{1} ({0})".format(*zarinpal_error(reply))
        if not ok_:
            logger.warning("zarinpal verify refused for %s: %s", authority, error)
        _finish(payment, ok_, str(data.get("ref_id") or ""), data.get("card_pan") or "", error)
        return HttpResponseRedirect(_confirmation(ok_, payment.invoice, str(data.get("ref_id") or "")))


class SnappPayCallbackView(PublicView):
    def post(self, request):
        d = request.data
        payment = InvoicePayment.objects.select_related("invoice").filter(
            gateway=SNAPPPAY, transaction_id=str(d.get("transactionId") or "")).first()
        if not payment:
            return HttpResponseRedirect(_confirmation(False, None))
        if payment.verified_at:
            return HttpResponseRedirect(_confirmation(payment.is_success, payment.invoice, payment.reference))
        if str(d.get("state") or "").upper() != "OK":
            _finish(payment, False, error="ناموفق در اسنپ‌پی")
            return HttpResponseRedirect(_confirmation(False, payment.invoice))
        try:
            verified = _snapp("POST", "/api/online/payment/v1/verify", json={"paymentToken": payment.authority})
            settled = _snapp("POST", "/api/online/payment/v1/settle", json={"paymentToken": payment.authority}) \
                if verified.get("successful") else {}
        except Exception:
            logger.exception("snapppay verify/settle failed for %s", payment.transaction_id)
            return HttpResponseRedirect(_confirmation(False, payment.invoice))
        ok_ = bool(settled.get("successful"))
        reference = str((settled.get("response") or {}).get("transactionId") or payment.transaction_id)
        _finish(payment, ok_, reference, error="" if ok_ else str(verified if not verified.get("successful") else settled)[:500])
        return HttpResponseRedirect(_confirmation(ok_, payment.invoice, reference))
