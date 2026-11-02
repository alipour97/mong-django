"""
The admin's product index: one row per product in a category that is on the
site, with Samian price, stock and photo count, so the product list can filter
and page over all of them. Kept warm like the storefront listing (apps.storefront.warm): edits and the
TTL only mark it stale, and it is rebuilt in the background.

Unlike the storefront, products without photos or stock are included: the
admin needs to see what is missing.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from django.db.models import Sum

from apps.storefront import catalog, warm
from apps.erp.models import LebazaiImage
from apps.erp.store import online_stock
from apps.website.models import HiddenImage, Product, ProductAIProfile, ProductComment, SiteSetting

CACHE_TTL = 600  # edits in the admin mark it stale (clear())


@dataclass
class AdminRow:
    id: int
    title: str          # normalized, for search
    name: str
    barcode: str
    category_id: int | None
    on_site: bool       # whether the site shows it now, by its own settings
    price: int
    reduction: float
    after: int
    qty: float
    media_count: int
    has_score: bool
    has_long_description: bool
    has_short_description: bool


def admin_rows() -> list[AdminRow]:
    return warm.get(catalog.ADMIN_ROWS_CACHE_KEY, CACHE_TTL, _build)


def _build() -> list[AdminRow]:
    tree = catalog.category_tree()
    products = catalog.on_sale(Product.objects.filter(is_deleted=False, is_active=True))
    setting = SiteSetting.objects.filter(is_deleted=False).first()
    min_qty = float(setting.min_qty) if setting else 0.0
    only_media = bool(setting and setting.only_has_media_products)
    # Every product of the software is listed here, with or without photos, so no bundle: only what the rows need.
    qty: dict[int, float] = defaultdict(float)
    for pid, total in online_stock().values("variant_id", "variant__product_id").annotate(total=Sum("qty")).values_list("variant__product_id", "total"):
        qty[pid] += max(0.0, float(total or 0) - min_qty)
    hidden = set(HiddenImage.objects.values_list("key", flat=True))
    media: dict[int, int] = defaultdict(int)
    for pid, key in LebazaiImage.objects.values_list("product_id", "key"):
        media[pid] += key not in hidden
    scored = set(
        ProductComment.objects.filter(is_deleted=False, score__isnull=False).values_list("product_id", flat=True)
    )
    # The two descriptions of a row are the site's own text, else LEBAZAI's (views/products.py DescriptionsView).
    ai_titled = set(ProductAIProfile.objects.exclude(title="").values_list("product_id", flat=True))
    ai_described = set(ProductAIProfile.objects.exclude(description="").values_list("product_id", flat=True))
    rows = []
    for p in products.only("id", "title", "barcode", "category_id", "price", "reduction", "sale_price",
                           "long_description_html", "short_description_html"):
        pr = catalog.Pricing(p.price, float(p.reduction), p.sale_price)
        rows.append(AdminRow(
            id=p.id, title=catalog.norm(p.title), name=p.title, barcode=p.barcode, category_id=p.category_id,
            on_site=p.category_id in tree.nodes and pr.after > 0 and (media[p.id] > 0 or not only_media),
            price=pr.base, reduction=pr.reduction, after=pr.after, qty=qty[p.id], media_count=media[p.id], has_score=p.id in scored,
            has_long_description=bool(p.long_description_html) or p.id in ai_described,
            has_short_description=bool(p.short_description_html) or p.id in ai_titled,
        ))
    rows.sort(key=lambda r: r.id)
    return rows


def clear() -> None:
    catalog.clear_caches()
