"""
Gift cards and coupons, whichever side made them: the site's own (Django admin) come first,
then the connector's. Also how this site has used them before the software hears of it.

As on the old site, a customer in a payment page holds the voucher for VOUCHER_HOLD_MINUTES.
A paid order keeps counting until the connector has written it, so nothing is spent twice.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Max, Sum
from django.utils import timezone

from apps.smsir import normalize_mobile
from apps.website.models import Invoice

from .connector import Coupon, GiftCard, Held, Refused, get_connector
from .models import SiteCoupon, SiteGiftCard


def hold() -> timedelta:
    return timedelta(minutes=settings.VOUCHER_HOLD_MINUTES)


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


def _paid(**voucher):
    return Invoice.objects.filter(paid_at__isnull=False, is_deleted=False, is_test=False, **voucher)


def site_card_left(card: SiteGiftCard) -> int:
    spent = _paid(gift_card_number=card.number, gift_card_id__isnull=True).aggregate(total=Sum("deduction_amount"))["total"] or 0
    return 0 if spent and card.use_whole else max(card.amount - spent, 0)


def times_used(coupon: SiteCoupon) -> int:
    return _paid(coupon_serial=coupon.serial, coupon_id__isnull=True).count()


def _owns(mobile: str, customer) -> bool:
    return not mobile or normalize_mobile(mobile) == customer.cellphone


def find_coupon(serial: str, customer, invoice_id: int | None = None) -> Coupon:
    site = SiteCoupon.objects.filter(serial=serial).first()
    if site is None:
        return get_connector().coupon(serial, customer, invoice_id)
    if not _owns(site.mobile, customer):
        raise Refused("کوپن وجود ندارد.")
    if _paid(coupon_serial=serial, customer=customer).exists():
        raise Refused("کوپن استفاده شده است.")
    if not site.is_active:
        raise Refused("کوپن غیر فعال است.")
    if site.expires and site.expires < timezone.now():
        raise Refused("مهلت استفاده از این کوپن تمام شده است.")
    coupon = Coupon(id=None, serial=serial, reduction=site.reduction, min_price=Decimal(site.min_price), max_price=site.max_price, expires=site.expires)
    until = held_until(invoice_id, coupon_serial=serial, customer=customer)
    if until:
        raise Held("این کوپن در حالت تعلیق قرار دارد.", until, coupon)
    return coupon


def find_gift_card(number: str, customer, invoice_id: int | None = None) -> GiftCard:
    site = SiteGiftCard.objects.filter(number=number).first()
    if site is None:
        return get_connector().gift_card(number, customer, invoice_id)
    left_on_card = site_card_left(site)
    if not _owns(site.mobile, customer):
        raise Refused("کارت هدیه پیدا نشد.")
    if not site.is_active or left_on_card <= 0:
        raise Refused("این کارت هدیه قابل استفاده نیست.")
    until = held_until(invoice_id, gift_card_number=number)
    if until:
        raise Held("این کارت هدیه در حالت تعلیق قرار دارد.", until)
    now = timezone.now()
    if site.starts and site.starts > now:
        raise Refused("زمان استفاده از این کارت هدیه هنوز نرسیده است.")
    if site.expires and site.expires < now:
        raise Refused("مهلت استفاده از این کارت هدیه تمام شده است.")
    return GiftCard(id=None, number=number, balance=Decimal(left_on_card), min_price=Decimal(site.min_price), use_whole=site.use_whole)


def gift_cards(customer) -> list[dict]:
    """What the customer can spend now: the site's cards, then the software's."""
    now, cards = timezone.now(), []
    for site in SiteGiftCard.objects.filter(mobile=customer.cellphone, is_active=True):
        left_on_card = site_card_left(site)
        if left_on_card > 0 and (not site.starts or site.starts <= now) and (not site.expires or site.expires >= now):
            until = held_until(gift_card_number=site.number)
            cards.append({"GCNum": site.number, "StartDate": site.starts or site.created, "ExpDate": site.expires, "GCBalance": Decimal(left_on_card),
                          "IsActive": True, "UseDepCode": False, "MinFactorPrice": site.min_price, "UseCompelete": site.use_whole,
                          "Left": left(until) if until else None})
    return cards + get_connector().gift_cards(customer)
