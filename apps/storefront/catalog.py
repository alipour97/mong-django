"""
Read side of the storefront: builds the JSON objects the legacy API returned.

Sources:
- website.*  (imported from DadehfaOnlineShop): category tree, slugs, titles,
  descriptions, variants (color/size) and website media.
- samian.*   (synced from Samian ERP): price, stock per barcode, product images.

Rules:
- Price and stock come from Samian for products linked to it. Products not yet
  linked fall back to the website price and the last legacy stock snapshot.
- Images: Samian gallery first, website media as fallback.
- Listing only shows products in an online category, and (when
  SiteSetting.only_has_media_products is on) only products that have images.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.db.models import Q, Sum
from django.utils import timezone

from apps.samian.models import (
    SamianBarcode,
    SamianInventory,
    SamianPriceListItem,
    SamianProduct,
    SamianProductColor,
)
from apps.samian.services.image_download import IMAGE_EXTENSIONS, local_image_url
from apps.website.models import (
    Brand,
    Category,
    CategoryTag,
    MediaAttachment,
    Product,
    ProductCollection,
    ProductColorMedia,
    ProductComment,
    ProductSamianLink,
    ProductTag,
    ProductVariant,
    SiteSetting,
)

LISTING_CACHE_KEY = "storefront:listing:v1"
LISTING_CACHE_TTL = 120
TREE_CACHE_KEY = "storefront:category-tree:v1"
TREE_CACHE_TTL = 300

COLOR_DETAIL_ID = 1
SIZE_DETAIL_ID = 2


def norm(text: str | None) -> str:
    """Normalize Persian text for matching (Arabic yeh/kaf, ZWNJ, spaces)."""
    return (text or "").replace("ي", "ی").replace("ك", "ک").replace("‌", " ").strip().lower()


def money(value) -> float:
    return float(value or 0)


def absolute_url(url: str) -> str:
    if url.startswith("/"):
        return settings.PUBLIC_BASE_URL.rstrip("/") + url
    return url


def none_if_blank(text: str | None):
    return text if text else None


# -----------------------------------------------------------------------------
# Media
# -----------------------------------------------------------------------------
def media_dict(att: MediaAttachment) -> dict:
    return {
        "id": att.id,
        "isVideo": att.is_video,
        "mediaUrl": absolute_url(att.media_url),
        "alternative": att.alternative,
        "tooltipTitle": att.tooltip_title,
    }


def attachments(table: int, record_ids) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = defaultdict(list)
    ids = list(record_ids)
    if not ids:
        return out
    for att in MediaAttachment.objects.filter(table=table, record_id__in=ids, is_deleted=False).order_by("id"):
        out[att.record_id].append(media_dict(att))
    return out


def tags_for(model, field_name: str, ids) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = defaultdict(list)
    links = model.objects.filter(**{f"{field_name}__in": list(ids)}, is_deleted=False, tag__is_deleted=False)
    for link in links.select_related("tag").order_by("-tag_id"):
        t = link.tag
        out[getattr(link, f"{field_name}")].append(
            {"title": t.title, "parentId": t.parent_id, "parent": None, "tags": None, "id": t.id}
        )
    return out


# -----------------------------------------------------------------------------
# Category tree (online categories reachable from a root)
# -----------------------------------------------------------------------------
@dataclass
class CategoryTree:
    nodes: dict[int, Category]
    children: dict[int | None, list[int]]

    def descendants(self, cat_id: int) -> set[int]:
        out, stack = set(), [cat_id]
        while stack:
            cid = stack.pop()
            if cid in self.nodes and cid not in out:
                out.add(cid)
                stack.extend(self.children.get(cid, []))
        return out

    def ancestors(self, cat_id: int) -> list[Category]:
        chain, cid = [], cat_id
        while cid in self.nodes:
            chain.append(self.nodes[cid])
            cid = self.nodes[cid].parent_id
        return list(reversed(chain))

    def by_slug(self, slug: str) -> Category | None:
        for c in self.nodes.values():
            if c.slug == slug:
                return c
        return None


def category_tree() -> CategoryTree:
    tree = cache.get(TREE_CACHE_KEY)
    if tree:
        return tree
    cats = {c.id: c for c in Category.objects.filter(is_online_active=True, is_deleted=False)}
    by_parent: dict[int | None, list[Category]] = defaultdict(list)
    for c in cats.values():
        by_parent[c.parent_id if c.parent_id in cats else (None if c.parent_id is None else -1)].append(c)
    nodes, children = {}, defaultdict(list)
    stack = [c.id for c in by_parent[None]]
    while stack:
        cid = stack.pop()
        nodes[cid] = cats[cid]
        kids = sorted(by_parent.get(cid, []), key=lambda c: (c.display_priority, c.id))
        children[cid] = [k.id for k in kids]
        stack.extend(children[cid])
    children[None] = sorted((c.id for c in by_parent[None]), key=lambda i: (cats[i].display_priority, i))
    tree = CategoryTree(nodes=nodes, children=dict(children))
    cache.set(TREE_CACHE_KEY, tree, TREE_CACHE_TTL)
    return tree


def category_dict(cat: Category, *, children=None, media=None, tags=None) -> dict:
    return {
        "slug": cat.slug,
        "title": cat.title,
        "inMainPage": cat.in_main_page,
        "parentId": cat.parent_id,
        "displayPriority": cat.display_priority,
        "isOnlineActive": cat.is_online_active,
        "longDescriptionHtml": none_if_blank(cat.long_description_html),
        "shortDescriptionHtml": none_if_blank(cat.short_description_html),
        "categories": children,
        "products": None,
        "mediaAttachments": media or [],
        "tags": tags or [],
        "id": cat.id,
    }


def category_tree_dicts() -> list[dict]:
    tree = category_tree()
    media = attachments(MediaAttachment.Table.CATEGORIES, tree.nodes.keys())
    tags = tags_for(CategoryTag, "category_id", tree.nodes.keys())

    def build(cid: int) -> dict:
        kids = tree.children.get(cid) or []
        return category_dict(
            tree.nodes[cid], children=[build(k) for k in kids] or None, media=media.get(cid), tags=tags.get(cid)
        )

    return [build(cid) for cid in tree.children.get(None, [])]


def breadcrumb_items(cat_id: int | None) -> list[dict]:
    items = [{"position": 1, "name": "خانه", "url": "/"}]
    if cat_id:
        for i, c in enumerate(category_tree().ancestors(cat_id), start=2):
            items.append({"position": i, "name": c.title, "url": f"/products-category/{c.slug}"})
    return items


# -----------------------------------------------------------------------------
# Products
# -----------------------------------------------------------------------------
@dataclass
class Pricing:
    base: float
    reduction: float
    after: int

    @property
    def reduction_price(self) -> float:
        return self.base - self.after


@dataclass
class ProductBundle:
    """Everything needed to render a set of products, loaded in a few queries."""

    products: dict[int, Product]
    variants: dict[int, list[ProductVariant]] = field(default_factory=dict)
    samian: dict[int, SamianProduct] = field(default_factory=dict)  # website product id -> SamianProduct
    list_price: dict[int, int] = field(default_factory=dict)  # samian product pk -> final price
    stock_by_barcode: dict[str, float] = field(default_factory=dict)
    samian_images: dict[int, dict[str, list[dict]]] = field(default_factory=dict)  # product id -> color -> images
    main_media: dict[int, list[dict]] = field(default_factory=dict)
    color_media: dict[int, dict[int, list[dict]]] = field(default_factory=dict)  # product id -> fv id -> images

    @classmethod
    def load(cls, product_ids, *, with_images: bool = True) -> "ProductBundle":
        ids = list(dict.fromkeys(product_ids))
        products = Product.objects.filter(id__in=ids).select_related("category", "brand").in_bulk()
        b = cls(products=products)
        if not products:
            return b

        for v in (
            ProductVariant.objects.filter(product_id__in=ids, is_deleted=False)
            .select_related("color", "size")
            .order_by("id")
        ):
            b.variants.setdefault(v.product_id, []).append(v)

        links = dict(ProductSamianLink.objects.filter(product_id__in=ids).values_list("product_id", "samian_product_id"))
        sps = {sp.samian_id: sp for sp in SamianProduct.objects.filter(samian_id__in=links.values())}
        b.samian = {pid: sps[sid] for pid, sid in links.items() if sid in sps}

        now = timezone.now()
        valid = Q(price_list__isnull=True) | Q(
            price_list__is_active=True, price_list__valid_from__lte=now, price_list__valid_to__gte=now
        )
        for spk, final in (
            SamianPriceListItem.objects.filter(valid, samian_product_id__in=[sp.pk for sp in b.samian.values()])
            .exclude(final_price__isnull=True)
            .values_list("samian_product_id", "final_price")
        ):
            if spk not in b.list_price or final < b.list_price[spk]:
                b.list_price[spk] = final

        barcodes = {v.barcode for vs in b.variants.values() for v in vs if v.barcode}
        if barcodes:
            rows = (
                SamianInventory.objects.filter(samian_barcode__barcode__in=barcodes)
                .values("samian_barcode__barcode")
                .annotate(total=Sum("qty"))
            )
            b.stock_by_barcode = {r["samian_barcode__barcode"]: float(r["total"] or 0) for r in rows}
            b._known_barcodes = set(
                SamianBarcode.objects.filter(barcode__in=barcodes).values_list("barcode", flat=True)
            )
        else:
            b._known_barcodes = set()

        if with_images:
            b._load_images(ids)
        return b

    def _load_images(self, ids):
        spk_to_pid = {sp.pk: pid for pid, sp in self.samian.items()}
        for color in SamianProductColor.objects.filter(samian_product_id__in=spk_to_pid.keys(), has_gallery=True).order_by("samian_id"):
            pid = spk_to_pid[color.samian_product_id]
            imgs = []
            for idx, item in enumerate(color.colorsgalery or []):
                fp = item.get("filePath", "") if isinstance(item, dict) else ""
                if not fp or Path(fp).suffix.lower() not in IMAGE_EXTENSIONS:
                    continue
                url = local_image_url(color.productmain_id, fp) or f"/api/samian/media/{color.samian_id}/{idx}/"
                imgs.append({
                    "id": color.samian_id * 100 + idx,
                    "mediaUrl": absolute_url(url),
                    "isVideo": False,
                    "alternative": "",
                    "tooltipTitle": "",
                })
            if imgs:
                self.samian_images.setdefault(pid, {}).setdefault(norm(color.color_name), []).extend(imgs)

        self.main_media = attachments(MediaAttachment.Table.PRODUCTS, ids)
        cms = list(ProductColorMedia.objects.filter(product_id__in=ids, is_deleted=False))
        cm_media = attachments(MediaAttachment.Table.FEATURE_VALUE_MEDIAS, [cm.id for cm in cms])
        for cm in cms:
            if cm_media.get(cm.id):
                self.color_media.setdefault(cm.product_id, {}).setdefault(cm.feature_value_id, []).extend(cm_media[cm.id])

    # -- per product -------------------------------------------------------
    def pricing(self, pid: int) -> Pricing:
        p = self.products[pid]
        sp = self.samian.get(pid)
        if sp and sp.sale_price:
            base = sp.sale_price
            final = self.list_price.get(sp.pk)
            if final and final < base:
                return Pricing(float(base), round((base - final) * 100 / base, 2), int(final))
            return Pricing(float(base), 0.0, int(base))
        base = money(p.price)
        reduction = money(p.reduction)
        after = int(base * (100 - reduction) / 100) if reduction else int(base)
        return Pricing(base, reduction, after)

    def variant_stock(self, pid: int, v: ProductVariant) -> float:
        if pid in self.samian:
            return self.stock_by_barcode.get(v.barcode, 0.0)
        # Not linked to Samian yet: last stock known by the legacy site.
        return money(v.legacy_qty)

    def has_images(self, pid: int) -> bool:
        return bool(self.samian_images.get(pid) or self.main_media.get(pid) or self.color_media.get(pid))

    def main_images(self, pid: int) -> list[dict]:
        samian = [img for imgs in self.samian_images.get(pid, {}).values() for img in imgs]
        if samian:
            return samian
        if self.main_media.get(pid):
            return self.main_media[pid]
        return [img for imgs in self.color_media.get(pid, {}).values() for img in imgs]

    def color_images(self, pid: int, fv) -> list[dict]:
        return self.samian_images.get(pid, {}).get(norm(fv.name)) or self.color_media.get(pid, {}).get(fv.id) or []

    def details(self, pid: int, pricing: Pricing, *, with_barcode: bool) -> list[dict]:
        colors: dict[int, dict] = {}
        sizes_fixed: dict[int, dict] = {}
        size_items = []
        for v in self.variants.get(pid, []):
            if not v.color:
                continue
            qty = self.variant_stock(pid, v)
            c = colors.get(v.color_id)
            if c is None:
                c = colors[v.color_id] = {
                    "id": v.color_id, "parentId": None, "name": v.color.name, "value": v.color.value,
                    "images": self.color_images(pid, v.color), "price": pricing.base,
                    "reduction": pricing.reduction, "discount": 0, "mojodi": 0.0, "barcode": "",
                    "displayPriority": v.color.display_priority, "productVariantId": 0,
                }
            c["mojodi"] += qty
            if v.size:
                sizes_fixed.setdefault(v.size_id, {
                    "id": v.size_id, "name": v.size.name, "value": v.size.value, "score": 0,
                    "displayPriority": v.size.display_priority,
                })
                size_items.append({
                    "id": v.size_id, "parentId": v.color_id, "name": v.size.name, "value": v.size.value,
                    "images": None, "price": 0.0, "reduction": 0.0, "discount": 0, "mojodi": qty,
                    "barcode": v.barcode if with_barcode else "", "displayPriority": v.size.display_priority,
                    "productVariantId": v.id,
                })
        if not colors:
            return []
        # Colors with more stock first, as the legacy site did; sizes follow their color.
        order = sorted(colors, key=lambda cid: (-colors[cid]["mojodi"], cid))
        colors = {cid: colors[cid] for cid in order}
        rank = {cid: i for i, cid in enumerate(order)}
        size_items.sort(key=lambda item: rank[item["parentId"]])
        fixed_colors = [
            {"id": c["id"], "name": c["name"], "value": c["value"], "score": 0, "displayPriority": c["displayPriority"]}
            for c in colors.values()
        ]
        return [
            {"id": COLOR_DETAIL_ID, "hasColor": True, "fixedList": fixed_colors, "title": "رنگ",
             "items": list(colors.values()), "defaultItemId": None},
            {"id": SIZE_DETAIL_ID, "hasColor": False, "fixedList": list(sizes_fixed.values()), "title": "سایز",
             "items": size_items, "defaultItemId": None},
        ]

    def in_stock(self, pid: int) -> bool:
        return any(self.variant_stock(pid, v) > 0 for v in self.variants.get(pid, []))

    def list_item(self, pid: int) -> dict:
        p = self.products[pid]
        pr = self.pricing(pid)
        return {
            "id": p.id,
            "slug": p.slug,
            "categoryId": p.category_id,
            "parentCategoryId": p.category.parent_id if p.category else None,
            "brandId": p.brand_id,
            "productName": p.title,
            "longDescriptionHtml": none_if_blank(p.long_description_html),
            "shortDescriptionHtml": none_if_blank(p.short_description_html),
            "mainImages": self.main_images(pid),
            "product_Base_Price": pr.base,
            "product_base_reduction": pr.reduction,
            "productBaseVat": money(p.vat),
            "reductionPercent": pr.reduction,
            "price": pr.base,
            "priceAfterReduction": pr.after,
            "reductionPrice": pr.reduction_price,
            "details": self.details(pid, pr, with_barcode=False),
            "selectedProductId": None,
            "sortingWeight": None,
        }

    def full_detail(self, pid: int) -> dict:
        p = self.products[pid]
        pr = self.pricing(pid)
        comments = ProductComment.objects.filter(product_id=pid, is_deleted=False, is_active=True).count()
        tags = tags_for(ProductTag, "product_id", [pid]).get(pid, [])
        sp = self.samian.get(pid)
        return {
            "id": p.id,
            "slug": p.slug,
            "longDescriptionHtml": none_if_blank(p.long_description_html),
            "shortDescriptionHtml": none_if_blank(p.short_description_html),
            "barcode": p.barcode,
            "categoryId": p.category_id,
            "parentCategoryId": p.category.parent_id if p.category else None,
            "brandId": p.brand_id,
            "productName": p.title,
            "ProductName_En": none_if_blank(sp.name_en if sp else ""),
            "mainImages": self.main_images(pid),
            "productSizeGuid": none_if_blank(p.size_guide),
            "product_Base_Price": pr.base,
            "product_base_reduction": pr.reduction,
            "productBaseVat": money(p.vat),
            "reductionPercent": pr.reduction,
            "price": pr.base,
            "priceAfterReduction": pr.after,
            "reductionPrice": pr.reduction_price,
            "details": self.details(pid, pr, with_barcode=True),
            "description": none_if_blank(p.description),
            "shortDesc": none_if_blank(p.short_desc),
            "commentCount": comments,
            "promotionLabel": None,
            "productFeatures": None,
            "breadcrumbs": None,
            "tags": tags,
        }


# -----------------------------------------------------------------------------
# Listing index: one compact row per listable product, cached briefly
# -----------------------------------------------------------------------------
@dataclass
class ListingRow:
    id: int
    title: str
    category_id: int | None
    brand_id: int | None
    price_after: int
    reduction: float
    in_stock: bool
    color_ids: frozenset
    created: object
    view_count: int
    sales_count: int
    buyer_score: float


def listing_rows() -> list[ListingRow]:
    rows = cache.get(LISTING_CACHE_KEY)
    if rows is not None:
        return rows
    tree = category_tree()
    setting = SiteSetting.objects.filter(is_deleted=False).first()
    only_media = bool(setting and setting.only_has_media_products)

    ids = list(
        Product.objects.filter(is_deleted=False, is_active=True, category_id__in=tree.nodes.keys()).values_list("id", flat=True)
    )
    if only_media:
        # The legacy site listed products that have a gallery per color; Samian galleries count too.
        with_media = set(ProductColorMedia.objects.filter(product_id__in=ids, is_deleted=False).values_list("product_id", flat=True))
        with_media |= set(
            ProductSamianLink.objects.filter(
                product_id__in=ids,
                samian_product_id__in=SamianProductColor.objects.filter(has_gallery=True).values("productmain_id"),
            ).values_list("product_id", flat=True)
        )
        ids = [i for i in ids if i in with_media]

    bundle = ProductBundle.load(ids, with_images=False)
    rows = []
    for pid, p in bundle.products.items():
        pr = bundle.pricing(pid)
        if pr.after <= 0:
            continue
        rows.append(ListingRow(
            id=pid, title=norm(p.title), category_id=p.category_id, brand_id=p.brand_id,
            price_after=pr.after, reduction=pr.reduction, in_stock=bundle.in_stock(pid),
            color_ids=frozenset(v.color_id for v in bundle.variants.get(pid, []) if v.color_id),
            created=p.created, view_count=p.view_count, sales_count=p.sales_count,
            buyer_score=float(p.buyer_score_average or 0),
        ))
    cache.set(LISTING_CACHE_KEY, rows, LISTING_CACHE_TTL)
    return rows


def _newest(r):
    return (-(r.created.timestamp() if r.created else 0), r.id)


# sortCriteriaId -> ascending sort key
SORT_KEYS = {
    1: lambda r: (-r.view_count, r.id),    # پربازدیدترین
    2: _newest,                            # جدیدترین (also the default)
    3: lambda r: (-r.sales_count, r.id),   # پرفروش ترین
    4: lambda r: (r.price_after, r.id),    # ارزان ترین
    5: lambda r: (-r.price_after, r.id),   # گران ترین
    6: lambda r: (-r.buyer_score, r.id),   # پیشنهاد خریداران
    7: _newest,                            # منتخب
    8: lambda r: (-r.reduction, r.id),     # بیشترین تخفیف
    9: lambda r: (r.reduction, r.id),      # کمترین تخفیف
}
SORT_CRITERIA = [
    {"id": 1, "sortKeyFa": "پربازدیدترین"}, {"id": 2, "sortKeyFa": "جدیدترین"},
    {"id": 3, "sortKeyFa": "پرفروش ترین"}, {"id": 4, "sortKeyFa": "ارزان ترین"},
    {"id": 5, "sortKeyFa": "گران ترین"}, {"id": 6, "sortKeyFa": "پیشنهاد خریداران"},
    {"id": 7, "sortKeyFa": "منتخب"}, {"id": 8, "sortKeyFa": "بیشترین تخفیف"},
    {"id": 9, "sortKeyFa": "کمترین تخفیف"},
]


def filter_rows(payload: dict) -> list[ListingRow]:
    rows = listing_rows()
    tree = category_tree()

    cat_ids = [int(c) for c in payload.get("filteredCategoryIds") or [] if c]
    if cat_ids:
        allowed = set().union(*(tree.descendants(c) for c in cat_ids))
        rows = [r for r in rows if r.category_id in allowed]
    if payload.get("filteredBrandId"):
        rows = [r for r in rows if r.brand_id == int(payload["filteredBrandId"])]
    coll_ids = [int(c) for c in payload.get("filteredCollectionIds") or [] if c]
    if coll_ids:
        links = ProductCollection.objects.filter(collection_id__in=coll_ids, is_deleted=False)
        pids = set(links.exclude(product_id=None).values_list("product_id", flat=True))
        bids = set(links.exclude(brand_id=None).values_list("brand_id", flat=True))
        rows = [r for r in rows if r.id in pids or r.brand_id in bids]
    if payload.get("fromPrice"):
        rows = [r for r in rows if r.price_after >= int(payload["fromPrice"])]
    if payload.get("toPrice"):
        rows = [r for r in rows if r.price_after <= int(payload["toPrice"])]
    if payload.get("hasDiscount"):
        rows = [r for r in rows if r.reduction > 0]
    if payload.get("isInStock"):
        rows = [r for r in rows if r.in_stock]
    feature_ids = {int(f) for f in payload.get("filteredFeatureId") or [] if f}
    if feature_ids:
        rows = [r for r in rows if r.color_ids & feature_ids]
    if payload.get("search"):
        q = norm(payload["search"])
        rows = [r for r in rows if q in r.title]

    return sorted(rows, key=SORT_KEYS.get(int(payload.get("sortCriteriaId") or 2), _newest))


def page_of(rows: list, page_number, page_size) -> tuple[list, int]:
    size = max(1, int(page_size or 20))
    number = max(1, int(page_number or 1))
    total_pages = math.ceil(len(rows) / size) if rows else 0
    return rows[(number - 1) * size: number * size], total_pages


def render_list(ids: list[int]) -> list[dict]:
    bundle = ProductBundle.load(ids)
    return [bundle.list_item(pid) for pid in ids if pid in bundle.products]


def brands_of(rows: list[ListingRow]) -> list[dict]:
    ids = {r.brand_id for r in rows if r.brand_id}
    return [{"title": b.title, "id": b.id} for b in Brand.objects.filter(id__in=ids).order_by("-id")]


def clear_caches():
    cache.delete_many([LISTING_CACHE_KEY, TREE_CACHE_KEY])
