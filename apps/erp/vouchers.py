"""
Gift cards and coupons, whichever side made them: the site's own (Django admin) come first, then
the software's as the last sync read them. Nothing here reaches the software. Also how this site
has used them before a sync shows it.

As on the old site, a customer in a payment page holds the voucher for VOUCHER_HOLD_MINUTES.
A paid order keeps counting until the connector has written it, so nothing is spent twice.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Max, Q, Sum
from django.utils import timezone

from apps.smsir import normalize_mobile
from apps.website.models import Invoice

from . import store
from .connector import Coupon, GiftCard, Held, Refused
from .models import ErpCoupon, ErpGiftCard, SiteCoupon, SiteGiftCard


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
    """Paid orders the last sync cannot show yet: not written to the software, or written after that sync read it."""
    since_sync = Q(erp_sent_at__isnull=True, erp_invoice_id__isnull=True)
    synced = store.synced_at()
    if synced:
        since_sync |= Q(erp_sent_at__gt=synced)
    return Invoice.objects.filter(since_sync, paid_at__isnull=False, is_deleted=False, is_test=False, **voucher)


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


def _source_hold(row) -> datetime | None:
    """A voucher the old site still holds in a payment page."""
    until = row.held_until
    return until if until and not row.is_active and until > timezone.now() else None


def _customer_id(customer) -> int:
    return customer.erp_customer_id or customer.id


def _software_coupon(serial: str, customer, invoice_id: int | None = None) -> Coupon:
    """The customer's own coupon, else a general one (the customer's copy is made when it is used)."""
    own = ErpCoupon.objects.filter(serial=serial, customer_erp_id=_customer_id(customer)).order_by("is_used").first()
    row = own or ErpCoupon.objects.filter(serial=serial, customer_erp_id__isnull=True, is_active=True).first()
    if row is None:
        raise Refused("کوپن وجود ندارد.")
    if (own and own.is_used) or coupon_taken(serial, customer):
        raise Refused("کوپن استفاده شده است.")
    if row.expires and row.expires < timezone.now():
        raise Refused("مهلت استفاده از این کوپن تمام شده است.")
    coupon = Coupon(id=row.id if own else None, serial=row.serial, reduction=row.reduction, min_price=row.min_price,
                    max_price=row.max_price, expires=row.expires)
    until = _source_hold(row) or held_until(invoice_id, coupon_serial=serial, customer=customer)
    if until:
        raise Held("این کوپن در حالت تعلیق قرار دارد.", until, coupon)
    if not row.is_active and not row.held_until:
        raise Refused("کوپن غیر فعال است.")
    return coupon


def _software_cards(customer):
    return ErpGiftCard.objects.filter(Q(customer_erp_id=_customer_id(customer)) | Q(mobile=customer.cellphone)).order_by("-id")


def _software_balance(card: ErpGiftCard) -> Decimal:
    spent = spent_on_card(card.id)
    return Decimal(0) if spent and card.use_whole else max(card.balance - spent, Decimal(0))


def _software_gift_cards(customer) -> list[dict]:
    """What the customer can spend now, as the old site listed it."""
    today, cards = timezone.localdate(), []
    for card in _software_cards(customer).filter(is_active=True, balance__gt=0):
        if (card.starts and timezone.localtime(card.starts).date() > today) or (card.expires and timezone.localtime(card.expires).date() < today):
            continue
        balance = _software_balance(card)
        if balance <= 0:
            continue
        until = _source_hold(card) or held_until(gift_card_id=card.id)
        cards.append({"Id": card.id, "GCNum": card.number, "StartDate": card.starts, "ExpDate": card.expires, "GCBalance": balance,
                      "IsActive": card.is_active, "CustomerId": card.customer_erp_id, "UseDepCode": card.use_dep_code,
                      "MinFactorPrice": card.min_price, "UseCompelete": card.use_whole, "Left": left(until) if until else None})
    return cards


def _software_gift_card(number: str, customer, invoice_id: int | None = None) -> GiftCard:
    card = _software_cards(customer).filter(number=number).first()
    if card is None:
        raise Refused("کارت هدیه پیدا نشد.")
    balance = _software_balance(card)
    if balance <= 0 or (not card.is_active and not card.held_until):
        raise Refused("این کارت هدیه قابل استفاده نیست.")
    until = _source_hold(card) or held_until(invoice_id, gift_card_id=card.id)
    if until:
        raise Held("این کارت هدیه در حالت تعلیق قرار دارد.", until)
    if card.starts and timezone.localtime(card.starts).date() > timezone.localdate():
        raise Refused("زمان استفاده از این کارت هدیه هنوز نرسیده است.")
    if card.expires and card.expires < timezone.now():
        raise Refused("مهلت استفاده از این کارت هدیه تمام شده است.")
    return GiftCard(id=card.id, number=card.number, balance=balance, min_price=card.min_price, use_whole=card.use_whole)


def find_coupon(serial: str, customer, invoice_id: int | None = None) -> Coupon:
    site = SiteCoupon.objects.filter(serial=serial).first()
    if site is None:
        return _software_coupon(serial, customer, invoice_id)
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
        return _software_gift_card(number, customer, invoice_id)
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
    return cards + _software_gift_cards(customer)
