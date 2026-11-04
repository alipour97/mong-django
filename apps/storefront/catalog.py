"""
Read side of the storefront: builds the JSON objects the legacy API returned.

Sources:
- website.*  the site's own tables: products, variants, stock, categories. The
  sales software's sync (apps/erp) keeps what it owns up to date in them; slugs,
  descriptions and website media are the site's.
- erp.LebazaiImage: product photos, from LEBAZAI or uploaded in the admin.

Rules:
- The sales software is the reference: a website product is shown only while its
  last read had it on sale (ProductBundle.load drops the others). Nothing here
  reaches the software, so the site goes on with its last read without it.
- Images are served as pre-built WebP from /img/ (apps/website/images.py) once
  build_images ran, else from their source.
- Stock is the sum over the warehouses sold online (apps.erp.store.online_stock),
  minus SiteSetting.min_qty kept back per variant.
- Only Mong products exist here; customers always see the one brand MONG_BRAND. Listing
  shows products in an online category, and (when SiteSetting.only_has_media_products is on) only products
  that have images.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field

from django.conf import settings
from django.db.models import Avg, Sum

from apps.erp.models import LebazaiImage
from apps.erp.store import online_stock
from apps.website import images as site_images
from apps.website.models import (
    Category,
    CategoryTag,
    MediaAttachment,
    Product,
    ProductAIProfile,
    ProductCollection,
    ProductComment,
    ProductTag,
    ProductVariant,
    HiddenImage,
    SelectedProduct,
    SiteSetting,
)

from . import warm

# مانگ and توليد are one brand for customers: every product is shown as Mong.
MONG_BRAND = {"id": 15, "title": "مانگ"}

LISTING_CACHE_KEY = "storefront:listing:v13"
LISTING_CACHE_TTL = 300  # a stale listing is rebuilt in the background
TREE_CACHE_KEY = "storefront:category-tree:v2"
TREE_CACHE_TTL = 300
ADMIN_ROWS_CACHE_KEY = "adminapi:product-rows:v2"

COLOR_DETAIL_ID = 1
SIZE_DETAIL_ID = 2


def norm(text: str | None) -> str:
    """Normalize Persian text for matching (Arabic yeh/kaf, ZWNJ, spaces)."""
    return (text or "").replace("ي", "ی").replace("ك", "ک").replace("‌", " ").strip().lower()


_PERSIAN_LETTERS = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک"})


def display_name(text: str | None) -> str:
    """
    A product or category name as customers see it: the sales software writes
    Arabic ي/ك, which Persian keyboards and searches type as ی/ک. Only letters
    change, so slugs and ERP matching (which use the stored title) are untouched.
    """
    return (text or "").translate(_PERSIAN_LETTERS)


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
        "mediaUrl": absolute_url(site_images.site_media_url(att.media_url)),
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
    return warm.get(TREE_CACHE_KEY, TREE_CACHE_TTL, _build_category_tree)


def _build_category_tree() -> CategoryTree:
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
    return CategoryTree(nodes=nodes, children=dict(children))


def category_dict(cat: Category, *, children=None, media=None, tags=None) -> dict:
    return {
        "slug": cat.slug,
        "title": display_name(cat.title),
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
    """Home, then the category path without its root: Samian level 1 (زنانه) is the same for every Mong product."""
    items = [{"position": 1, "name": "خانه", "url": "/"}]
    if cat_id:
        chain = category_tree().ancestors(cat_id)
        if len(chain) > 1 and chain[0].parent_id is None:
            chain = chain[1:]
        for i, c in enumerate(chain, start=2):
            items.append({"position": i, "name": display_name(c.title), "url": f"/products-category/{c.slug}"})
    return items


# -----------------------------------------------------------------------------
# Products
# -----------------------------------------------------------------------------
@dataclass
class Pricing:
    base: int
    reduction: float
    after: int

    @property
    def reduction_price(self) -> int:
        return self.base - self.after


@dataclass(frozen=True)
class Option:
    """A color or a size as the site shows it."""

    id: int
    name: str
    value: str
    display_priority: int


@dataclass(frozen=True)
class Variant:
    """A sellable color and size of a product."""

    id: int        # productVariantId on the site
    erp_ref: int | None
    barcode: str
    color: Option | None
    size: Option | None

    @property
    def color_id(self) -> int | None:
        return self.color.id if self.color else None

    @property
    def size_id(self) -> int | None:
        return self.size.id if self.size else None


def _variant(row: ProductVariant) -> Variant:
    return Variant(
        id=row.id, erp_ref=row.erp_ref, barcode=row.barcode,
        color=Option(row.color_id, row.color_name, row.color_value, row.color_priority) if row.color_id else None,
        size=Option(row.size_id, row.size_name, row.size_value, row.size_priority) if row.size_id else None,
    )


def _image_dict(img: LebazaiImage, hidden: set[str], include_hidden: bool) -> dict:
    url = site_images.public_url(img.key) if img.key and site_images.is_built(img.key) else site_images.site_media_url(img.source_url)
    return {
        "id": img.id,
        "mediaUrl": absolute_url(url),
        "isVideo": False,
        "alternative": "",
        "tooltipTitle": "",
        **({"key": img.key, "isHidden": img.key in hidden} if include_hidden else {}),
    }


@dataclass
class ProductBundle:
    """Everything needed to render a set of products, loaded in a few queries."""

    products: dict[int, Product]
    variants: dict[int, list[Variant]] = field(default_factory=dict)
    stock: dict[int, float] = field(default_factory=dict)  # variant id -> qty in the online warehouses
    color_gallery: dict[int, dict[int, list[dict]]] = field(default_factory=dict)  # product id -> color id -> images
    only_media: bool = False  # SiteSetting.only_has_media_products: hide colors that have no images
    min_qty: float = 0.0  # SiteSetting.min_qty: safety stock per variant that is never offered online
    ai_profiles: dict[int, ProductAIProfile] = field(default_factory=dict)  # website product id -> ProductAIProfile

    @classmethod
    def load(cls, product_ids, *, with_images: bool = True, include_hidden: bool = False) -> "ProductBundle":
        """include_hidden: also the photos hidden in the admin, marked isHidden (for the admin's product page)."""
        ids = list(dict.fromkeys(product_ids))
        products = Product.objects.filter(id__in=ids).select_related("category", "brand").in_bulk()
        setting = SiteSetting.objects.filter(is_deleted=False).first()
        b = cls(
            products=products,
            only_media=bool(with_images and setting and setting.only_has_media_products),
            min_qty=float(setting.min_qty) if setting else 0.0,
        )
        if not products:
            return b

        # Not in the sales software -> not on the site.
        b.products = {pid: p for pid, p in products.items() if p.on_sale}
        ids = list(b.products)
        if not ids:
            return b

        for row in ProductVariant.objects.filter(product_id__in=ids).order_by("id"):
            b.variants.setdefault(row.product_id, []).append(_variant(row))
        variant_ids = [v.id for vs in b.variants.values() for v in vs]
        b.stock = {
            r["variant_id"]: float(r["total"] or 0)
            for r in online_stock().filter(variant_id__in=variant_ids).values("variant_id").annotate(total=Sum("qty"))
        }

        b.ai_profiles = {ap.product_id: ap for ap in ProductAIProfile.objects.filter(product_id__in=ids)}
        if with_images:
            b._load_images(ids, include_hidden)
        return b

    def _load_images(self, ids, include_hidden: bool = False):
        hidden = set(HiddenImage.objects.values_list("key", flat=True))
        for img in LebazaiImage.objects.filter(product_id__in=ids):
            if img.key in hidden and not include_hidden:
                continue
            self.color_gallery.setdefault(img.product_id, {}).setdefault(img.color_id, []).append(_image_dict(img, hidden, include_hidden))

    # -- per product -------------------------------------------------------
    def pricing(self, pid: int) -> Pricing:
        p = self.products.get(pid)
        if not p:
            return Pricing(0.0, 0.0, 0)
        return Pricing(p.price, float(p.reduction), p.sale_price)

    def variant_stock(self, pid: int, v: Variant) -> float:
        return max(0.0, self.stock.get(v.id, 0.0) - self.min_qty)

    def has_images(self, pid: int) -> bool:
        return bool(self.color_gallery.get(pid))

    def main_images(self, pid: int) -> list[dict]:
        return [img for imgs in self.color_gallery.get(pid, {}).values() for img in imgs]

    def color_images(self, pid: int, v: Variant) -> list[dict]:
        return self.color_gallery.get(pid, {}).get(v.color_id) or []

    def visible_variants(self, pid: int) -> list[Variant]:
        """Variants the site shows: with a color, and (like the legacy site) only colors that have images."""
        out = []
        for v in self.variants.get(pid, []):
            if not v.color:
                continue
            if self.only_media and not self.color_images(pid, v):
                continue
            out.append(v)
        return out

    def details(self, pid: int, pricing: Pricing, *, with_barcode: bool) -> list[dict]:
        colors: dict[int, dict] = {}
        sizes_fixed: dict[int, dict] = {}
        size_items = []
        for v in self.visible_variants(pid):
            qty = self.variant_stock(pid, v)
            c = colors.get(v.color_id)
            if c is None:
                c = colors[v.color_id] = {
                    "id": v.color_id, "parentId": None, "name": v.color.name, "value": v.color.value,
                    "images": self.color_images(pid, v), "price": pricing.base,
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
                    "images": None, "price": 0, "reduction": 0.0, "discount": 0, "mojodi": qty,
                    "barcode": v.barcode if with_barcode else "", "displayPriority": v.size.display_priority,
                    "productVariantId": v.id,
                })
        if not colors:
            return []
        # Legacy order: sizes by stock (desc), then color id, then variant id;
        # colors in the order they first appear in that list.
        size_items.sort(key=lambda item: (-item["mojodi"], item["parentId"], item["productVariantId"]))
        order = list(dict.fromkeys(item["parentId"] for item in size_items))
        order += sorted(cid for cid in colors if cid not in order)
        colors = {cid: colors[cid] for cid in order}
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
        return any(self.variant_stock(pid, v) > 0 for v in self.visible_variants(pid))

    def list_item(self, pid: int) -> dict:
        p = self.products[pid]
        pr = self.pricing(pid)
        ai = self.ai_profiles.get(pid)
        return {
            "id": p.id,
            "slug": p.slug,
            "categoryId": p.category_id,
            "parentCategoryId": p.category.parent_id if p.category else None,
            "brandId": MONG_BRAND["id"],
            "productName": display_name(p.title),
            "aiTitle": (ai.title if ai and ai.title else ""),
            "longDescriptionHtml": none_if_blank(p.long_description_html),
            "shortDescriptionHtml": none_if_blank(p.short_description_html),
            "mainImages": self.main_images(pid),
            "product_Base_Price": pr.base,
            "product_base_reduction": pr.reduction,
            "productBaseVat": float(p.vat or 0),
            "reductionPercent": pr.reduction,
            "price": pr.base,
            "priceAfterReduction": pr.after,
            "reductionPrice": pr.reduction_price,
            "details": self.details(pid, pr, with_barcode=False),
            "selectedProductId": None,
            "sortingWeight": None,
        }

    def size_guide(self, pid: int) -> dict | None:
        """The size chart: the sales software's, else one set in the admin for the product, else for its category."""
        key = self.products[pid].size_guide_key
        if key and site_images.is_built(key):
            return {"id": 0, "isVideo": False, "mediaUrl": absolute_url(site_images.public_url(key)),
                    "alternative": "راهنمای سایز", "tooltipTitle": ""}
        guide = MediaAttachment.objects.filter(
            table=MediaAttachment.Table.PRODUCTS, record_id=pid, is_product_guid=True, is_deleted=False,
        ).order_by("-id").first()
        p = self.products[pid]
        if guide is None and p.category_id:
            chain = [c.id for c in reversed(category_tree().ancestors(p.category_id))]
            by_cat = {
                a.record_id: a for a in MediaAttachment.objects.filter(
                    table=MediaAttachment.Table.CATEGORIES, record_id__in=chain, is_product_guid=True, is_deleted=False)
            }
            guide = next((by_cat[c] for c in chain if c in by_cat), None)
        return media_dict(guide) if guide else None

    def full_detail(self, pid: int) -> dict:
        p = self.products[pid]
        pr = self.pricing(pid)
        comments = ProductComment.objects.filter(product_id=pid, is_deleted=False, status=1).count()
        tags = tags_for(ProductTag, "product_id", [pid]).get(pid, [])
        ai = self.ai_profiles.get(pid)

        product_name = display_name(p.title)
        ai_title = ai.title if ai and ai.title else ""
        description = ai.description if ai and ai.description else none_if_blank(p.description)
        short_desc = ai.meta_description if ai and ai.meta_description else none_if_blank(p.short_desc)

        return {
            "id": p.id,
            "slug": p.slug,
            "longDescriptionHtml": none_if_blank(p.long_description_html),
            "shortDescriptionHtml": none_if_blank(p.short_description_html),
            "barcode": p.barcode,
            "categoryId": p.category_id,
            "parentCategoryId": p.category.parent_id if p.category else None,
            "brandId": MONG_BRAND["id"],
            "productName": product_name,
            "aiTitle": ai_title,
            "ProductName_En": none_if_blank(p.name_en),
            "mainImages": self.main_images(pid),
            "productSizeGuid": self.size_guide(pid),
            "product_Base_Price": pr.base,
            "product_base_reduction": pr.reduction,
            "productBaseVat": float(p.vat or 0),
            "reductionPercent": pr.reduction,
            "price": pr.base,
            "priceAfterReduction": pr.after,
            "reductionPrice": pr.reduction_price,
            "details": self.details(pid, pr, with_barcode=True),
            "description": description,
            "shortDesc": short_desc,
            "commentCount": comments,
            "promotionLabel": None,
            "productFeatures": None,
            "breadcrumbs": None,
            "tags": tags,
            # AI Profile additions
            "fab": ai.fab if ai else "",
            "summaryBullets": ai.summary_bullets if ai else [],
            "stylistNote": ai.stylist_note if ai else "",
            "aiTags": ai.tags if ai else [],
            "aiAttributes": ai.attributes if ai else {},
            "metaDescription": ai.meta_description if ai else "",
        }


# -----------------------------------------------------------------------------
# Listing index: one compact row per listable product, cached briefly
# -----------------------------------------------------------------------------
@dataclass
class ListingRow:
    id: int
    title: str
    category_id: int | None
    price_after: int
    reduction: float
    in_stock: bool
    color_ids: frozenset
    created: object
    sold: float          # recent sales, as the sales software counts them
    featured: float      # SelectedProduct.sorting_weight; inf when not selected
    buyer_score: float


def listing_rows() -> list[ListingRow]:
    return warm.get(LISTING_CACHE_KEY, LISTING_CACHE_TTL, _build_listing_rows)


def _build_listing_rows() -> list[ListingRow]:
    tree = category_tree()
    setting = SiteSetting.objects.filter(is_deleted=False).first()
    only_media = bool(setting and setting.only_has_media_products)

    products = on_sale(Product.objects.filter(is_deleted=False, is_active=True, category_id__in=tree.nodes.keys()))
    if only_media:
        products = products.filter(id__in=LebazaiImage.objects.values("product_id"))
    ids = list(products.values_list("id", flat=True))
    bundle = ProductBundle.load(ids)
    scores = dict(
        ProductComment.objects.filter(product_id__in=ids, is_deleted=False, status=1)
        .values("product_id").annotate(avg=Avg("score")).values_list("product_id", "avg")
    )
    featured: dict[int, float] = {}
    for pid, weight in SelectedProduct.objects.filter(is_deleted=False).values_list("product_id", "sorting_weight"):
        featured[pid] = min(float(weight), featured.get(pid, math.inf))
    rows = []
    for pid, p in bundle.products.items():
        pr = bundle.pricing(pid)
        if pr.after <= 0:
            continue
        if only_media and not bundle.has_images(pid):  # like the legacy site; also when every photo is hidden in the admin
            continue
        rows.append(ListingRow(
            id=pid, title=norm(p.title), category_id=p.category_id,
            price_after=pr.after, reduction=pr.reduction, in_stock=bundle.in_stock(pid),
            color_ids=frozenset(v.color_id for v in bundle.visible_variants(pid)),
            created=p.created, sold=p.sold, featured=featured.get(pid, math.inf),
            buyer_score=float(scores.get(pid) or 0),
        ))
    return rows


def _newest(r):
    return (-(r.created.timestamp() if r.created else 0), r.id)


# sortCriteriaId -> ascending sort key; ties fall back to newest like the legacy site.
# 1 (پربازدیدترین) is not offered until views are tracked; requests for it get newest.
SORT_KEYS = {
    2: _newest,                                   # جدیدترین (also the default)
    3: lambda r: (-r.sold, *_newest(r)),          # پرفروش ترین
    4: lambda r: (r.price_after, *_newest(r)),    # ارزان ترین
    5: lambda r: (-r.price_after, *_newest(r)),   # گران ترین
    6: lambda r: (-r.buyer_score, *_newest(r)),   # پیشنهاد خریداران (approved comment scores)
    7: lambda r: (r.featured, *_newest(r)),       # منتخب: محصولات منتخب ادمین به ترتیب وزن، بعد جدیدترین
    8: lambda r: (-r.reduction, *_newest(r)),     # بیشترین تخفیف
    9: lambda r: (r.reduction, *_newest(r)),      # کمترین تخفیف
}
SORT_CRITERIA = [
    {"id": 2, "sortKeyFa": "جدیدترین"},
    {"id": 3, "sortKeyFa": "پرفروش ترین"}, {"id": 4, "sortKeyFa": "ارزان ترین"},
    {"id": 5, "sortKeyFa": "گران ترین"}, {"id": 6, "sortKeyFa": "پیشنهاد خریداران"},
    {"id": 7, "sortKeyFa": "منتخب"}, {"id": 8, "sortKeyFa": "بیشترین تخفیف"},
    {"id": 9, "sortKeyFa": "کمترین تخفیف"},
]


def _safe_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def filter_rows(payload: dict) -> list[ListingRow]:
    payload = payload if isinstance(payload, dict) else {}
    rows = listing_rows()
    tree = category_tree()

    cat_ids = [_safe_int(c) for c in payload.get("filteredCategoryIds") or []]
    cat_ids = [c for c in cat_ids if c is not None]
    if cat_ids:
        allowed = set().union(*(tree.descendants(c) for c in cat_ids))
        rows = [r for r in rows if r.category_id in allowed]

    brand_id = _safe_int(payload.get("filteredBrandId"))
    if brand_id is not None and brand_id != MONG_BRAND["id"]:
        rows = []

    coll_ids = [_safe_int(c) for c in payload.get("filteredCollectionIds") or []]
    coll_ids = [c for c in coll_ids if c is not None]
    if coll_ids:
        links = ProductCollection.objects.filter(collection_id__in=coll_ids, is_deleted=False)
        pids = set(links.exclude(product_id=None).values_list("product_id", flat=True))
        # A collection that includes a brand includes every product (there is only Mong).
        if not links.exclude(brand_id=None).exists():
            rows = [r for r in rows if r.id in pids]

    from_price = _safe_int(payload.get("fromPrice"))
    if from_price is not None:
        rows = [r for r in rows if r.price_after >= from_price]

    to_price = _safe_int(payload.get("toPrice"))
    if to_price is not None:
        rows = [r for r in rows if r.price_after <= to_price]

    if payload.get("hasDiscount"):
        rows = [r for r in rows if r.reduction > 0]
    if payload.get("isInStock"):
        rows = [r for r in rows if r.in_stock]

    raw_feat = [_safe_int(f) for f in payload.get("filteredFeatureId") or []]
    feat_ids = {f for f in raw_feat if f is not None}
    feature_ids = expand_color_families(feat_ids)
    if feature_ids:
        rows = [r for r in rows if r.color_ids & feature_ids]

    if payload.get("search"):
        q = norm(payload["search"])
        rows = [r for r in rows if q in r.title]

    sort_id = _safe_int(payload.get("sortCriteriaId")) or 2
    return sorted(rows, key=SORT_KEYS.get(sort_id, _newest))


def page_of(rows: list, page_number, page_size) -> tuple[list, int]:
    size = max(1, _safe_int(page_size) or 20)
    number = max(1, _safe_int(page_number) or 1)
    total_pages = math.ceil(len(rows) / size) if rows else 0
    return rows[(number - 1) * size: number * size], total_pages


def render_list(ids: list[int]) -> list[dict]:
    bundle = ProductBundle.load(ids)
    return [bundle.list_item(pid) for pid in ids if pid in bundle.products]


def color_families(color_ids) -> list[dict]:
    """The color filter: one entry per color family (سفید covers استخواني, سفيد, ...), id = its first color."""
    families: dict[str, tuple[int, str]] = {}
    rows = ProductVariant.objects.filter(color_id__in=color_ids).order_by("color_priority", "color_id")
    for family, color_id, value in rows.values_list("color_family", "color_id", "color_value").distinct():
        families.setdefault(family, (color_id, value))
    return [
        {"id": color_id, "hasColor": True, "name": family, "value": value, "parentId": 0}
        for family, (color_id, value) in families.items()
    ]


def womens(name: str) -> str:
    """"مانتو" -> "مانتو زنانه": every Mong product is women's, and searches say so."""
    if name.strip() == "زنانه":  # the root category
        return "پوشاک زنانه"
    return name if "زنانه" in name else f"{name} زنانه"


def category_guide(cat: Category) -> dict | None:
    """
    The closed "درباره ..." box under a category's products: a few facts about
    what is on sale there now, written from the catalog so they stay true, and
    links to its subcategories. The admin's long description, when set, comes first.
    """
    tree = category_tree()
    inside = tree.descendants(cat.id)
    rows = [r for r in listing_rows() if r.category_id in inside]
    item = womens(display_name(cat.title))
    paragraphs = []
    if rows:
        prices = sorted(r.price_after for r in rows)
        low, high = prices[0] // 10, prices[-1] // 10
        price = f"با قیمت {low:,} تومان" if low == high else f"با قیمت از {low:,} تا {high:,} تومان"
        paragraphs.append(f"در حال حاضر {len(rows)} مدل {item} {price} در فروشگاه مانگ موجود است.")
        colors = [display_name(c["name"]) for c in color_families(set().union(*(r.color_ids for r in rows)))][:8]
        if len(colors) > 1:
            paragraphs.append(f"رنگ‌های موجود: {'، '.join(colors)}.")
        discounted = sum(1 for r in rows if r.reduction > 0)
        if discounted:
            paragraphs.append(f"{discounted} مدل از این دسته تخفیف دارد.")
    listed = {r.category_id for r in listing_rows()}
    links = [
        {"title": display_name(tree.nodes[k].title), "url": f"/products-category/{tree.nodes[k].slug}"}
        for k in tree.children.get(cat.id, [])
        if tree.descendants(k) & listed
    ]
    html = none_if_blank(cat.long_description_html)
    if not (paragraphs or links or html):
        return None
    return {"title": f"درباره {item}", "html": html, "paragraphs": paragraphs, "links": links}


def home_guide(branch_names: list[str]) -> dict | None:
    """
    The closed "درباره مانگ" box at the foot of the home page: what the shop
    sells now, with links to its biggest categories, and where its shops are.
    Written from the catalog and the branch list, so it stays true; the home
    page otherwise has almost no text of its own for a search engine to read.
    """
    tree = category_tree()
    rows = listing_rows()
    if not rows:
        return None
    per_category = defaultdict(int)
    for r in rows:
        per_category[r.category_id] += 1

    def count(cid: int) -> int:
        return sum(per_category[k] for k in tree.descendants(cid))

    # The categories a shopper picks from: those with products and no subcategory that has any.
    kinds = [
        cid for cid in tree.nodes
        if count(cid) and not any(count(k) for k in tree.children.get(cid, []))
    ]
    kinds.sort(key=lambda cid: (-count(cid), cid))
    kinds = kinds[:10]
    names = [display_name(tree.nodes[cid].title) for cid in kinds]

    paragraphs = [
        f"مانگ (Mong) فروشگاه اینترنتی پوشاک زنانه است. در حال حاضر {len(rows)} مدل "
        f"پوشاک زنانه در سایت مانگ موجود است، از جمله {'، '.join(names[:6])}."
    ]
    # Shops people can walk into: not the online sales desk or the head office.
    shops = [
        re.sub(r"^\s*شعبه\s+", "", display_name(b)).strip()
        for b in branch_names
        if not re.search(r"آنلاین|اینترنتی|دفتر", b)
    ]
    if shops:
        paragraphs.append(f"فروشگاه‌های حضوری مانگ: {'، '.join(shops)}.")
    links = [
        {"title": womens(display_name(tree.nodes[cid].title)), "url": f"/products-category/{tree.nodes[cid].slug}"}
        for cid in kinds
    ]
    links += [{"title": "شعب مانگ", "url": "/branches"}, {"title": "بلاگ مانگ", "url": "/blog"}]
    return {"title": "درباره مانگ", "html": None, "paragraphs": paragraphs, "links": links}


def expand_color_families(color_ids: set[int]) -> set[int]:
    """A filter on a family's id matches every color of that family."""
    if not color_ids:
        return color_ids
    colors = ProductVariant.objects.exclude(color_id=None)
    families = set(colors.filter(color_id__in=color_ids).values_list("color_family", flat=True))
    return color_ids | set(colors.filter(color_family__in=families).values_list("color_id", flat=True))


def brands_of(rows: list[ListingRow]) -> list[dict]:
    return [dict(MONG_BRAND)] if rows else []


def clear_caches():
    warm.drop(TREE_CACHE_KEY)
    warm.invalidate(LISTING_CACHE_KEY)
    warm.invalidate(ADMIN_ROWS_CACHE_KEY)


def on_sale(products):
    """Restrict a Product queryset to what the sales software's last read had on sale."""
    return products.filter(on_sale=True)
