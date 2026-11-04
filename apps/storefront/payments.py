"""
Paying a pre-invoice (Bank/*), site side. The gateways themselves live in
apps.payhub, the one service both sites use; the site calls it in process.

    GET  Bank/GetGateways                                  -> [{id, name, iconUrl, gatewayKey}] (active gateways from the panel)
    GET  Bank/PayInvoiceById?InvoiceId=&ShippingMethodId=&GateWayId=   -> the gateway page URL
    GET  Bank/SnappPayEligible?Amount=                     -> {eligible, title_message, description}
    GET  Bank/SnappPayOffer?Amount=                        -> the same for the product page (no sign-in, cached)
    GET  Bank/GiftCardPayInvoiceById?InvoiceId=&ShippingMethodId=      -> confirmation URL (only a zero-amount invoice)
    GET  Bank/PaymentVerification?success=&trackingToken=  (the hub sends the customer here after the gateway)

Each pay request is an InvoicePayment row and a hub record. Back from the gateway
the hub finishes the payment once (Zarinpal verify, SnappPay settle); then the
invoice is successful and the customer lands on
/order-confirmation?success=...&InvoiceId=...&TrackingToken=... like before. A paid
invoice goes to the sales software through its connector (apps/erp/outbox.py).
"""
from __future__ import annotations

import base64
import logging
import threading
from decimal import Decimal
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.http import HttpResponseRedirect
from django.db.models import Sum
from django.utils import timezone
from rest_framework.throttling import AnonRateThrottle

from apps import smsir
from apps.erp import outbox, store as erp_store, vouchers
from apps.erp.connector import Refused
from apps.payhub import service as hub
from apps.payhub import snapppay, zarinpal
from apps.payhub.models import PayRecord
from apps.website.models import BankGateway, Customer, Invoice, InvoicePayment, ProductVariant

from apps.adminapi.paging import to_int

from . import catalog
from .account import CustomerView, answer
from .orders import S, assign_number, snapshot_address
from .views import PublicView

logger = logging.getLogger(__name__)

ZARINPAL, SNAPPPAY = hub.ZARINPAL, hub.SNAPPPAY
SUPPORTED = hub.GATEWAYS
OFFER_SECONDS = 300  # product pages share the answer: one customer view is not one SnappPay call


def _active(key: str) -> BankGateway | None:
    """The gateway switched on in the panel's configs page for this bank key."""
    return BankGateway.objects.filter(bank__key=key, is_deleted=False).select_related("bank").order_by("-id").first()


def zarinpal_merchant() -> str:
    """The panel gateway's merchant id, else ZARINPAL_KEY from .env."""
    g = _active(ZARINPAL)
    for value in ((g.merchant, g.merchant_key, g.terminal_id) if g else ()):
        if len((value or "").strip()) == zarinpal.UUID_LEN:
            return value.strip()
    return settings.ZARINPAL_MERCHANT_ID


def _enabled(key: str) -> bool:
    if not _active(key):
        return False
    if key == ZARINPAL:
        return bool(zarinpal_merchant())
    # SnappPay's OAuth client, user and API address stay in .env.
    return snapppay.configured()


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


def _back_here(success: bool) -> str:
    """Where the hub sends the customer after the gateway."""
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/api/v1/Bank/PaymentVerification?success={'true' if success else 'false'}"


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


def _test_money(gateway: str) -> bool:
    return settings.ZARINPAL_SANDBOX if gateway == ZARINPAL else settings.SNAPPAY_IS_STAGE


def _mark_paid(inv: Invoice, *, test: bool = False) -> None:
    with transaction.atomic():
        if inv.address and not inv.full_address:
            snapshot_address(inv)
        inv.state, inv.paid_at, inv.is_test = S.SUCCESSFUL, timezone.now(), test
        inv.save(update_fields=["state", "paid_at", "is_test", "last_modified", "recipient_name", "recipient_mobile", "full_address", "postal_code", "province_name", "city_name"])
        number = assign_number(inv)
        for line in inv.lines.all():
            erp_store.take(line.variant_id, line.qty)
    transaction.on_commit(catalog.clear_caches)
    transaction.on_commit(lambda: _notify_admins(number))
    transaction.on_commit(lambda: outbox.send_soon(inv.id))


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


def snapp_order(inv: Invoice, lines=None) -> dict:
    """
    The order as SnappPay wants it (API document, "how to calculate totalAmount and amount"):
    cart total = count x item amount + shipping; order amount = cart total - discount - external source.
    """
    items = [{"amount": ln.price_after_reduction, "category": "پوشاک", "count": int(ln.qty), "id": ln.variant_id,
              "name": ln.name[:100], "commissionType": settings.SNAPPAY_COMMISSION_TYPE} for ln in (lines or inv.lines.all())]
    goods = sum(i["amount"] * i["count"] for i in items)
    external = inv.deduction_amount if inv.gift_card_number else 0
    discount = inv.deduction_amount - external
    amount = goods + inv.delivery_amount - discount - external
    return {
        "amount": amount, "discountAmount": discount, "externalSourceAmount": external, "mobile": inv.customer.cellphone,
        "cartList": [{"cartId": inv.id, "cartItems": items, "isShipmentIncluded": True, "isTaxIncluded": True,
                      "shippingAmount": inv.delivery_amount, "taxAmount": 0, "totalAmount": goods + inv.delivery_amount}],
    }


def _hold_voucher(inv: Invoice) -> None:
    """A voucher on its way through a payment is out of reach until the payment ends or the hold runs out."""
    if not (inv.gift_card_number or inv.coupon_serial):
        return
    with transaction.atomic():
        Customer.objects.select_for_update().filter(pk=inv.customer_id).first()  # one customer, one hold at a time
        if inv.gift_card_number:
            card = vouchers.find_gift_card(inv.gift_card_number, inv.customer, inv.id)
            if card.balance < inv.deduction_amount:
                raise Refused("موجودی کارت هدیه تغییر کرده است. لطفا سبد خرید را دوباره ثبت کنید.")
        else:
            vouchers.find_coupon(inv.coupon_serial, inv.customer, inv.id)
        if vouchers.hold():
            Invoice.objects.filter(pk=inv.pk).update(voucher_held_until=timezone.now() + vouchers.hold())


def _release_voucher(inv: Invoice) -> None:
    Invoice.objects.filter(pk=inv.pk).update(voucher_held_until=None)


def _start_payment(inv: Invoice, key: str) -> str:
    """Opens the gateway session and returns its page."""
    record = hub.create(gateway=key, amount=inv.payable_amount, success=_back_here(True), failed=_back_here(False),
                        source=PayRecord.Source.SITE, cell_phone=inv.customer.cellphone, customer_key=str(inv.customer_id),
                        merchant_id=zarinpal_merchant() if key == ZARINPAL else "")
    if key == ZARINPAL:
        url = hub.start_zarinpal(record, str(inv.id), inv.payable_amount)
        InvoicePayment.objects.create(invoice=inv, gateway=key, amount=inv.payable_amount, authority=record.authority)
        return url
    started = hub.start_snapp(record, str(inv.id), inv.payable_amount, snapp_order(inv))
    InvoicePayment.objects.create(invoice=inv, gateway=key, amount=inv.payable_amount, authority=started["paymentToken"],
                                  transaction_id=started["transactionId"])
    return started["paymentPageUrl"]


def _out_of_stock(inv: Invoice) -> bool:
    lines = list(inv.lines.all())
    stock = dict(
        erp_store.online_stock().filter(variant__in=[ln.variant_id for ln in lines])
        .values("variant_id").annotate(total=Sum("qty")).values_list("variant_id", "total")
    )
    known = set(ProductVariant.objects.filter(id__in=[ln.variant_id for ln in lines]).values_list("id", flat=True))
    return any(ln.variant_id in known and stock.get(ln.variant_id, Decimal(0)) < ln.qty for ln in lines)


def delivery_problem(record: PayRecord) -> str:
    """Why this payment must not go through, for the customer; empty when all is well. Asked before the gateway is verified."""
    inv = Invoice.objects.filter(id=record.transaction_id, is_deleted=False).first() if record.transaction_id.isdigit() else None
    if not inv:
        return "فاکتور این پرداخت پیدا نشد؛ مبلغ برگشت داده می‌شود."
    if inv.state != S.PRE_INVOICE:
        return "این فاکتور قبلاً پرداخت شده است؛ مبلغ این پرداخت برگشت داده می‌شود."
    if inv.payable_amount != record.amount:
        return "سبد خرید بعد از شروع پرداخت تغییر کرده است؛ مبلغ برگشت داده می‌شود."
    if _out_of_stock(inv):
        return "موجودی کالاهای سفارش به اتمام رسیده است؛ مبلغ برگشت داده می‌شود."
    return ""


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
        if key == SNAPPPAY and inv.gift_card_number:
            return answer(None, 409, "امکان استفاده همزمان از کارت هدیه و اعتبار اسنپ‌پی وجود ندارد.")
        try:
            _hold_voucher(inv)
        except Refused as exc:
            return answer(None, 409, str(exc))
        try:
            url = _start_payment(inv, key)
        except hub.Refused as exc:
            logger.warning("pay request refused for invoice %s: %s", inv.id, exc)
            _release_voucher(inv)
            return answer(None, 502, exc.message)
        except Exception:
            logger.exception("pay request failed for invoice %s", inv.id)
            _release_voucher(inv)
            return answer(None, 502, hub.CONNECTION_FAILED)
        return answer(url, message="در حال انتقال به درگاه پرداخت")


def _eligibility(amount: int) -> dict:
    """Shown without any change, and only as SnappPay answers it (API document, questions 6)."""
    reply = snapppay.eligible(amount)
    return {"eligible": bool(reply.value("eligible")), "title_message": reply.value("title_message") or "",
            "description": reply.value("description") or ""}


NOT_ELIGIBLE = {"eligible": False, "title_message": "", "description": ""}


class SnappEligibleView(CustomerView):
    def get(self, request):
        amount = request.query_params.get("Amount")
        if not _enabled(SNAPPPAY) or not str(amount or "").isdigit():
            return answer(NOT_ELIGIBLE)
        return answer(_eligibility(int(amount)))


class OfferThrottle(AnonRateThrottle):
    rate = "60/min"


class SnappOfferView(PublicView):
    """The product page's box: anyone can see it, so answers are shared for a few minutes."""

    throttle_classes = [OfferThrottle]

    def get(self, request):
        amount = request.query_params.get("Amount")
        if not str(amount or "").isdigit() or int(amount) <= 0 or not _enabled(SNAPPPAY):
            return answer(NOT_ELIGIBLE)
        key = f"snapppay:offer:{int(amount)}"
        offer = cache.get(key)
        if offer is None:
            offer = _eligibility(int(amount))
            cache.set(key, offer, OFFER_SECONDS)
        return answer(offer)


class ZeroAmountView(CustomerView):
    """A pre-invoice with nothing to pay (once gift cards cover it) is finished without a gateway."""

    def get(self, request):
        inv = _payable_invoice(request, request.query_params.get("InvoiceId"))
        if not inv:
            return answer(None, 404, "فاکتور یافت نشد")
        if inv.payable_amount > 0:
            return answer(None, 400, "این فاکتور باید از درگاه پرداخت شود.")
        try:
            _hold_voucher(inv)
        except Refused as exc:
            return answer(None, 409, str(exc))
        _mark_paid(inv)
        return answer(_confirmation(True, inv), message="پرداخت موفق با کارت هدیه.")


def _finish(payment: InvoicePayment, success: bool, reference: str = "", card: str = "", error: str = "") -> None:
    with transaction.atomic():
        won = InvoicePayment.objects.filter(pk=payment.pk, verified_at__isnull=True).update(
            is_success=success, reference=reference, card_pan=card, error_message=error[:2000], verified_at=timezone.now())
        payment.refresh_from_db()
        if won and success and payment.invoice.state == S.PRE_INVOICE:
            _mark_paid(payment.invoice, test=_test_money(payment.gateway))
        elif won and not success:
            _release_voucher(payment.invoice)


def _payment_of(record: PayRecord | None) -> InvoicePayment | None:
    if not record or not record.transaction_id.isdigit():
        return None
    return InvoicePayment.objects.select_related("invoice").filter(
        invoice_id=int(record.transaction_id), gateway=record.gateway, authority=record.payment_token or record.authority).first()


def _gateway_reference(record: PayRecord) -> str:
    return record.ref_id or record.gateway_transaction_id


class PaymentVerificationView(PublicView):
    """The hub's return address for this site: the token is secret, and confirm answers ok only once."""

    def get(self, request):
        q = request.query_params
        record = PayRecord.objects.filter(token=q.get("trackingToken", ""), source=PayRecord.Source.SITE).first()
        payment = _payment_of(record)
        if not payment:
            return HttpResponseRedirect(_confirmation(False, None))
        if payment.verified_at:  # already handled (refresh or a second visit)
            return HttpResponseRedirect(_confirmation(payment.is_success, payment.invoice, payment.reference))
        if q.get("success") != "true":
            _finish(payment, False, error=q.get("errorMessage") or record.error)
            return HttpResponseRedirect(_confirmation(False, payment.invoice))

        if problem := delivery_problem(record):
            hub.abandon(record, problem)
            _finish(payment, False, error=problem)
            return HttpResponseRedirect(_confirmation(False, payment.invoice))
        result = hub.confirm(record, record.transaction_id, record.amount)
        if result["status"] in ("ok", "duplicate"):
            reference = _gateway_reference(record)
            _finish(payment, True, reference, record.card_pan)
            return HttpResponseRedirect(_confirmation(True, payment.invoice, reference))
        logger.warning("payment %s not confirmed: %s (%s)", payment.pk, result["status"], record.error)
        if record.state != hub.S.RETURNED:  # RETURNED: coming back to this URL confirms again
            _finish(payment, False, error=record.error)
        return HttpResponseRedirect(_confirmation(False, payment.invoice))
