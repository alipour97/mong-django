"""
The admin's product index: one row per product in a category that is on the
site, with Samian price, stock and photo count, so the product list can filter
and page over all of them. Cached briefly, like the storefront listing.

Unlike the storefront, products without photos or stock are included: the
admin needs to see what is missing.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.core.cache import cache

from apps.storefront import catalog
from apps.website.models import Product, ProductComment

CACHE_KEY = "adminapi:product-rows:v1"
CACHE_TTL = 600  # edits in the admin clear it (clear())


@dataclass
class AdminRow:
    id: int
    title: str          # normalized, for search
    name: str
    barcode: str
    category_id: int | None
    is_saleable: bool
    price: float
    reduction: float
    after: int
    qty: float
    media_count: int
    has_score: bool
    has_long_description: bool
    has_short_description: bool


def admin_rows() -> list[AdminRow]:
    rows = cache.get(CACHE_KEY)
    if rows is not None:
        return rows
    tree = catalog.category_tree()
    ids = list(
        catalog.in_samian(Product.objects.filter(is_deleted=False, is_active=True, category_id__in=tree.nodes.keys()))
        .values_list("id", flat=True)
    )
    bundle = catalog.ProductBundle.load(ids)
    scored = set(
        ProductComment.objects.filter(product_id__in=ids, is_deleted=False, score__isnull=False)
        .values_list("product_id", flat=True)
    )
    rows = []
    for pid, p in bundle.products.items():
        pr = bundle.pricing(pid)
        rows.append(AdminRow(
            id=pid, title=catalog.norm(p.title), name=p.title, barcode=p.barcode, category_id=p.category_id,
            is_saleable=p.is_saleable, price=pr.base, reduction=pr.reduction, after=pr.after,
            qty=sum(bundle.variant_stock(pid, v) for v in bundle.variants.get(pid, [])),
            media_count=len(bundle.main_images(pid)), has_score=pid in scored,
            has_long_description=bool(p.long_description_html), has_short_description=bool(p.short_description_html),
        ))
    rows.sort(key=lambda r: r.id)
    cache.set(CACHE_KEY, rows, CACHE_TTL)
    return rows


def clear() -> None:
    cache.delete(CACHE_KEY)
    catalog.clear_caches()
