"""
Read side of the storefront: builds the JSON objects the legacy API returned.

Sources:
- website.*  (imported from DadehfaOnlineShop): category tree, slugs, titles,
  descriptions, variants (color/size) and website media.
- samian.*   (synced from Samian ERP): price, stock per barcode, product images.

Rules:
- Samian is the reference: a website product is shown only when it is linked
  to a Samian product (ProductBundle.load drops the others). Price and stock
  come only from Samian.
- Images: Samian gallery first, website media as fallback; both served as
  pre-built WebP from /img/ (apps/website/images.py) once build_images ran.
- Stock is the sum over the branches marked sells_online (website.Branch), minus
  SiteSetting.min_qty kept back per variant.
- Only Mong products exist here (Samian brands مانگ and توليد, synced with
  SAMIAN_BRAND_IDS); customers always see the one brand MONG_BRAND. Listing
  shows products in an online category, and (when SiteSetting.only_has_media_products is on) only products
  that have images.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.db.models import Avg, Q, Sum
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
)
from apps.website import images as site_images
from apps.website.models import (
    Category,
    CategoryTag,
    MediaAttachment,
    Product,
    ProductCollection,
    ProductComment,
    ProductSamianLink,
    ProductTag,
    HiddenImage,
    SelectedProduct,
    SiteSetting,
    online_warehouse_ids,
)

from . import warm

# مانگ and توليد are one brand for customers: every product is shown as Mong.
MONG_BRAND = {"id": 15, "title": "مانگ"}

LISTING_CACHE_KEY = "storefront:listing:v11"
LISTING_CACHE_TTL = 300  # Samian syncs every 15 minutes; a stale listing is rebuilt in the background
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


def round_price(rial) -> int:
    """Discounted prices are rounded to 1,000 toman (10,000 rial) like the legacy site."""
    return int((float(rial) + 5000) // 10000 * 10000)


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
    """Home, then the category path without its root: Samian level 1 (زنانه) is the same for every Mong product."""
    items = [{"position": 1, "name": "خانه", "url": "/"}]
    if cat_id:
        chain = category_tree().ancestors(cat_id)
        if len(chain) > 1 and chain[0].parent_id is None:
            chain = chain[1:]
        for i, c in enumerate(chain, start=2):
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


@dataclass(frozen=True)
class Option:
    """A color or a size as the site shows it."""

    id: int
    name: str
    value: str
    display_priority: int


@dataclass(frozen=True)
class Variant:
    """A sellable barcode of a Samian product, with its Samian color and size."""

    id: int        # Samian barcodemain_id (productVariantId on the site)
    pk: int        # SamianBarcode pk
    barcode: str
    color: Option | None
    size: Option | None

    @property
    def color_id(self) -> int | None:
        return self.color.id if self.color else None

    @property
    def size_id(self) -> int | None:
        return self.size.id if self.size else None


def _color_option(color_id: int | None, fallback_name: str, colors: dict[int, SamianColor]) -> Option | None:
    if not color_id:
        return None
    c = colors.get(color_id)
    if c is None:
        return Option(color_id, fallback_name, "", 0)
    return Option(c.samian_id, c.name, c.hex_code, c.display_priority)


@dataclass
class ProductBundle:
    """Everything needed to render a set of products, loaded in a few queries."""

    products: dict[int, Product]
    variants: dict[int, list[Variant]] = field(default_factory=dict)
    samian: dict[int, SamianProduct] = field(default_factory=dict)  # website product id -> SamianProduct
    list_price: dict[int, int] = field(default_factory=dict)  # samian product pk -> final price
    stock: dict[int, float] = field(default_factory=dict)  # SamianBarcode pk -> qty in the online branches
    samian_images: dict[int, dict[int, list[dict]]] = field(default_factory=dict)  # product id -> colorinfo id -> images
    only_media: bool = False  # SiteSetting.only_has_media_products: hide colors that have no images
    min_qty: float = 0.0  # SiteSetting.min_qty: safety stock per variant that is never offered online

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

        links = dict(ProductSamianLink.objects.filter(product_id__in=ids).values_list("product_id", "samian_product_id"))
        sps = {sp.samian_id: sp for sp in SamianProduct.objects.filter(samian_id__in=links.values())}
        b.samian = {pid: sps[sid] for pid, sid in links.items() if sid in sps}
        # Not in Samian -> not on the site (the Dadehfa copy is only kept for comparison).
        b.products = {pid: p for pid, p in products.items() if pid in b.samian}
        ids = list(b.products)
        if not ids:
            return b

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

        # Variants: the product's active Samian barcodes, color and size as Samian has them.
        pid_by_sp = {sp.pk: pid for pid, sp in b.samian.items()}
        colors = {c.samian_id: c for c in SamianColor.objects.all()}
        sizes = {sz.name: sz for sz in SamianSize.objects.all()}
        barcodes = (
            SamianBarcode.objects.filter(samian_product_id__in=pid_by_sp, is_active=True)
            .only("samian_id", "barcode", "size", "color", "colorinfo_id", "samian_product_id").order_by("samian_id")
        )
        for bc in barcodes:
            sz = sizes.get(bc.size)
            b.variants.setdefault(pid_by_sp[bc.samian_product_id], []).append(Variant(
                id=bc.samian_id, pk=bc.pk, barcode=bc.barcode,
                color=_color_option(bc.colorinfo_id, bc.color, colors),
                size=Option(sz.pk, sz.name, sz.name, sz.display_priority) if sz else None,
            ))
        barcode_pks = [v.pk for vs in b.variants.values() for v in vs]
        b.stock = {
            r["samian_barcode_id"]: float(r["total"] or 0)
            for r in SamianInventory.objects.filter(samian_barcode_id__in=barcode_pks, warehouse_id__in=online_warehouse_ids())
            .values("samian_barcode_id").annotate(total=Sum("qty"))
        }

        if with_images:
            b._load_images(ids, include_hidden)
        return b

    def _load_images(self, ids, include_hidden: bool = False):
        pmid_to_pid = {sp.samian_id: pid for pid, sp in self.samian.items()}
        hidden = set(HiddenImage.objects.values_list("key", flat=True))
        colors = (
            SamianProductColor.objects.filter(productmain_id__in=pmid_to_pid.keys(), has_gallery=True)
            .only("samian_id", "productmain_id", "colorinfo_id", "colorsgalery").order_by("samian_id")
        )
        for color in colors:
            pid = pmid_to_pid[color.productmain_id]
            imgs = []
            for idx, item in enumerate(color.colorsgalery or []):
                fp = item.get("filePath", "") if isinstance(item, dict) else ""
                if not fp or Path(fp).suffix.lower() not in site_images.IMAGE_EXT:
                    continue
                key = site_images.samian_key(color.productmain_id, fp)
                if key in hidden and not include_hidden:
                    continue
                # Built nightly by build_images; until then the original through the proxy.
                url = site_images.public_url(key) if site_images.is_built(key) else f"/api/samian/media/{color.samian_id}/{idx}/"
                imgs.append({
                    "id": color.samian_id * 100 + idx,
                    "mediaUrl": absolute_url(url),
                    "isVideo": False,
                    "alternative": "",
                    "tooltipTitle": "",
                    **({"key": key, "isHidden": key in hidden} if include_hidden else {}),
                })
            if imgs:
                self.samian_images.setdefault(pid, {}).setdefault(color.colorinfo_id, []).extend(imgs)

    # -- per product -------------------------------------------------------
    def pricing(self, pid: int) -> Pricing:
        sp = self.samian.get(pid)
        if not sp or not sp.sale_price:
            return Pricing(0.0, 0.0, 0)
        base = sp.sale_price
        final = self.list_price.get(sp.pk)
        if final and final < base:
            return Pricing(float(base), round((base - final) * 100 / base, 3), round_price(final))
        return Pricing(float(base), 0.0, int(base))

    def variant_stock(self, pid: int, v: Variant) -> float:
        return max(0.0, self.stock.get(v.pk, 0.0) - self.min_qty)

    def has_images(self, pid: int) -> bool:
        return bool(self.samian_images.get(pid))

    def main_images(self, pid: int) -> list[dict]:
        return [img for imgs in self.samian_images.get(pid, {}).values() for img in imgs]

    def color_images(self, pid: int, v: Variant) -> list[dict]:
        """The Samian gallery of the variant's color (product/colors, same colorinfo id as the barcode)."""
        return self.samian_images.get(pid, {}).get(v.color_id) or []

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
                    "images": None, "price": 0.0, "reduction": 0.0, "discount": 0, "mojodi": qty,
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
        return {
            "id": p.id,
            "slug": p.slug,
            "categoryId": p.category_id,
            "parentCategoryId": p.category.parent_id if p.category else None,
            "brandId": MONG_BRAND["id"],
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

    def size_guide(self, pid: int) -> dict | None:
        """The size chart: Samian's (onlinestoresizehelp), else one set in the admin for the product, else for its category."""
        sp = self.samian.get(pid)
        if sp and sp.size_help_path:
            key = site_images.samian_key(sp.samian_id, sp.size_help_path)
            if site_images.is_built(key):
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
        sp = self.samian.get(pid)
        return {
            "id": p.id,
            "slug": p.slug,
            "longDescriptionHtml": none_if_blank(p.long_description_html),
            "shortDescriptionHtml": none_if_blank(p.short_description_html),
            "barcode": p.barcode,
            "categoryId": p.category_id,
            "parentCategoryId": p.category.parent_id if p.category else None,
            "brandId": MONG_BRAND["id"],
            "productName": p.title,
            "ProductName_En": none_if_blank(sp.name_en if sp else ""),
            "mainImages": self.main_images(pid),
            "productSizeGuid": self.size_guide(pid),
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
    price_after: int
    reduction: float
    in_stock: bool
    color_ids: frozenset
    created: object
    sold: float          # Mong units sold in the last BEST_SELLER_DAYS, every branch, returns subtracted
    featured: float      # SelectedProduct.sorting_weight; inf when not selected
    buyer_score: float


def listing_rows() -> list[ListingRow]:
    return warm.get(LISTING_CACHE_KEY, LISTING_CACHE_TTL, _build_listing_rows)


def _build_listing_rows() -> list[ListingRow]:
    tree = category_tree()
    setting = SiteSetting.objects.filter(is_deleted=False).first()
    only_media = bool(setting and setting.only_has_media_products)

    ids = list(
        Product.objects.filter(
            is_deleted=False, is_active=True, category_id__in=tree.nodes.keys()
        ).values_list("id", flat=True)
    )
    if only_media:
        # Like the legacy site: only products that have a gallery per color (in Samian).
        with_media = set(
            ProductSamianLink.objects.filter(
                product_id__in=ids,
                samian_product_id__in=SamianProductColor.objects.filter(has_gallery=True).values("productmain_id"),
            ).values_list("product_id", flat=True)
        )
        ids = [i for i in ids if i in with_media]

    bundle = ProductBundle.load(ids)
    scores = dict(
        ProductComment.objects.filter(product_id__in=ids, is_deleted=False, status=1)
        .values("product_id").annotate(avg=Avg("score")).values_list("product_id", "avg")
    )
    sold = sold_by_samian_product()
    featured: dict[int, float] = {}
    for pid, weight in SelectedProduct.objects.filter(is_deleted=False).values_list("product_id", "sorting_weight"):
        featured[pid] = min(float(weight), featured.get(pid, math.inf))
    rows = []
    for pid, p in bundle.products.items():
        pr = bundle.pricing(pid)
        if pr.after <= 0:
            continue
        if only_media and not bundle.has_images(pid):  # e.g. every photo hidden in the admin
            continue
        rows.append(ListingRow(
            id=pid, title=norm(p.title), category_id=p.category_id,
            price_after=pr.after, reduction=pr.reduction, in_stock=bundle.in_stock(pid),
            color_ids=frozenset(v.color_id for v in bundle.visible_variants(pid)),
            created=p.created, sold=sold.get(bundle.samian[pid].pk, 0.0), featured=featured.get(pid, math.inf),
            buyer_score=float(scores.get(pid) or 0),
        ))
    return rows


def _newest(r):
    return (-(r.created.timestamp() if r.created else 0), r.id)


def sold_by_samian_product() -> dict[int, float]:
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
    """The color filter: one entry per Samian color family (سفید covers استخواني, سفيد, ...), id = its first color."""
    families: dict[str, SamianColor] = {}
    for c in SamianColor.objects.filter(samian_id__in=color_ids).order_by("display_priority", "samian_id"):
        families.setdefault(c.family, c)
    return [
        {"id": c.samian_id, "hasColor": True, "name": family, "value": c.hex_code, "parentId": 0}
        for family, c in families.items()
    ]


def expand_color_families(color_ids: set[int]) -> set[int]:
    """A filter on a family's id matches every color of that family."""
    if not color_ids:
        return color_ids
    picked = SamianColor.objects.filter(samian_id__in=color_ids)
    families = {c.family for c in picked}
    return color_ids | {c.samian_id for c in SamianColor.objects.all() if c.family in families}


def brands_of(rows: list[ListingRow]) -> list[dict]:
    return [dict(MONG_BRAND)] if rows else []


def clear_caches():
    cache.delete(TREE_CACHE_KEY)
    warm.invalidate(LISTING_CACHE_KEY)


def in_samian(products):
    """Restrict a Product queryset to products linked to an existing Samian product."""
    return products.filter(
        id__in=ProductSamianLink.objects.filter(
            samian_product_id__in=SamianProduct.objects.values("samian_id")
        ).values("product_id")
    )
