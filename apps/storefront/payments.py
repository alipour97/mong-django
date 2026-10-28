"""
Paying a pre-invoice (Bank/*), site side: Zarinpal and SnappPay.

    GET  Bank/GetGateways                                  -> [{id, name, iconUrl, gatewayKey}]
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
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.db import transaction
from django.http import HttpResponseRedirect
from django.utils import timezone

from apps.website.models import Invoice, InvoicePayment

from .account import CustomerView, answer
from .orders import S
from .views import PublicView

logger = logging.getLogger(__name__)

ZARINPAL, SNAPPPAY = "zarinpal", "snapppay"
GATEWAYS = {1: (ZARINPAL, "زرین‌پال"), 2: (SNAPPPAY, "اسنپ‌پی")}
TIMEOUT = 30


def _enabled(key: str) -> bool:
    if key == ZARINPAL:
        return bool(settings.ZARINPAL_MERCHANT_ID)
    return bool(settings.SNAPPAY_BASE_URL and settings.SNAPPAY_CLIENT_ID and settings.SNAPPAY_USERNAME)


def _confirmation(success: bool, invoice_id: int, token: str = "") -> str:
    query = {"success": "true" if success else "false", "TrackingToken": token, "InvoiceId": invoice_id}
    return f"{settings.SITE_URL}/order-confirmation?{urlencode(query)}"


def _callback(name: str) -> str:
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/api/v1/Bank/{name}"


class GatewaysView(CustomerView):
    def get(self, request):
        return answer([
            {"id": gid, "name": name, "iconUrl": "", "gatewayKey": key}
            for gid, (key, name) in GATEWAYS.items() if _enabled(key)
        ])


def _payable_invoice(request, invoice_id) -> Invoice | None:
    return request.user.invoices.filter(id=invoice_id, state=S.PRE_INVOICE, is_deleted=False).first() if str(invoice_id or "").isdigit() else None


def _mark_paid(inv: Invoice) -> None:
    inv.state, inv.paid_at = S.SUCCESSFUL, timezone.now()
    inv.save(update_fields=["state", "paid_at", "last_modified"])


# -----------------------------------------------------------------------------
# Zarinpal (https://payment.zarinpal.com/pg/v4/payment/{request,verify}.json, amounts in rial)
# -----------------------------------------------------------------------------
def _zarinpal_base() -> str:
    return "https://sandbox.zarinpal.com" if settings.ZARINPAL_SANDBOX else "https://payment.zarinpal.com"


def zarinpal_request(inv: Invoice) -> str:
    """Creates the payment; returns the StartPay URL."""
    body = {
        "merchant_id": settings.ZARINPAL_MERCHANT_ID, "amount": inv.payable_amount, "currency": "IRR",
        "callback_url": _callback("ZarinpalCallback"), "description": f"سفارش {inv.id} مانگ",
        "metadata": {"mobile": inv.customer.cellphone, "order_id": str(inv.id)},
    }
    resp = requests.post(f"{_zarinpal_base()}/pg/v4/payment/request.json", json=body, timeout=TIMEOUT,
                         headers={"Accept": "application/json"})
    data = (resp.json() or {}).get("data") or {}
    if data.get("code") != 100 or not data.get("authority"):
        raise RuntimeError(f"zarinpal request: {resp.status_code} {resp.text[:300]}")
    InvoicePayment.objects.create(invoice=inv, gateway=ZARINPAL, amount=inv.payable_amount, authority=data["authority"])
    return f"{_zarinpal_base()}/pg/StartPay/{data['authority']}"


def zarinpal_verify(payment: InvoicePayment) -> dict:
    body = {"merchant_id": settings.ZARINPAL_MERCHANT_ID, "amount": payment.amount, "authority": payment.authority}
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
        key, _ = GATEWAYS.get(int(q.get("GateWayId")) if str(q.get("GateWayId") or "").isdigit() else 0, (None, None))
        if not key or not _enabled(key):
            return answer(None, 400, "درگاه پرداخت انتخاب‌شده فعال نیست.")
        try:
            url = zarinpal_request(inv) if key == ZARINPAL else snapp_request(inv)
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
        return answer(_confirmation(True, inv.id), message="پرداخت موفق با کارت هدیه.")


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
            return HttpResponseRedirect(_confirmation(False, 0))
        if payment.verified_at:  # already handled (refresh or a second visit)
            return HttpResponseRedirect(_confirmation(payment.is_success, payment.invoice_id, payment.reference))
        if request.query_params.get("Status") != "OK":
            _finish(payment, False, error="لغو شده توسط کاربر")
            return HttpResponseRedirect(_confirmation(False, payment.invoice_id))
        try:
            data = (zarinpal_verify(payment).get("data") or {})
        except Exception:
            logger.exception("zarinpal verify failed for %s", authority)
            return HttpResponseRedirect(_confirmation(False, payment.invoice_id))
        ok_ = data.get("code") in (100, 101)
        _finish(payment, ok_, str(data.get("ref_id") or ""), data.get("card_pan") or "", "" if ok_ else str(data)[:500])
        return HttpResponseRedirect(_confirmation(ok_, payment.invoice_id, str(data.get("ref_id") or "")))


class SnappPayCallbackView(PublicView):
    def post(self, request):
        d = request.data
        payment = InvoicePayment.objects.select_related("invoice").filter(
            gateway=SNAPPPAY, transaction_id=str(d.get("transactionId") or "")).first()
        if not payment:
            return HttpResponseRedirect(_confirmation(False, 0))
        if payment.verified_at:
            return HttpResponseRedirect(_confirmation(payment.is_success, payment.invoice_id, payment.reference))
        if str(d.get("state") or "").upper() != "OK":
            _finish(payment, False, error="ناموفق در اسنپ‌پی")
            return HttpResponseRedirect(_confirmation(False, payment.invoice_id))
        try:
            verified = _snapp("POST", "/api/online/payment/v1/verify", json={"paymentToken": payment.authority})
            settled = _snapp("POST", "/api/online/payment/v1/settle", json={"paymentToken": payment.authority}) \
                if verified.get("successful") else {}
        except Exception:
            logger.exception("snapppay verify/settle failed for %s", payment.transaction_id)
            return HttpResponseRedirect(_confirmation(False, payment.invoice_id))
        ok_ = bool(settled.get("successful"))
        reference = str((settled.get("response") or {}).get("transactionId") or payment.transaction_id)
        _finish(payment, ok_, reference, error="" if ok_ else str(verified if not verified.get("successful") else settled)[:500])
        return HttpResponseRedirect(_confirmation(ok_, payment.invoice_id, reference))
