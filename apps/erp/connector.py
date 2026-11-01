"""
The one seam between the site and the sales software. ERP_CONNECTOR picks one; the site
never asks which. A connector does two things only: fills apps.erp.models on its schedule,
and takes paid invoices. Gift cards and coupons live in the software too, so it answers those.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from typing import Callable

from django.conf import settings
from django.utils.module_loading import import_string

from .models import ErpVariant

Log = Callable[[str], None]


class SourceError(RuntimeError):
    """A source answered badly, so what this site holds is left as it is."""


@dataclass(frozen=True)
class Coupon:
    id: int | None  # None: a general coupon, the customer's own copy is made when it is used
    serial: str
    reduction: Decimal
    min_price: Decimal
    max_price: Decimal | None
    expires: datetime | None


@dataclass(frozen=True)
class GiftCard:
    id: int
    number: str
    balance: Decimal
    min_price: Decimal
    use_whole: bool


class Refused(ValueError):
    """Why a coupon or gift card cannot be used, for the customer."""


class Held(Refused):
    """The voucher is in another payment page until this moment."""

    def __init__(self, message: str, until: datetime, coupon: Coupon | None = None):
        super().__init__(message)
        self.until, self.coupon = until, coupon


class Connector:
    name = ""
    all_warehouses = False  # every warehouse's stock is offered online
    holds_stock = False  # a paid order is missing from the software's stock until it has taken the invoice

    def sync(self, *, full: bool, log: Log) -> dict:
        raise NotImplementedError

    def barcodes(self) -> list[tuple[str, int, int]]:
        """(barcode, product id, color id) of everything on sale, for matching LEBAZAI's photos."""
        rows = ErpVariant.objects.exclude(barcode="").exclude(color_id=None)
        return list(rows.values_list("barcode", "product_id", "color_id"))

    def push(self, invoice) -> None:
        """Hands a paid invoice over. Nothing happens until the software has a way in."""

    def follow(self, log: Log) -> None:
        """Marks the invoices the software has taken."""

    def coupon(self, serial: str, customer, invoice_id: int | None = None) -> Coupon:
        raise Refused("استفاده از کوپن به‌زودی فعال می‌شود.")

    def gift_card(self, number: str, customer, invoice_id: int | None = None) -> GiftCard:
        raise Refused("استفاده از کارت هدیه به‌زودی فعال می‌شود.")

    def gift_cards(self, customer) -> list[dict]:
        return []

    def coupon_page(self, *, search: str, created_from, expires_to, page: int, size: int) -> tuple[int, list[dict]]:
        """(total, one page of coupons) for the panel."""
        return 0, []

    def coupon_labels(self) -> dict:
        return {"total": 0, "active": 0, "used": 0}

    def coupon_info(self, coupon_id: int) -> dict | None:
        return None

    def gift_card_page(self, filters: dict, page: int, size: int) -> tuple[int, list[dict]]:
        """(total, one page of gift cards) for the panel."""
        return 0, []

    def gift_card_labels(self) -> dict:
        return {"total": 0, "active": 0, "used": 0}


@lru_cache(maxsize=1)
def get_connector() -> Connector:
    return import_string(settings.ERP_CONNECTORS[settings.ERP_CONNECTOR])()
