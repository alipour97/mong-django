"""
The Samian connector. Samian's own sync (apps/samian) keeps its tables fresh; this copies what
the site sells out of them into the site's tables. Variants keep their site id by barcode, and
colors and sizes by name, so moving between sales programs changes the sync and nothing else:
photos and AI copy stay LEBAZAI's. Sending invoices to Samian is the write phase and is not built yet.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Max, Q, Sum
from django.utils import timezone

from apps.samian.models import (
    SamianBarcode,
    SamianColor,
    SamianInventory,
    SamianPriceListItem,
    SamianProduct,
    SamianSalesRow,
    SamianSize,
    SamianWarehouse,
)
from apps.website import images as site_images
from apps.storefront.catalog import COLOR_DETAIL_ID, SIZE_DETAIL_ID, norm
from apps.website.models import FeatureValue, ProductSamianLink, ProductVariant

from . import specs, store
from .connector import Connector, Log


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


def _product(pid: int, sp: SamianProduct, final, sold: float) -> dict:
    row = {
        "id": pid, "erp_id": sp.samian_id, "on_sale": True, "name_en": sp.name_en or "", "sold": sold,
        "attributes": specs.clean({specs.MATERIAL: sp.material, specs.SEASON: specs.season(sp.season),
                                   specs.FIT: specs.fit(sp.fit), specs.LENGTH: specs.length(sp.height),
                                   specs.STYLE: specs.style(sp.style)}),
        "size_guide_key": site_images.samian_key(sp.samian_id, sp.size_help_path) if sp.size_help_path else "",
        "price": 0, "reduction": Decimal(0), "sale_price": 0,
    }
    base = sp.sale_price
    if base:
        row["price"], row["sale_price"] = int(base), int(base)
        if final and final < base:
            row["reduction"] = Decimal(str(round((base - final) * 100 / base, 3)))
            row["sale_price"] = round_price(final)
    return row


class _SiteValues:
    """Samian's colors and sizes as the site's, found by name so favorites, photos and filters keep their ids."""

    def __init__(self):
        self.ids = {(v.feature_id, norm(v.name)): v.id for v in FeatureValue.objects.filter(is_deleted=False).order_by("-id")}

    def id_of(self, feature_id: int, name: str, value: str, priority: int) -> int:
        key = (feature_id, norm(name))
        if key not in self.ids:
            self.ids[key] = FeatureValue.objects.create(feature_id=feature_id, name=name, value=value, display_priority=priority).id
        return self.ids[key]


def _variant(variant_id: int, bc: SamianBarcode, pid: int, colors: dict, sizes: dict, values: _SiteValues) -> store.VariantRow:
    color_id, color_name, color_value, color_priority, color_family = None, "", "", 0, ""
    if bc.colorinfo_id:
        color_name, c = bc.color or "", colors.get(bc.colorinfo_id)
        if c:
            color_name, color_value, color_priority, color_family = c.name, c.hex_code, c.display_priority, c.family
        color_id = values.id_of(COLOR_DETAIL_ID, color_name, color_value, color_priority)
    size_id, size_name, size_priority = None, "", 0
    if sz := sizes.get(bc.size):
        size_name, size_priority = sz.name, sz.display_priority
        size_id = values.id_of(SIZE_DETAIL_ID, size_name, size_name, size_priority)
    return store.VariantRow(
        id=variant_id, product_id=pid, erp_ref=bc.samian_id, barcode=bc.barcode, color_id=color_id, color_name=color_name,
        color_value=color_value, color_priority=color_priority, color_family=color_family, size_id=size_id, size_name=size_name,
        size_value=size_name, size_priority=size_priority,
    )


class SamianConnector(Connector):
    name = "samian"

    def sync(self, *, force: bool = False, log: Log) -> dict:
        read = store.Read()
        links = dict(ProductSamianLink.objects.values_list("product_id", "samian_product_id"))
        sps = {sp.samian_id: sp for sp in SamianProduct.objects.filter(samian_id__in=links.values())}
        linked = {pid: sps[sid] for pid, sid in links.items() if sid in sps}
        prices = _list_prices([sp.pk for sp in linked.values()])
        sold = sold_by_product()
        read.products = [_product(pid, sp, prices.get(sp.pk), sold.get(sp.pk, 0.0)) for pid, sp in linked.items()]

        pid_by_pk = {sp.pk: pid for pid, sp in linked.items()}
        colors = {c.samian_id: c for c in SamianColor.objects.all()}
        sizes = {sz.name: sz for sz in SamianSize.objects.all()}
        values = _SiteValues()
        site_ids = dict(ProductVariant.objects.exclude(barcode="").values_list("barcode", "id"))
        next_id = (ProductVariant.objects.aggregate(top=Max("id"))["top"] or 0) + 1
        variant_of = {}
        for bc in (SamianBarcode.objects.filter(samian_product_id__in=pid_by_pk, is_active=True)
                   .only("samian_id", "barcode", "size", "color", "colorinfo_id", "samian_product_id")):
            variant_id = site_ids.get(bc.barcode)
            if variant_id is None:
                variant_id, next_id = next_id, next_id + 1
            read.variants.append(_variant(variant_id, bc, pid_by_pk[bc.samian_product_id], colors, sizes, values))
            variant_of[bc.pk] = variant_id

        titles = dict(SamianWarehouse.objects.values_list("samian_id", "title"))
        for r in (SamianInventory.objects.filter(samian_barcode_id__in=variant_of)
                  .values("samian_barcode_id", "warehouse_id").annotate(total=Sum("qty"))):
            if r["total"] and r["total"] > 0:
                read.stock.append(store.StockRow(variant_of[r["samian_barcode_id"]], r["warehouse_id"],
                                                 titles.get(r["warehouse_id"], ""), r["total"]))
        result = store.apply(read, force=force)
        log(f"erp: {result}")
        return result
