"""Writing a connector's whole read into apps.erp.models, and the stock a paid order takes."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.website.models import Invoice, online_warehouse_ids

from .connector import SourceError, get_connector
from .models import ErpImage, ErpProduct, ErpStock, ErpVariant

BATCH = 2000
# A taken invoice reaches the shop's quantities a little later than its MapId.
SETTLES_AFTER = timedelta(minutes=15)


@dataclass
class Read:
    products: list[ErpProduct] = field(default_factory=list)
    variants: list[ErpVariant] = field(default_factory=list)
    stock: list[ErpStock] = field(default_factory=list)
    images: list[ErpImage] = field(default_factory=list)


def replace(read: Read) -> dict:
    """Swaps in a full read at once, so a page never sees half of one. An empty read changes nothing."""
    if not read.products:
        raise SourceError("nothing to sell in this read, kept what we have")
    with transaction.atomic():
        ErpStock.objects.all().delete()
        ErpImage.objects.all().delete()
        ErpVariant.objects.all().delete()
        ErpProduct.objects.all().delete()
        for rows in (read.products, read.variants, read.stock, read.images):
            if rows:
                type(rows[0]).objects.bulk_create(rows, batch_size=BATCH)
        if get_connector().holds_stock:
            hold_open_orders()
    return {"products": len(read.products), "variants": len(read.variants), "images": len(read.images)}


def online_stock():
    rows = ErpStock.objects.all()
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
        ErpStock.objects.filter(pk=row.pk).update(qty=F("qty") - taken)
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
