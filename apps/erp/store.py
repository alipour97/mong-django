"""
Writing a connector's read into the site's own tables, and the stock a paid order takes.

A sync only updates what the software owns: slugs, descriptions, AI copy, photos and whatever else
the site keeps are never touched, and the site goes on with its last read when the software is away.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import NamedTuple

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.website.models import Brand, Category, Invoice, Product, ProductVariant, VariantStock, online_warehouse_ids

from .connector import SourceError, get_connector
from .models import ErpCoupon, ErpGiftCard, SyncState

BATCH = 2000
UPDATE_BATCH = 500
# A read this much smaller than what is on sale is a broken source, not a closing-down sale.
MIN_SHARE = 0.5
# A taken invoice reaches the shop's quantities a little later than its MapId.
SETTLES_AFTER = timedelta(minutes=15)
SYNC_NAME = "erp"


class VariantRow(NamedTuple):
    id: int
    product_id: int
    erp_ref: int | None
    barcode: str
    color_id: int | None
    color_name: str
    color_value: str
    color_priority: int
    color_family: str
    size_id: int | None
    size_name: str
    size_value: str
    size_priority: int


class StockRow(NamedTuple):
    variant_id: int
    warehouse_id: int
    warehouse_title: str
    qty: Decimal


@dataclass
class Read:
    """
    A connector's whole read. brands, categories and products are dicts of an id and the fields the software
    owns; a product or category the site does not have yet is made with the extra fields in "new".
    """

    brands: list[dict] = field(default_factory=list)
    categories: list[dict] = field(default_factory=list)
    products: list[dict] = field(default_factory=list)
    variants: list[VariantRow] = field(default_factory=list)
    stock: list[StockRow] = field(default_factory=list)
    coupons: list[ErpCoupon] = field(default_factory=list)
    gift_cards: list[ErpGiftCard] = field(default_factory=list)


def _chunks(values: list, size: int = BATCH):
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _merge(model, rows: list[dict]) -> None:
    """Adds what is new and updates what changed, so a quiet read writes nothing."""
    if not rows:
        return
    fields = [name for name in rows[0] if name not in ("id", "new")]
    held = {row[0]: row[1:] for row in model.objects.values_list("id", *fields)}
    added, changed = [], []
    for row in rows:
        values = {name: row[name] for name in fields}
        if row["id"] not in held:
            added.append(model(id=row["id"], **values, **row.get("new", {})))
        elif held[row["id"]] != tuple(values.values()):
            changed.append(model(id=row["id"], **values))
    model.objects.bulk_create(added, batch_size=BATCH)
    model.objects.bulk_update(changed, fields, batch_size=UPDATE_BATCH)


def _take_off_sale(sold: set[int]) -> None:
    gone = set(Product.objects.filter(on_sale=True).values_list("id", flat=True)) - sold
    for ids in _chunks(list(gone)):
        Product.objects.filter(id__in=ids).update(on_sale=False)


def _variants(rows: list[VariantRow]) -> None:
    held = {row[0]: row for row in ProductVariant.objects.values_list(*VariantRow._fields)}
    added, changed = [], []
    for row in rows:
        known = held.pop(row.id, None)
        if known is None:
            added.append(ProductVariant(**row._asdict()))
        elif known != tuple(row):
            changed.append(ProductVariant(**row._asdict()))
    ProductVariant.objects.bulk_create(added, batch_size=BATCH)
    ProductVariant.objects.bulk_update(changed, VariantRow._fields[1:], batch_size=UPDATE_BATCH)
    for ids in _chunks(list(held)):
        ProductVariant.objects.filter(id__in=ids).delete()


def apply(read: Read, *, force: bool = False) -> dict:
    """Swaps in a full read at once, so a page never sees half of one. An empty or shrunken read changes nothing."""
    if not read.products:
        raise SourceError("nothing to sell in this read, kept what we have")
    held = Product.objects.filter(on_sale=True).count()
    if not force and len(read.products) < held * MIN_SHARE:
        raise SourceError(f"only {len(read.products)} products in this read against {held} on sale, kept what we have")
    with transaction.atomic():
        _merge(Brand, read.brands)
        _merge(Category, read.categories)
        _merge(Product, read.products)
        _take_off_sale({row["id"] for row in read.products})
        _variants(read.variants)
        VariantStock.objects.all().delete()
        VariantStock.objects.bulk_create([VariantStock(**row._asdict()) for row in read.stock], batch_size=BATCH)
        ErpCoupon.objects.all().delete()
        ErpCoupon.objects.bulk_create(read.coupons, batch_size=BATCH)
        ErpGiftCard.objects.all().delete()
        ErpGiftCard.objects.bulk_create(read.gift_cards, batch_size=BATCH)
        if get_connector().holds_stock:
            hold_open_orders()
        SyncState.objects.update_or_create(name=SYNC_NAME, defaults={"at": timezone.now()})
    return {"products": len(read.products), "variants": len(read.variants), "stock": len(read.stock),
            "coupons": len(read.coupons), "gift_cards": len(read.gift_cards)}


def synced_at():
    return SyncState.objects.filter(name=SYNC_NAME).values_list("at", flat=True).first()


def barcodes() -> list[tuple[str, int, int]]:
    """(barcode, product id, color id) of everything on sale, for matching LEBAZAI's photos."""
    rows = ProductVariant.objects.exclude(barcode="").exclude(color_id=None)
    return list(rows.values_list("barcode", "product_id", "color_id"))


def online_stock():
    rows = VariantStock.objects.all()
    return rows if get_connector().all_warehouses else rows.filter(warehouse_id__in=online_warehouse_ids())


def take(variant_id: int, qty: Decimal) -> None:
    """Takes qty off the online stock of a variant, largest warehouse first. Call inside a transaction."""
    rows = list(online_stock().select_for_update().filter(variant_id=variant_id).order_by("-qty"))
    for row in rows:
        if qty <= 0:
            break
        if row.qty <= 0:
            continue
        taken = min(row.qty, qty)
        VariantStock.objects.filter(pk=row.pk).update(qty=F("qty") - taken)
        qty -= taken


def open_orders():
    """Paid orders the software's stock does not show yet."""
    settled = timezone.now() - SETTLES_AFTER
    return (Invoice.objects.filter(state=Invoice.State.SUCCESSFUL, is_deleted=False, is_test=False)
            .exclude(erp_taken_at__lte=settled))


def hold_open_orders() -> None:
    """A fresh read knows nothing of what was just sold: without this the last piece could sell twice."""
    for invoice in open_orders().prefetch_related("lines"):
        for line in invoice.lines.all():
            take(line.variant_id, line.qty)
