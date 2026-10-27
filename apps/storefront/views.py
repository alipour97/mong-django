"""
Storefront API v1 (samian.mong.ir/api/v1/...), a drop-in for the legacy
api.mong.ir so the unchanged Next.js frontend works against it.

Response shapes are checked against real responses saved in
contract_fixtures/. Data access and product rendering live in catalog.py.
"""
from __future__ import annotations

import json
import logging
from urllib.parse import unquote

from django.db.models import Avg
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.website.models import (
    Banner,
    Branch,
    Category,
    CategoryTag,
    City,
    Collection,
    CompanyInfo,
    CustomTheme,
    CustomThemePage,
    FeatureValue,
    FileMedia,
    MediaAttachment,
    Outfit,
    PrimaryConfig,
    Product,
    ProductComment,
    ProductTag,
    Province,
    SelectedProduct,
    SiteSetting,
    Tag,
    Theme,
    ThemePage,
)

from apps.website import images as site_images

from . import catalog
from .envelope import MSG_FETCHED, MSG_FETCHED_ONE, MSG_NOT_FOUND, MSG_NOT_FOUND_REQUIRED, MSG_SENT, iso, jalali, not_found, ok, server_error

logger = logging.getLogger(__name__)


class PublicView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []


def _ids(request) -> list[int]:
    return [int(i) for i in (request.data.get("items") or []) if str(i).lstrip("-").isdigit()]


# -----------------------------------------------------------------------------
# Configs, company, theme
# -----------------------------------------------------------------------------
class PrimaryConfigGetConfigView(PublicView):
    """
    GET  PrimaryConfig/GetConfig/<key> -> {"id", "key", "value": <parsed JSON>}
    POST PrimaryConfig/Get {"key"}     -> [{"id", "key", "value": "<raw JSON string>"}]
    """

    def get(self, request, key: str = ""):
        pc = PrimaryConfig.objects.filter(key=key, is_deleted=False).first()
        if not pc:
            return server_error()
        raw = _config_value(pc)
        try:
            value = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            value = raw
        return ok({"id": pc.id, "key": pc.key, "value": value})

    def post(self, request, key: str = ""):
        key = key or request.data.get("key", "")
        rows = [{"id": pc.id, "key": pc.key, "value": _config_value(pc)} for pc in PrimaryConfig.objects.filter(key=key, is_deleted=False)]
        return ok(rows)


def _config_value(pc: PrimaryConfig) -> str:
    """The stored JSON with media URLs rewritten; the branches list comes from the Branch table."""
    raw = pc.value
    if pc.key == "businessDepartments" and raw:
        branches = Branch.objects.filter(show_on_site=True)
        if branches.exists():
            value = json.loads(raw)
            value["departmentList"] = [b.as_department() for b in branches]
            raw = json.dumps(value, ensure_ascii=False)
    return site_images.rewrite_media_in_text(raw)


def _company_media(record_id: int) -> dict | None:
    att = MediaAttachment.objects.filter(
        table=MediaAttachment.Table.COMPANY_INFOS, record_id=record_id, is_deleted=False
    ).order_by("-id").first()
    if not att:
        return None
    file_media = FileMedia.objects.filter(url=att.media_url, is_deleted=False).values_list("id", flat=True).first()
    return {
        "url": site_images.site_media_url(att.media_url), "mediaId": att.id, "fileMediaId": file_media,
        "alternative": att.alternative, "tooltipTitle": att.tooltip_title,
    }


class CompanyInfoView(PublicView):
    """GET CompanyInfo/GetCompanyInfo. Logo = company media record 1, favicon = record 2."""

    def get(self, request):
        info = CompanyInfo.objects.filter(is_deleted=False).first()
        setting = SiteSetting.objects.filter(is_deleted=False).first()
        phones = [p for p in (info.phone_numbers if info else "").split(",") if p.strip()]
        keywords = [k for k in (info.keywords if info else "").split(",") if k.strip()]
        return ok({
            "name": info.name if info else "",
            "description": info.description if info else "",
            "address": info.address if info else "",
            "phoneNumbers": phones,
            "postalCode": info.postal_code if info else "",
            "keywords": keywords,
            "webSiteLogo": _company_media(1),
            "favicon": _company_media(2),
            "minQty": float(setting.min_qty) if setting else 1.0,
        })


def _theme_colors(t) -> dict:
    return {
        "white": t.white_color, "whiteHover": t.white_hover_color, "primary1": t.primary1_color,
        "primary2": t.primary2_color, "secondary": t.secondary_color, "border": t.border_color,
        "cta": t.cta_color, "ctaHover": t.cta_hover_color, "ctaDisabled": t.cta_disabled_color,
        "focus": t.focus_color, "highlight": t.highlight_color or None, "alert": t.alert_color,
    }


class SettingGetDefaultThemeView(PublicView):
    """GET Setting/GetDefaultTheme -> pages per type + color palette of the active theme."""

    def get(self, request):
        setting = SiteSetting.objects.filter(is_deleted=False).first()
        if not setting or not setting.default_theme_id:
            return not_found()
        if setting.is_custom_theme:
            theme = CustomTheme.objects.filter(id=setting.default_theme_id).first()
            links = CustomThemePage.objects.filter(custom_theme_id=setting.default_theme_id, is_deleted=False)
        else:
            theme = Theme.objects.filter(id=setting.default_theme_id).first()
            links = ThemePage.objects.filter(theme_id=setting.default_theme_id, is_deleted=False)
        if not theme:
            return not_found()
        pages = {link.page.type: {"id": link.page.id, "key": link.page.key} for link in links.select_related("page")}
        return ok({"pages": pages, "color": _theme_colors(theme)})


class SortCriteriaGetAllView(PublicView):
    def get(self, request):
        return ok(catalog.SORT_CRITERIA, total_pages=1)


# -----------------------------------------------------------------------------
# Categories
# -----------------------------------------------------------------------------
class CategoryGetAllView(PublicView):
    def get(self, request):
        return ok({"categories": catalog.category_tree_dicts(), "banners": [], "sliders": []})


class CategoryGetByIdView(PublicView):
    def get(self, request, category_id: int):
        cat = Category.objects.filter(id=category_id, is_deleted=False).first()
        if not cat:
            return not_found()
        media = catalog.attachments(MediaAttachment.Table.CATEGORIES, [cat.id]).get(cat.id)
        tags = catalog.tags_for(CategoryTag, "category_id", [cat.id]).get(cat.id)
        data = catalog.category_dict(cat, media=media, tags=tags)
        data.update({"parentMapId": cat.parent_map_id or None, "created": iso(cat.created)})
        return ok(data)


class CategoryGetBreadCrumbsView(PublicView):
    def get(self, request, category_id: int):
        return ok(catalog.breadcrumb_items(category_id), message=MSG_SENT)


class CategoryGetSliderBannerSummariesView(PublicView):
    """POST Category/GetSliderBannerSummaries {"items": [banner ids]} -> active banners in that order."""

    def post(self, request):
        ids = _ids(request)
        found = Banner.objects.filter(id__in=ids, is_deleted=False, is_active=True).in_bulk()
        banners = [
            {"id": b.id, "mediaUrl": site_images.site_media_url(b.media_url), "link": b.link, "displayPriority": b.display_priority, "isBanner": b.is_banner}
            for b in (found[i] for i in ids if i in found)
        ]
        return ok({"banners": banners, "sliders": []}, message=MSG_FETCHED_ONE)


class CategoryGetCategorySummariesView(PublicView):
    def post(self, request):
        ids = _ids(request)
        cats = Category.objects.filter(id__in=ids, is_deleted=False).in_bulk()
        media = catalog.attachments(MediaAttachment.Table.CATEGORIES, cats.keys())
        data = [{"id": c.id, "title": c.title, "slug": c.slug, "medias": media.get(c.id, [])} for c in (cats[i] for i in ids if i in cats)]
        return ok(data)


# -----------------------------------------------------------------------------
# Collections and outfits
# -----------------------------------------------------------------------------
def _collection_dict(c: Collection, media: list, media_key: str) -> dict:
    return {
        "id": c.id, "title": c.title, "inMainPage": c.in_main_page, "reduction": float(c.reduction),
        "beginningDate": jalali(c.beginning_date), "endDate": jalali(c.end_date),
        "displayPriority": c.display_priority, media_key: media,
    }


def _current_collections():
    now = timezone.now()
    return (
        Collection.objects.filter(is_deleted=False, is_active=True)
        .exclude(end_date__lt=now)
        .exclude(beginning_date__gt=now)
        .order_by("display_priority", "id")
    )


class CollectionGetCollectionSummariesView(PublicView):
    """POST Collection/GetCollectionSummaries {"items": [...]} -> running collections (all when items is empty)."""

    def post(self, request):
        ids = _ids(request)
        qs = _current_collections()
        if ids:
            qs = qs.filter(id__in=ids)
        cols = list(qs)
        media = catalog.attachments(MediaAttachment.Table.COLLECTIONS, [c.id for c in cols])
        return ok([_collection_dict(c, media.get(c.id, []), "medias") for c in cols])


class CollectionGetAllView(PublicView):
    def get(self, request):
        cols = list(Collection.objects.filter(is_deleted=False).order_by("display_priority", "id"))
        media = catalog.attachments(MediaAttachment.Table.COLLECTIONS, [c.id for c in cols])
        return ok([_collection_dict(c, media.get(c.id, []), "mediaAttachments") for c in cols])


class CollectionGetByIdView(PublicView):
    def get(self, request, collection_id: int):
        c = Collection.objects.filter(id=collection_id, is_deleted=False).first()
        if not c:
            return not_found()
        media = catalog.attachments(MediaAttachment.Table.COLLECTIONS, [c.id]).get(c.id, [])
        cats = Category.objects.filter(collection_links__collection=c, collection_links__is_deleted=False, is_deleted=False)
        data = _collection_dict(c, media, "mediaAttachments")
        data.update({
            "categoryCollectionFilters": [],
            "categoryFilters": [
                {"id": cat.id, "title": cat.title, "parentId": cat.parent_id, "isOnlineActive": cat.is_online_active}
                for cat in cats.order_by("id")
            ],
            "categoryCount": cats.count(),
            "hasProducts": c.product_links.filter(is_deleted=False).exists(),
        })
        return ok(data)


def _current_outfits():
    now = timezone.now()
    return Outfit.objects.filter(is_deleted=False, is_active=True).exclude(expiration_date__lt=now).exclude(start_date__gt=now)


def _outfit_dict(o: Outfit, media: list) -> dict:
    return {
        "id": o.id, "title": o.title, "medias": media, "description": o.description, "categoryId": o.category_id,
        "labelTitle": o.label_title, "startDate": jalali(o.start_date), "expirationDate": jalali(o.expiration_date),
    }


class OutfitGetOutfitSummariesView(PublicView):
    def post(self, request):
        ids = _ids(request)
        qs = _current_outfits()
        if ids:
            qs = qs.filter(id__in=ids)
        outfits = list(qs.order_by("id"))
        media = catalog.attachments(MediaAttachment.Table.OUTFITS, [o.id for o in outfits])
        data = [_outfit_dict(o, media.get(o.id, [])) for o in outfits]
        return ok(data, message=MSG_FETCHED if data else MSG_NOT_FOUND)


class OutfitGetAllView(PublicView):
    def get(self, request):
        outfits = list(_current_outfits().order_by("id"))
        if not outfits:
            return not_found([], http_status=404, message=MSG_NOT_FOUND_REQUIRED)
        media = catalog.attachments(MediaAttachment.Table.OUTFITS, [o.id for o in outfits])
        return ok([_outfit_dict(o, media.get(o.id, [])) for o in outfits])


class OutfitGetByIdView(PublicView):
    EMPTY = {"id": 0, "title": None, "medias": None, "description": None, "categoryId": None,
             "labelTitle": None, "startDate": None, "expirationDate": None}

    def get(self, request, outfit_id: int):
        o = _current_outfits().filter(id=outfit_id).first()
        if not o:
            return not_found(self.EMPTY, http_status=404, message=MSG_NOT_FOUND_REQUIRED)
        return ok(_outfit_dict(o, catalog.attachments(MediaAttachment.Table.OUTFITS, [o.id]).get(o.id, [])))


class OutfitGetProductsByIdView(PublicView):
    def get(self, request, outfit_id: int):
        o = _current_outfits().filter(id=outfit_id).first()
        if not o:
            return not_found([])
        ids = list(o.product_links.filter(is_deleted=False).values_list("product_id", flat=True))
        return ok(catalog.render_list(ids))


# -----------------------------------------------------------------------------
# Products
# -----------------------------------------------------------------------------
class ProductGetAllView(PublicView):
    """POST Product/GetAll with IProductFilterPayload."""

    def post(self, request):
        rows = catalog.filter_rows(request.data)
        page, total_pages = catalog.page_of(rows, request.data.get("pageNumber"), request.data.get("pageSize"))
        return ok(catalog.render_list([r.id for r in page]), total_pages=total_pages)


class ProductSearchView(PublicView):
    """POST Product/Search {"query", "size"}."""

    def post(self, request):
        rows = catalog.filter_rows({"search": request.data.get("query", ""), "sortCriteriaId": 2})
        page, total_pages = catalog.page_of(rows, 1, request.data.get("size") or 10)
        return ok(catalog.render_list([r.id for r in page]), total_pages=total_pages)


class ProductGetSelectedProductsView(PublicView):
    def get(self, request):
        selections = list(SelectedProduct.objects.filter(is_deleted=False).order_by("sorting_weight", "id"))
        bundle = catalog.ProductBundle.load([s.product_id for s in selections])
        data = []
        for s in selections:
            if s.product_id not in bundle.products:
                continue
            item = bundle.list_item(s.product_id)
            item.update({"selectedProductId": s.id, "sortingWeight": float(s.sorting_weight)})
            data.append(item)
        return ok(data)


class ProductGetByIdView(PublicView):
    EMPTY = {
        "id": 0, "slug": None, "longDescriptionHtml": None, "shortDescriptionHtml": None, "barcode": "",
        "categoryId": 0, "parentCategoryId": None, "brandId": None, "productName": None, "ProductName_En": None,
        "mainImages": None, "productSizeGuid": None, "product_Base_Price": 0, "product_base_reduction": 0,
        "productBaseVat": 0, "reductionPercent": 0, "price": 0, "priceAfterReduction": 0, "reductionPrice": 0,
        "details": None, "description": None, "shortDesc": None, "commentCount": 0, "promotionLabel": None,
        "productFeatures": None, "breadcrumbs": None, "tags": None,
    }

    def get(self, request, product_id: int):
        bundle = catalog.ProductBundle.load([product_id])
        p = bundle.products.get(product_id)
        if not p or p.is_deleted:
            return not_found(self.EMPTY)
        return ok(bundle.full_detail(product_id))


class ProductSuggestView(PublicView):
    """POST Product/SuggestProduct {"categoryId", "productId"} -> other listed products of that category."""

    LIMIT = 12

    def post(self, request):
        cat_id = request.data.get("categoryId")
        product_id = request.data.get("productId")
        if not cat_id:
            return ok([])
        rows = [r for r in catalog.filter_rows({"filteredCategoryIds": [cat_id], "sortCriteriaId": 2}) if r.id != product_id]
        return ok(catalog.render_list([r.id for r in rows[: self.LIMIT]]))


class ProductGetFilterByCategoryView(PublicView):
    """GET Product/GetFilterByCategoryId?id=<category> -> price range, colors, brands, tags."""

    def get(self, request):
        cat_id = request.query_params.get("id")
        rows = catalog.filter_rows({"filteredCategoryIds": [cat_id]} if cat_id else {})
        if not rows:
            return ok({"fromPrice": 0, "toPrice": 0, "filteredValues": [], "brands": [], "tags": []})
        color_ids = set().union(*(r.color_ids for r in rows))
        colors = FeatureValue.objects.filter(id__in=color_ids, is_deleted=False).order_by("id")
        tag_ids = ProductTag.objects.filter(product_id__in=[r.id for r in rows], is_deleted=False).values("tag_id")

        return ok({
            "fromPrice": min(r.price_after for r in rows),
            "toPrice": max(r.price_after for r in rows),
            "filteredValues": [{"id": c.id, "hasColor": True, "name": c.name, "value": c.value, "parentId": 0} for c in colors],
            "brands": catalog.brands_of(rows),
            "tags": [
                {"title": t.title, "parentId": t.parent_id, "parent": None, "tags": None, "id": t.id}
                for t in Tag.objects.filter(id__in=tag_ids, is_deleted=False).order_by("-id")
            ],
        })


class CommentGetByProductIdView(PublicView):
    def get(self, request, product_id: int):
        comments = ProductComment.objects.filter(product_id=product_id, is_deleted=False, is_active=True).order_by("-id")
        data = [
            {
                "id": c.id, "lastModifiedBy": None, "comment": c.comment, "score": float(c.score),
                "isAdminComment": c.is_admin_comment, "parentId": c.parent_id, "commenterId": c.commenter_id,
                "isBuyer": c.is_buyer, "commenterFullName": "", "productId": c.product_id, "isActive": c.is_active,
                "isAnonymous": c.is_anonymous, "parent": None, "productComments": [], "productCommentLikes": [],
                "title": c.title, "commentMedias": [], "created": iso(c.created),
            }
            for c in comments
        ]
        avg = comments.aggregate(a=Avg("score"))["a"]
        return ok({"productComments": data, "averageScore": float(avg) if avg is not None else None}, message=MSG_FETCHED_ONE)


# -----------------------------------------------------------------------------
# Provinces / cities
# -----------------------------------------------------------------------------
class ProvinceGetAllView(PublicView):
    def get(self, request):
        return ok([
            {"id": p.id, "name": p.name, "countryId": p.country_id, "latitude": p.latitude, "longitude": p.longitude,
             "countryDto": None, "cityDtOs": None}
            for p in Province.objects.filter(is_deleted=False).order_by("id")
        ])


class CityGetAllView(PublicView):
    def get(self, request, province_id: int):
        return ok([
            {"id": c.id, "name": c.name, "provinceId": c.province_id, "latitude": c.latitude, "longitude": c.longitude,
             "provinceDto": None}
            for c in City.objects.filter(province_id=province_id, is_deleted=False).order_by("id")
        ])


# -----------------------------------------------------------------------------
# SearchEngine (served from the admin API host in the legacy system).
# These return raw values / schema.org JSON-LD, not the envelope.
# -----------------------------------------------------------------------------
def _slug(slug: str) -> str:
    return unquote(slug).strip()


def _product_by_slug(slug: str) -> Product | None:
    return Product.objects.filter(slug=_slug(slug), is_deleted=False).select_related("category", "brand").first()


def _toman(rial: int) -> str:
    return f"{int(rial) // 10:,}"


class SearchEngineIndexView(PublicView):
    def get(self, request, entity_type: str, slug: str):
        if entity_type == "product":
            p = _product_by_slug(slug)
            return Response(p.id if p else 0)
        if entity_type == "category":
            c = Category.objects.filter(slug=_slug(slug), is_deleted=False).first()
            return Response(c.id if c else 0)
        return Response(0)


class SearchEngineMetaView(PublicView):
    def get(self, request, entity_type: str, slug: str):
        if entity_type == "product":
            return self._product(slug)
        if entity_type == "category":
            return self._category(slug)
        return Response(None, status=404)

    def _product(self, slug):
        p = _product_by_slug(slug)
        if not p:
            return Response(None, status=404)
        bundle = catalog.ProductBundle.load([p.id])
        pr = bundle.pricing(p.id)
        images = bundle.main_images(p.id)
        category = p.category.title if p.category else ""
        parts = [category, p.title, p.short_desc, f"قیمت {_toman(pr.after)} تومان"]
        reviews = ProductComment.objects.filter(product=p, is_deleted=False, is_active=True).count()
        url = f"/products-item/{p.slug}"
        return Response({
            "context": "https://schema.org/",
            "type": "Product",
            "name": p.title,
            "image": [i["mediaUrl"] for i in images if not i["isVideo"]],
            "video": [i["mediaUrl"] for i in images if i["isVideo"]],
            "description": " . ".join(x for x in parts if x),
            "canonical": url,
            "brand": {"type": "Brand", "name": p.brand.title if p.brand else ""},
            "sku": p.barcode,
            "offers": {
                "type": "Offer",
                "url": url,
                "priceCurrency": "IRR",
                "price": f"{pr.after:,}",
                "priceValidUntil": timezone.localdate().isoformat(),
                "availability": "https://schema.org/InStock" if bundle.in_stock(p.id) else "https://schema.org/OutOfStock",
                "itemCondition": "https://schema.org/NewCondition",
            },
            "aggregateRating": {
                "type": "AggregateRating",
                "ratingValue": f"{float(p.overall_score_average or 0):.2f}",
                "reviewCount": str(reviews),
            },
            "category": category,
        })

    def _category(self, slug):
        cat = Category.objects.filter(slug=_slug(slug), is_deleted=False).first()
        if not cat:
            return Response(None, status=404)
        everything = list(Category.objects.filter(is_deleted=False).only("id", "parent_id", "title", "slug", "is_online_active"))
        kids: dict = {}
        for c in everything:
            kids.setdefault(c.parent_id, []).append(c)
        below, stack = [], [cat.id]
        while stack:
            for c in kids.get(stack.pop(), []):
                below.append(c)
                stack.append(c.id)
        online_parents = {c.parent_id for c in below if c.is_online_active}
        leaves = sorted((c for c in below if c.is_online_active and c.id not in online_parents), key=lambda c: c.id)
        return Response({
            "context": "https://schema.org/",
            "type": "ItemList",
            "name": cat.title,
            "description": " . ".join([cat.title] + [c.title for c in leaves]),
            "url": f"/products-category/{cat.slug}",
            "numberOfItems": len(leaves),
            "itemListOrder": "https://schema.org/ItemListOrderAscending",
            "itemListElement": [
                {"type": "ListItem", "position": i, "name": c.title, "url": f"/products-category/{c.slug}"}
                for i, c in enumerate(leaves, start=1)
            ],
        })


class SearchEngineBreadcrumbsView(PublicView):
    def get(self, request, entity_type: str, slug: str):
        if entity_type == "product":
            p = _product_by_slug(slug)
            if not p:
                return Response(None, status=404)
            items = catalog.breadcrumb_items(p.category_id)
            items.append({"position": len(items) + 1, "name": p.title, "url": f"/products-item/{p.slug}"})
        elif entity_type == "category":
            c = Category.objects.filter(slug=_slug(slug), is_deleted=False).first()
            if not c:
                return Response(None, status=404)
            items = catalog.breadcrumb_items(c.id)
        else:
            return Response(None, status=404)
        return Response({
            "context": "https://schema.org/",
            "type": "BreadcrumbList",
            "itemListElement": [{"type": "ListItem", **i} for i in items],
        })


class SearchEngineSiteMapsView(PublicView):
    def get(self, request):
        now = iso(timezone.now())
        rows = catalog.listing_rows()
        listed = Product.objects.filter(id__in=[r.id for r in rows]).values_list("slug", "last_modified", "created")
        tree = catalog.category_tree()

        def item(loc, modified):
            return {"urlLocation": loc, "lastModified": iso(modified) or now, "changeFrequency": "daily", "priority": 0.8}

        entity_type = request.query_params.get("entityType")
        data = {
            "blog": {"entityType": "blog", "lastCacheTime": now, "items": []},
            "product": {"entityType": "product", "lastCacheTime": now,
                        "items": [item(slug, lm or cr) for slug, lm, cr in listed if slug]},
            "category": {"entityType": "category", "lastCacheTime": now,
                         "items": [item(c.slug, None) for c in tree.nodes.values() if c.parent_id and c.slug]},
        }
        if entity_type in data:
            data = {entity_type: data[entity_type]}
        return Response(data)
