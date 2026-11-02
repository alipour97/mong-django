"""
The one seam between the site and the sales software. ERP_CONNECTOR picks one; the site
never asks which. A connector does two things only: copies what the software owns into the
site's tables on its schedule, and takes paid invoices. Nothing here runs while a customer waits.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from typing import Callable

from django.conf import settings
from django.utils.module_loading import import_string

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
    id: int | None  # None: a card made on this site
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

    def sync(self, *, force: bool = False, log: Log) -> dict:
        raise NotImplementedError

    def push(self, invoice) -> None:
        """Hands a paid invoice over. Nothing happens until the software has a way in."""

    def follow(self, log: Log) -> None:
        """Marks the invoices the software has taken."""


@lru_cache(maxsize=1)
def get_connector() -> Connector:
    return import_string(settings.ERP_CONNECTORS[settings.ERP_CONNECTOR])()
