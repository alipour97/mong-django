"""
Gift cards and coupons as this site has used them, before the software hears of it.

As on the old site, a customer in a payment page holds the voucher for 11 minutes. A paid
order keeps counting until the connector has written it, so nothing is spent twice.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import Max, Sum
from django.utils import timezone

from apps.website.models import Invoice

HOLD = timedelta(minutes=11)


def left(until: datetime) -> str:
    """Time left as the old API gave it, mm:ss."""
    seconds = max(int((until - timezone.now()).total_seconds()), 0)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def held_until(invoice_id: int | None = None, **voucher) -> datetime | None:
    """When another invoice's hold on this voucher ends. An invoice never waits for itself."""
    held = Invoice.objects.filter(state=Invoice.State.PRE_INVOICE, is_deleted=False, voucher_held_until__gt=timezone.now(), **voucher)
    return held.exclude(pk=invoice_id).aggregate(until=Max("voucher_held_until"))["until"]


def _unsent(**voucher):
    return Invoice.objects.filter(paid_at__isnull=False, is_deleted=False, is_test=False, erp_sent_at__isnull=True,
                                  erp_invoice_id__isnull=True, **voucher)


def spent_on_card(card_id: int) -> Decimal:
    return Decimal(_unsent(gift_card_id=card_id).aggregate(total=Sum("deduction_amount"))["total"] or 0)


def coupon_taken(serial: str, customer) -> bool:
    return _unsent(coupon_serial=serial, customer=customer).exists()
