"""
Storefront Web API v1 Views (samian.mong.ir / api/v1/...)

Hybrid mode: website.Product provides slug, category, title, description.
SamianProduct (via ProductSamianLink) provides real price and inventory from Samian ERP.
Samian is source of truth for price/stock; website is source of truth for presentation.
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal
from urllib.parse import unquote

from django.db.models import Prefetch, Q, Sum
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.samian.models import (
    SamianBarcode,
    SamianDepartment,
    SamianInventory,
    SamianProduct,
    SamianProductColor,
)
from apps.samian.services.image_download import local_image_url
from apps.website.models import (
    Banner,
    Category,
    Collection,
    MediaAttachment,
    PrimaryConfig,
    Product,
    ProductColorMedia,
    ProductSamianLink,
    ProductVariant,
    SelectedProduct,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_config(key: str, default=None):
    """Read a PrimaryConfig value from the database and parse as JSON."""
    try:
        pc = PrimaryConfig.objects.get(key=key)
        if not pc.value:
            return default
        return json.loads(pc.value)
    except PrimaryConfig.DoesNotExist:
        return default
    except (json.JSONDecodeError, TypeError):
        return default


def _image_url_for_color(color: SamianProductColor, idx: int, img_item: dict) -> str:
    """Return local path if downloaded, otherwise fall back to proxy."""
    fp = img_item.get("filePath", "") if isinstance(img_item, dict) else ""
    if fp:
        url = local_image_url(color.productmain_id, fp)
        if url:
            return url
    return f"/api/samian/media/{color.samian_id}/{idx}/"


def _get_samian_product(website_product: Product) -> SamianProduct | None:
    """Get the linked SamianProduct for a website product, if any."""
    try:
        link = website_product.samian_link
        return SamianProduct.objects.filter(samian_id=link.samian_product_id).first()
    except ProductSamianLink.DoesNotExist:
        return None


def _samian_images(samian_product: SamianProduct, product_name: str, max_colors: int = 3, max_per_color: int | None = None) -> list[dict]:
    """Build image list from Samian color galleries."""
    images = []
    for color in samian_product.colors.filter(has_gallery=True)[:max_colors]:
        gallery = color.colorsgalery or []
        items = gallery if max_per_color is None else gallery[:max_per_color]
        for idx, img_item in enumerate(items):
            if not isinstance(img_item, dict):
                continue
            images.append({
                "id": len(images) + 1,
                "mediaUrl": _image_url_for_color(color, idx, img_item),
                "isVideo": False,
                "tooltipTitle": product_name,
                "alternative": product_name,
            })
    return images


def _website_images(website_product: Product) -> list[dict]:
    """Build image list from website MediaAttachment (table=14 direct, table=27 via ProductColorMedia)."""
    images = []
    attachments = MediaAttachment.objects.filter(
        table=MediaAttachment.Table.PRODUCTS,
        record_id=website_product.id,
        is_deleted=False,
    ).order_by("id")
    for att in attachments[:6]:
        images.append({
            "id": att.id,
            "mediaUrl": att.media_url,
            "isVideo": att.is_video,
            "tooltipTitle": att.tooltip_title or website_product.title,
            "alternative": att.alternative or website_product.title,
        })

    if not images:
        fv_ids = list(
            ProductColorMedia.objects.filter(product=website_product, is_deleted=False)
            .values_list("feature_value_id", flat=True)
        )
        if fv_ids:
            color_atts = MediaAttachment.objects.filter(
                table=MediaAttachment.Table.FEATURE_VALUE_MEDIAS,
                record_id__in=fv_ids,
                is_deleted=False,
            ).order_by("id")
            for att in color_atts[:6]:
                images.append({
                    "id": att.id,
                    "mediaUrl": att.media_url,
                    "isVideo": att.is_video,
                    "tooltipTitle": att.tooltip_title or website_product.title,
                    "alternative": att.alternative or website_product.title,
                })

    return images


def _product_price(website_product: Product, samian_product: SamianProduct | None) -> tuple[int, int, int]:
    """
    Return (base_price, reduction_percent, price_after_reduction).
    Samian is source of truth. Falls back to website price if no Samian link.
    """
    if samian_product and samian_product.sale_price:
        base = samian_product.sale_price
        list_item = samian_product.current_list_price()
        if list_item and list_item.final_price and list_item.final_price < base:
            reduction = round((base - list_item.final_price) * 100 / base)
            return base, reduction, list_item.final_price
        return base, 0, base

    wp_price = int(website_product.price) if website_product.price else 0
    wp_reduction = int(website_product.reduction) if website_product.reduction else 0
    if wp_price and wp_reduction:
        after = int(wp_price * (100 - wp_reduction) / 100)
        return wp_price, wp_reduction, after
    return wp_price, 0, wp_price


def _product_total_stock(samian_product: SamianProduct | None) -> int:
    """Total stock across all warehouses from Samian inventory."""
    if not samian_product:
        return 0
    result = SamianInventory.objects.filter(
        samian_barcode__samian_product=samian_product,
        qty__gt=0,
    ).aggregate(total=Sum("qty"))
    return int(result["total"] or 0)


def _build_product_item(wp: Product, sp: SamianProduct | None, *, include_details: bool = False) -> dict:
    """Build a product JSON object for the storefront API."""
    name = wp.title
    base_price, reduction, after_price = _product_price(wp, sp)

    images = _samian_images(sp, name, max_colors=2, max_per_color=1) if sp else []
    if not images:
        images = _website_images(wp)

    slug = wp.slug or f"product-{wp.barcode or wp.id}"

    item = {
        "id": wp.id,
        "productName": name,
        "slug": slug,
        "product_Base_Price": base_price,
        "product_base_reduction": reduction,
        "priceAfterReduction": after_price,
        "mainImages": images,
        "hasColor": bool(sp and sp.colors.exists()),
        "categoryId": wp.category_id,
        "parentCategoryId": wp.category.parent_id if wp.category_id and wp.category else None,
        "brandId": wp.brand_id,
    }

    if include_details:
        all_images = _samian_images(sp, name) if sp else []
        if not all_images:
            all_images = _website_images(wp)
        item["mainImages"] = all_images
        item["shortDescriptionHtml"] = wp.short_description_html or f"<p>{wp.short_desc or name}</p>"
        item["longDescriptionHtml"] = wp.long_description_html or f"<p>{wp.description or name}</p>"
        item["productName_En"] = (sp.name_en if sp else "") or ""
        item["description"] = wp.description or (sp.description if sp else "") or ""
        item["shortDesc"] = wp.short_desc or name
        item["productSizeGuid"] = wp.size_guide or None
        item["promotionLabel"] = None
        item["productBaseVat"] = int(wp.vat) if wp.vat else 0

        sizes = []
        if sp:
            for bc in SamianBarcode.objects.filter(samian_product=sp, is_active=True).order_by("size"):
                stock = SamianInventory.objects.filter(samian_barcode=bc, qty__gt=0).aggregate(s=Sum("qty"))
                sizes.append({
                    "barcode": bc.barcode,
                    "size": bc.size,
                    "color": bc.color,
                    "qty": int(stock["s"] or 0),
                    "price": bc.sale_price or base_price,
                })
        item["productSizes"] = sizes
        item["details"] = []
        item["productFeatures"] = []

    return item


# ---------------------------------------------------------------------------
# Config views
# ---------------------------------------------------------------------------

class PrimaryConfigGetConfigView(APIView):
    """
    GET /api/v1/PrimaryConfig/GetConfig/<key>
    POST /api/v1/PrimaryConfig/Get with body {"key": "..."}
    Reads from website.PrimaryConfig DB table. Falls back to hardcoded defaults for missing keys.
    """
    permission_classes = [AllowAny]

    DEFAULTS = {
        "adminMyThemeConfig": {"theme": "default"},
    }

    def _get_config_data(self, key_str: str):
        key_str = str(key_str).strip()
        data = _parse_config(key_str)
        if data is not None:
            return data
        return self.DEFAULTS.get(key_str, {})

    def get(self, request, key: str = ""):
        key_str = key or request.query_params.get("key", "")
        value = self._get_config_data(key_str)
        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "message": "موفق",
            "result": {"data": {"id": 1, "key": key_str, "value": value}},
            "data": value,
        })

    def post(self, request, key: str = ""):
        key_str = key or request.data.get("key", "")
        value = self._get_config_data(key_str)
        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "message": "موفق",
            "result": {"data": {"id": 1, "key": key_str, "value": value}},
            "data": value,
        })


class CompanyInfoView(APIView):
    """GET /api/v1/CompanyInfo/GetCompanyInfo"""
    permission_classes = [AllowAny]

    def get(self, request):
        data = _parse_config("companyConfigs")
        if data and isinstance(data, dict):
            support = data.get("support", {})
            phones = support.get("phoneNumbers", [])
            phone = phones[0]["value"] if phones else ""
            return Response({
                "isSuccess": True,
                "statusCode": 200,
                "result": {"data": {
                    "companyName": "فروشگاه پوشاک مانگ",
                    "title": "مانگ",
                    "telephone": phone,
                    "cellPhone": phone,
                    "address": _parse_config("contactUsConfig", {}).get("address", ""),
                    "email": _parse_config("contactUsConfig2", {}).get("socials", {}).get("email", "info@mong.ir"),
                    "workTime": support.get("description", ""),
                    "aboutUs": "فروشگاه پوشاک مانگ",
                }},
            })

        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "result": {"data": {
                "companyName": "فروشگاه پوشاک مانگ",
                "title": "مانگ",
                "telephone": "",
                "cellPhone": "",
                "address": "",
                "email": "info@mong.ir",
                "workTime": "",
                "aboutUs": "فروشگاه پوشاک مانگ",
            }},
        })


# ---------------------------------------------------------------------------
# Category views — reads from website.Category with Samian department fallback
# ---------------------------------------------------------------------------

def _category_to_dict(cat: Category, include_children: bool = True) -> dict:
    d = {
        "id": cat.id,
        "title": cat.title,
        "slug": cat.slug or f"cat-{cat.id}",
        "isOnlineActive": cat.is_online_active,
        "displayPriority": cat.display_priority,
        "inMainPage": cat.in_main_page,
    }
    if include_children:
        children = cat.children.filter(is_deleted=False, is_online_active=True).order_by("display_priority", "id")[:30]
        d["categories"] = [_category_to_dict(ch, include_children=False) for ch in children]
    else:
        d["categories"] = []
    return d


class CategoryGetAllView(APIView):
    """GET /api/v1/Category/GetAll"""
    permission_classes = [AllowAny]

    def get(self, request):
        roots = Category.objects.filter(
            parent__isnull=True, is_deleted=False, is_online_active=True,
        ).order_by("display_priority", "id")[:30]

        categories_data = [_category_to_dict(r) for r in roots]

        if not categories_data:
            dept_roots = SamianDepartment.objects.filter(parent__isnull=True)[:20]
            categories_data = [{
                "id": d.samian_id,
                "title": d.title,
                "slug": f"dept-{d.samian_id}",
                "isOnlineActive": True,
                "categories": [{
                    "id": ch.samian_id,
                    "title": ch.title,
                    "slug": f"dept-{ch.samian_id}",
                    "isOnlineActive": True,
                    "categories": [],
                } for ch in d.children.all()[:15]],
            } for d in dept_roots]

        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "result": {"data": {"categories": categories_data}},
            "data": categories_data,
        })


class CategoryGetByIdView(APIView):
    """GET /api/v1/Category/GetById/<id>"""
    permission_classes = [AllowAny]

    def get(self, request, category_id: int):
        try:
            cat = Category.objects.get(id=category_id, is_deleted=False)
            data = _category_to_dict(cat)
        except Category.DoesNotExist:
            try:
                dept = SamianDepartment.objects.get(samian_id=category_id)
                data = {
                    "id": dept.samian_id,
                    "title": dept.title,
                    "slug": f"dept-{dept.samian_id}",
                    "isOnlineActive": True,
                    "categories": [{
                        "id": ch.samian_id,
                        "title": ch.title,
                        "slug": f"dept-{ch.samian_id}",
                        "isOnlineActive": True,
                        "categories": [],
                    } for ch in dept.children.all()[:20]],
                }
            except SamianDepartment.DoesNotExist:
                data = {
                    "id": category_id,
                    "title": f"دسته‌بندی {category_id}",
                    "slug": f"cat-{category_id}",
                    "isOnlineActive": True,
                    "categories": [],
                }

        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "result": {"data": data},
            "data": data,
        })


# ---------------------------------------------------------------------------
# Product views — hybrid: website for presentation, Samian for price/stock
# ---------------------------------------------------------------------------

class ProductGetAllView(APIView):
    """POST /api/v1/Product/GetAll"""
    permission_classes = [AllowAny]

    def post(self, request):
        page_num = int(request.data.get("pageNumber", 1))
        page_size = min(int(request.data.get("pageSize", 20)), 100)
        offset = (page_num - 1) * page_size
        category_id = request.data.get("categoryId")
        filtered_cat_ids = request.data.get("filteredCategoryIds", [])
        search = request.data.get("search", "").strip()

        qs = Product.objects.filter(is_deleted=False, is_active=True).select_related("category", "brand")

        effective_cat_ids = []
        if category_id:
            effective_cat_ids = [int(category_id)]
        elif filtered_cat_ids:
            effective_cat_ids = [int(c) for c in filtered_cat_ids if c]

        if effective_cat_ids:
            all_cat_ids = list(effective_cat_ids)
            child_ids = list(Category.objects.filter(parent_id__in=effective_cat_ids, is_deleted=False).values_list("id", flat=True))
            all_cat_ids.extend(child_ids)
            qs = qs.filter(category_id__in=all_cat_ids)
        if search:
            qs = qs.filter(Q(title__icontains=search) | Q(barcode__icontains=search))

        qs = qs.order_by("-id")
        total_count = qs.count()
        products = list(qs[offset: offset + page_size])

        product_ids = [p.id for p in products]
        links = {
            link.product_id: link.samian_product_id
            for link in ProductSamianLink.objects.filter(product_id__in=product_ids)
        }
        samian_ids = set(links.values())
        samian_products = {
            sp.samian_id: sp
            for sp in SamianProduct.objects.filter(samian_id__in=samian_ids)
        } if samian_ids else {}

        items = []
        for wp in products:
            sp_id = links.get(wp.id)
            sp = samian_products.get(sp_id) if sp_id else None
            items.append(_build_product_item(wp, sp))

        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "data": {
                "items": items,
                "totalCount": total_count,
                "pageNumber": page_num,
                "pageSize": page_size,
            },
        })


class ProductGetSelectedProductsView(APIView):
    """GET /api/v1/Product/GetSelectedProducts"""
    permission_classes = [AllowAny]

    def get(self, request):
        selected_ids = list(
            SelectedProduct.objects.filter(is_deleted=False)
            .order_by("sorting_weight", "id")
            .values_list("product_id", flat=True)[:40]
        )

        if selected_ids:
            wp_qs = Product.objects.filter(id__in=selected_ids, is_deleted=False, is_active=True).select_related("category", "brand")
            wp_map = {p.id: p for p in wp_qs}
            products = [wp_map[pid] for pid in selected_ids if pid in wp_map]
        else:
            products = list(
                Product.objects.filter(is_deleted=False, is_active=True)
                .select_related("category", "brand")
                .order_by("-id")[:20]
            )

        product_ids = [p.id for p in products]
        links = {
            link.product_id: link.samian_product_id
            for link in ProductSamianLink.objects.filter(product_id__in=product_ids)
        }
        samian_ids = set(links.values())
        samian_products = {
            sp.samian_id: sp
            for sp in SamianProduct.objects.filter(samian_id__in=samian_ids)
        } if samian_ids else {}

        items = []
        for wp in products:
            sp_id = links.get(wp.id)
            sp = samian_products.get(sp_id) if sp_id else None
            item = _build_product_item(wp, sp)
            item["productBaseVat"] = int(wp.vat) if wp.vat else 0
            item["details"] = []
            items.append(item)

        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "result": {"data": items},
            "data": items,
        })


class ProductGetByIdView(APIView):
    """GET /api/v1/Product/GetById/<id>"""
    permission_classes = [AllowAny]

    def get(self, request, product_id: int):
        try:
            wp = Product.objects.select_related("category", "brand").get(id=product_id, is_deleted=False)
        except Product.DoesNotExist:
            return Response({"isSuccess": False, "message": "کالا یافت نشد"}, status=404)

        sp = _get_samian_product(wp)
        data = _build_product_item(wp, sp, include_details=True)

        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "result": {"data": data},
            "data": data,
        })


# ---------------------------------------------------------------------------
# Settings, sliders, banners
# ---------------------------------------------------------------------------

class SettingGetSettingView(APIView):
    """GET /api/v1/Setting/GetSetting"""
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "data": {
                "freeShippingThreshold": 15000000,
                "shippingCost": 650000,
                "isStoreOpen": True,
            },
        })


class SliderGetAllView(APIView):
    """GET /api/v1/Slider/GetAll"""
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "data": [],
        })


class BannerGetAllView(APIView):
    """GET /api/v1/Banner/GetAll"""
    permission_classes = [AllowAny]

    def get(self, request):
        banners = []
        for b in Banner.objects.filter(is_deleted=False, is_banner=True).order_by("display_priority", "id")[:20]:
            if not b.media_url:
                continue
            banners.append({
                "id": b.id,
                "mediaUrl": b.media_url,
                "link": b.link or "",
                "displayPriority": b.display_priority or 0,
                "isBanner": True,
            })
        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "data": banners,
        })


# ---------------------------------------------------------------------------
# SEO & SearchEngine
# ---------------------------------------------------------------------------

class SearchEngineMetaView(APIView):
    """GET /api/v1/SearchEngine/<entity_type>/<slug>/meta"""
    permission_classes = [AllowAny]

    def get(self, request, entity_type: str, slug: str):
        cleaned_slug = unquote(slug).strip()

        if entity_type == "product":
            wp = Product.objects.filter(slug=cleaned_slug, is_deleted=False).first()
            if wp:
                sp = _get_samian_product(wp)
                base_price, _, after_price = _product_price(wp, sp)
                title = f"{wp.title} | مانگ"
                description = wp.short_desc or wp.description or wp.title
                data = {
                    "title": title,
                    "metaDescription": description[:200],
                    "keywords": ["مانگ", wp.title, "پوشاک"],
                    "canonicalUrl": f"/product/{cleaned_slug}",
                    "context": "https://schema.org/",
                    "type": "Product",
                    "name": wp.title,
                    "offers": {
                        "type": "Offer",
                        "urlSlug": cleaned_slug,
                        "priceCurrency": "IRR",
                        "price": str(after_price),
                        "availability": "https://schema.org/InStock",
                        "itemCondition": "https://schema.org/NewCondition",
                    },
                }
                return Response({
                    "isSuccess": True,
                    "statusCode": 200,
                    "result": {"data": data},
                    "data": data,
                })

        title = f"{cleaned_slug} | مانگ" if cleaned_slug else "فروشگاه پوشاک مانگ"
        description = f"خرید آنلاین انواع {cleaned_slug} با بهترین قیمت، کیفیت و ارسال سریع از فروشگاه مانگ."
        data = {
            "title": title,
            "metaDescription": description,
            "keywords": ["مانگ", cleaned_slug, "پوشاک", "خرید آنلاین"],
            "canonicalUrl": "",
            "context": "https://schema.org/",
            "type": "CollectionPage" if entity_type == "category" else "Product",
            "name": title,
            "offers": {
                "type": "Offer",
                "urlSlug": cleaned_slug,
                "priceCurrency": "IRR",
                "price": "0",
                "availability": "https://schema.org/InStock",
                "itemCondition": "https://schema.org/NewCondition",
            },
        }
        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "result": {"data": data},
            "data": data,
        })


class SearchEngineBreadcrumbsView(APIView):
    """GET /api/v1/SearchEngine/<entity_type>/<slug>/breadcrumbs"""
    permission_classes = [AllowAny]

    def get(self, request, entity_type: str, slug: str):
        cleaned_slug = unquote(slug).strip()
        breadcrumbs = [
            {"title": "صفحه اصلی", "url": "/"},
        ]

        if entity_type == "product":
            wp = Product.objects.filter(slug=cleaned_slug, is_deleted=False).select_related("category__parent").first()
            if wp and wp.category:
                if wp.category.parent:
                    breadcrumbs.append({"title": wp.category.parent.title, "url": f"/products-category/{wp.category.parent.slug or wp.category.parent_id}"})
                breadcrumbs.append({"title": wp.category.title, "url": f"/products-category/{wp.category.slug or wp.category_id}"})
            breadcrumbs.append({"title": wp.title if wp else cleaned_slug, "url": f"/product/{cleaned_slug}"})
        else:
            breadcrumbs.append({"title": cleaned_slug, "url": f"/{entity_type}/{slug}"})

        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "result": {"data": breadcrumbs},
            "data": breadcrumbs,
        })


class SearchEngineIndexView(APIView):
    """GET /api/v1/SearchEngine/<entity_type>/<slug>/index — returns the entity's DB id."""
    permission_classes = [AllowAny]

    def get(self, request, entity_type: str, slug: str):
        cleaned_slug = unquote(slug).strip()
        if entity_type == "category":
            cat = Category.objects.filter(slug=cleaned_slug, is_deleted=False).first()
            if cat:
                return Response(cat.id, status=status.HTTP_200_OK)
        elif entity_type == "product":
            wp = Product.objects.filter(slug=cleaned_slug, is_deleted=False).first()
            if wp:
                return Response(wp.id, status=status.HTTP_200_OK)
        return Response(None, status=status.HTTP_200_OK)


class SearchEngineSiteMapsView(APIView):
    """GET /api/v1/SearchEngine/SiteMaps"""
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "result": {
                "data": {
                    "product": {"entityType": "product", "lastCacheTime": "", "items": []},
                    "category": {"entityType": "category", "lastCacheTime": "", "items": []},
                    "blog": {"entityType": "blog", "lastCacheTime": "", "items": []},
                },
            },
        })


# ---------------------------------------------------------------------------
# Homepage summaries
# ---------------------------------------------------------------------------

class CategoryGetSliderBannerSummariesView(APIView):
    """POST /api/v1/Category/GetSliderBannerSummaries"""
    permission_classes = [AllowAny]

    def post(self, request):
        config = _parse_config("sortRowsConfig", [])
        banner_items = []
        if isinstance(config, list):
            for row in config:
                if isinstance(row, dict) and row.get("type") == "banner":
                    for item in row.get("selectedIds", []):
                        if isinstance(item, dict) and "id" in item:
                            banner_items.append(item)
                        elif isinstance(item, int):
                            banner_items.append({"id": item})

        banner_ids = [b["id"] for b in banner_items]
        banner_objs = {b.id: b for b in Banner.objects.filter(id__in=banner_ids, is_deleted=False)} if banner_ids else {}

        banners = []
        for idx, item in enumerate(banner_items):
            bid = item["id"]
            media_url = item.get("mediaUrl") or ""
            link = ""
            banner_obj = banner_objs.get(bid)
            if not media_url and banner_obj:
                media_url = banner_obj.media_url or ""
            if banner_obj:
                link = banner_obj.link or ""
            if media_url:
                banners.append({
                    "id": bid,
                    "mediaUrl": media_url,
                    "link": link,
                    "displayPriority": idx + 1,
                    "isBanner": True,
                })

        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "message": "موفق",
            "result": {"data": {"banners": banners}},
            "data": {"banners": banners},
        })


class CategoryGetCategorySummariesView(APIView):
    """POST /api/v1/Category/GetCategorySummaries"""
    permission_classes = [AllowAny]

    def post(self, request):
        config = _parse_config("sortRowsConfig", [])
        cat_ids = []
        if isinstance(config, list):
            for row in config:
                if isinstance(row, dict) and row.get("type") == "category":
                    for item in row.get("selectedIds", []):
                        if isinstance(item, dict) and "id" in item:
                            cat_ids.append(item["id"])
                        elif isinstance(item, int):
                            cat_ids.append(item)

        categories = []
        if cat_ids:
            cats = {c.id: c for c in Category.objects.filter(id__in=cat_ids, is_deleted=False)}
            for cid in cat_ids:
                cat = cats.get(cid)
                if not cat:
                    continue
                attachments = MediaAttachment.objects.filter(
                    table=MediaAttachment.Table.CATEGORIES,
                    record_id=cat.id,
                    is_deleted=False,
                ).order_by("id")[:1]
                categories.append({
                    "id": cat.id,
                    "title": cat.title,
                    "slug": cat.slug or f"cat-{cat.id}",
                    "displayPriority": cat.display_priority,
                    "inMainPage": cat.in_main_page,
                    "isOnlineActive": cat.is_online_active,
                    "mediaAttachments": [{
                        "id": att.id,
                        "isVideo": att.is_video,
                        "mediaUrl": att.media_url,
                        "alternative": att.alternative or cat.title,
                        "tooltipTitle": att.tooltip_title or cat.title,
                    } for att in attachments],
                    "categories": None,
                    "longDescriptionHtml": cat.long_description_html,
                    "shortDescriptionHtml": cat.short_description_html,
                })
        else:
            for cat in Category.objects.filter(is_deleted=False, is_online_active=True, in_main_page=True).order_by("display_priority")[:6]:
                attachments = MediaAttachment.objects.filter(
                    table=MediaAttachment.Table.CATEGORIES,
                    record_id=cat.id,
                    is_deleted=False,
                ).order_by("id")[:1]
                categories.append({
                    "id": cat.id,
                    "title": cat.title,
                    "slug": cat.slug or f"cat-{cat.id}",
                    "displayPriority": cat.display_priority,
                    "inMainPage": cat.in_main_page,
                    "isOnlineActive": cat.is_online_active,
                    "mediaAttachments": [{
                        "id": att.id,
                        "isVideo": att.is_video,
                        "mediaUrl": att.media_url,
                        "alternative": att.alternative or cat.title,
                        "tooltipTitle": att.tooltip_title or cat.title,
                    } for att in attachments],
                    "categories": None,
                    "longDescriptionHtml": cat.long_description_html,
                    "shortDescriptionHtml": cat.short_description_html,
                })

        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "message": "موفق",
            "result": {"data": categories},
            "data": categories,
        })


class CollectionGetCollectionSummariesView(APIView):
    """POST /api/v1/Collection/GetCollectionSummaries"""
    permission_classes = [AllowAny]

    def post(self, request):
        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "message": "موفق",
            "result": {"data": []},
            "data": [],
        })


class OutfitGetOutfitSummariesView(APIView):
    """POST /api/v1/Outfit/GetOutfitSummaries"""
    permission_classes = [AllowAny]

    def post(self, request):
        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "message": "موفق",
            "result": {"data": []},
            "data": [],
        })
