"""
The Samian connector. Samian's own sync (apps/samian) keeps its tables fresh; this copies
what the site sells out of them, by the same rules the storefront used to read them with.
Sending invoices to Samian is the write phase and is not built yet.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db.models import Q, Sum
from django.utils import timezone

from apps.samian.models import (
    SamianBarcode,
    SamianColor,
    SamianInventory,
    SamianPriceListItem,
    SamianProduct,
    SamianProductColor,
    SamianSalesRow,
    SamianSize,
    SamianWarehouse,
)
from apps.website import images as site_images
from apps.website.models import ProductSamianLink

from . import store
from .connector import Connector, Log
from .models import ErpImage, ErpProduct, ErpStock, ErpVariant


def round_price(rial) -> int:
    """Discounted prices are rounded to 1,000 toman (10,000 rial) like the legacy site."""
    return int((float(rial) + 5000) // 10000 * 10000)


def sold_by_product() -> dict[int, float]:
    """Net units sold per SamianProduct pk over the last BEST_SELLER_DAYS (all branches, Lebaza's too)."""
    since = timezone.localdate() - timedelta(days=settings.BEST_SELLER_DAYS)
    sold: dict[int, float] = defaultdict(float)
    for spk, is_return, qty in (
        SamianSalesRow.objects.filter(report_date__gte=since, samian_product__isnull=False)
        .values("samian_product_id", "is_return").annotate(qty=Sum("quantity"))
        .values_list("samian_product_id", "is_return", "qty")
    ):
        # Samian already stores returned quantities as negative; abs() keeps either sign right.
        sold[spk] += -abs(float(qty)) if is_return else float(qty)
    return sold


def _list_prices(sp_pks) -> dict[int, int]:
    """SamianProduct pk -> the lowest final price of a price list in force."""
    now = timezone.now()
    valid = Q(price_list__isnull=True) | Q(
        price_list__is_active=True, price_list__valid_from__lte=now, price_list__valid_to__gte=now
    )
    prices: dict[int, int] = {}
    for spk, final in (
        SamianPriceListItem.objects.filter(valid, samian_product_id__in=sp_pks)
        .exclude(final_price__isnull=True).values_list("samian_product_id", "final_price")
    ):
        if spk not in prices or final < prices[spk]:
            prices[spk] = final
    return prices


def _product(pid: int, sp: SamianProduct, final, sold: float, now) -> ErpProduct:
    row = ErpProduct(
        product_id=pid, erp_id=sp.samian_id, name_en=sp.name_en or "", subcode=sp.subcode or "", sold=sold, synced_at=now,
        attributes={"جنس": sp.material or "", "سبک": sp.style or "", "فصل": str(sp.season or "")},
    )
    if sp.size_help_path:
        row.size_guide_key = site_images.samian_key(sp.samian_id, sp.size_help_path)
    base = sp.sale_price
    if base:
        row.base_price, row.sale_price = int(base), int(base)
        if final and final < base:
            row.reduction, row.sale_price = round((base - final) * 100 / base, 3), round_price(final)
    return row


def _variant(bc: SamianBarcode, pid: int, colors: dict, sizes: dict) -> ErpVariant:
    row = ErpVariant(id=bc.samian_id, product_id=pid, barcode=bc.barcode)
    if bc.colorinfo_id:
        row.color_id, row.color_name = bc.colorinfo_id, bc.color
        if c := colors.get(bc.colorinfo_id):
            row.color_name, row.color_value, row.color_priority = c.name, c.hex_code, c.display_priority
            row.color_family = c.family
    if sz := sizes.get(bc.size):
        row.size_id, row.size_name, row.size_value, row.size_priority = sz.pk, sz.name, sz.name, sz.display_priority
    return row


def _images(pid_by_erp: dict[int, int]) -> list[ErpImage]:
    rows = []
    gallery = (
        SamianProductColor.objects.filter(productmain_id__in=pid_by_erp, has_gallery=True)
        .only("samian_id", "productmain_id", "colorinfo_id", "colorsgalery").order_by("samian_id")
    )
    for color in gallery:
        for idx, item in enumerate(color.colorsgalery or []):
            fp = item.get("filePath", "") if isinstance(item, dict) else ""
            if not fp or Path(fp).suffix.lower() not in site_images.IMAGE_EXT:
                continue
            rows.append(ErpImage(
                product_id=pid_by_erp[color.productmain_id], color_id=color.colorinfo_id,
                source_id=color.samian_id * 100 + idx, key=site_images.samian_key(color.productmain_id, fp),
                # Built nightly by build_images; until then the original through the proxy.
                source=f"/api/samian/media/{color.samian_id}/{idx}/", position=len(rows),
            ))
    return rows


class SamianConnector(Connector):
    name = "samian"

    def sync(self, *, full: bool, log: Log) -> dict:
        read = store.Read()
        now = timezone.now()
        links = dict(ProductSamianLink.objects.values_list("product_id", "samian_product_id"))
        sps = {sp.samian_id: sp for sp in SamianProduct.objects.filter(samian_id__in=links.values())}
        linked = {pid: sps[sid] for pid, sid in links.items() if sid in sps}
        prices = _list_prices([sp.pk for sp in linked.values()])
        sold = sold_by_product()
        read.products = [_product(pid, sp, prices.get(sp.pk), sold.get(sp.pk, 0.0), now) for pid, sp in linked.items()]

        pid_by_pk = {sp.pk: pid for pid, sp in linked.items()}
        colors = {c.samian_id: c for c in SamianColor.objects.all()}
        sizes = {sz.name: sz for sz in SamianSize.objects.all()}
        variant_of = {}
        for bc in (SamianBarcode.objects.filter(samian_product_id__in=pid_by_pk, is_active=True)
                   .only("samian_id", "barcode", "size", "color", "colorinfo_id", "samian_product_id")):
            read.variants.append(_variant(bc, pid_by_pk[bc.samian_product_id], colors, sizes))
            variant_of[bc.pk] = bc.samian_id

        titles = dict(SamianWarehouse.objects.values_list("samian_id", "title"))
        for r in (SamianInventory.objects.filter(samian_barcode_id__in=variant_of)
                  .values("samian_barcode_id", "warehouse_id").annotate(total=Sum("qty"))):
            read.stock.append(ErpStock(variant_id=variant_of[r["samian_barcode_id"]], warehouse_id=r["warehouse_id"],
                                       warehouse_title=titles.get(r["warehouse_id"], ""), qty=r["total"] or 0))
        read.images = _images({sp.samian_id: pid for pid, sp in linked.items()})
        result = store.replace(read)
        log(f"erp: {result}")
        return result
