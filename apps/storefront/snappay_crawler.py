"""
SnappPay (SearchWise) Product Crawler & Feed Integration.

Implements the official SnappPay crawler specifications:
- Method 1: Sitemap & direct product crawling (SEO metadata in Next.js).
- Method 2: Structured product feed (JSON / XML) at /api/snappay/feed.
- Method 3: REST API with pagination & item lookup at /api/snappay/products.
- Compatibility: Legacy .NET endpoints (/api/SnappPay/ProductList, /api/SnappPay/ProductInfo)
  supporting both GET and POST requests.
"""
from __future__ import annotations

import html
import json
import math
import os
import re
import urllib.parse
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from apps.storefront import catalog
from apps.website.models import Product, ProductAIProfile

# Official SearchWise / SnappPay crawler IPs from specification
SNAPPAY_DEFAULT_IPS = {
    "185.206.93.115",
    "185.206.94.25",
    "37.152.176.176",
    "188.121.106.231",
}

SNAPPAY_FEED_CACHE_KEY = "snappay:products:feed:v1"
SNAPPAY_FEED_CACHE_TTL = 300  # 5 minutes


def get_base_url() -> str:
    """
    Get canonical site base URL strictly from settings.SITE_URL or .env.
    e.g. 'https://samian.mong.ir' or 'https://mong.ir'
    """
    url = getattr(settings, "SITE_URL", "") or getattr(settings, "PUBLIC_BASE_URL", "") or os.getenv("SITE_URL") or "https://mong.ir"
    return url.rstrip("/")


def normalize_url(url: str, base_url: str | None = None) -> str:
    """
    Ensure any product or media URL strictly uses the base domain defined in .env (SITE_URL).
    Rebases relative URLs (/products-item/..., /img/...) as well as URLs
    from other staging/production domains (samian.mong.ir, third-party.mong.ir, mong.ir, localhost).
    """
    if not url:
        return ""
    if base_url is None:
        base_url = get_base_url()

    url_str = str(url).strip()
    if url_str.startswith("/"):
        return f"{base_url}{url_str}"

    parsed = urllib.parse.urlsplit(url_str)
    if parsed.netloc:
        hostname = (parsed.hostname or "").lower()
        if hostname.endswith("mong.ir") or hostname in {"localhost", "127.0.0.1"}:
            base_parsed = urllib.parse.urlsplit(base_url)
            rebased = parsed._replace(scheme=base_parsed.scheme, netloc=base_parsed.netloc)
            return urllib.parse.urlunsplit(rebased)
    return url_str


def _should_force_refresh(request: HttpRequest) -> bool:
    """Check if caller requests bypassing and refreshing the 5-minute cache."""
    return request.GET.get("refresh", "").lower() in ("true", "1") or request.GET.get("nocache") == "1"


def _clean_xml_str(text: Any) -> str:
    """Remove XML 1.0 invalid control characters and escape CDATA delimiters."""
    if text is None:
        return ""
    s = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", str(text))
    return s.replace("]]>", "]]&gt;")


def invalidate_snappay_cache() -> None:
    """Clear all SnappPay feed cache keys (useful after syncing AI profiles or inventory)."""
    base_url = get_base_url()
    netloc = urllib.parse.urlsplit(base_url).netloc or "default"
    cache.delete(f"{SNAPPAY_FEED_CACHE_KEY}:{netloc}")
    cache.delete(SNAPPAY_FEED_CACHE_KEY)


def get_client_ip(request: HttpRequest) -> str:
    """Extract client IP handling proxies / Nginx X-Forwarded-For."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    x_real_ip = request.META.get("HTTP_X_REAL_IP")
    if x_real_ip:
        return x_real_ip.strip()
    return request.META.get("REMOTE_ADDR", "").strip()


def is_snappay_authorized(request: HttpRequest) -> bool:
    """
    Check if the incoming request is authorized to access the SnappPay feeds.
    Checks:
    1. If IP restriction is disabled in settings (SNAPPAY_RESTRICT_IP=False by default for public feeds).
    2. Header token authentication (Bearer token or X-SnappPay-Token).
    3. Official SnappPay Crawler IPs.
    4. Local development / loopback.
    """
    # If explicit IP restriction is not enabled, allow access (recommended for public crawler feeds)
    restrict_ip = getattr(settings, "SNAPPAY_RESTRICT_IP", False)
    if not restrict_ip:
        return True

    # Allow local testing in debug mode
    client_ip = get_client_ip(request)
    if settings.DEBUG and client_ip in ("127.0.0.1", "::1", "localhost", ""):
        return True

    # Check Header Authentication (PDF Page 5)
    auth_header = (
        request.headers.get("Authorization")
        or request.headers.get("X-SnappPay-Token")
        or request.META.get("HTTP_AUTHORIZATION")
        or ""
    )
    expected_token = getattr(settings, "SNAPPAY_CRAWLER_TOKEN", None)
    if expected_token:
        if auth_header == f"Bearer {expected_token}" or auth_header == expected_token:
            return True

    # Check Whitelisted IPs (PDF Page 1)
    allowed_ips = set(getattr(settings, "SNAPPAY_ALLOWED_IPS", [])) | SNAPPAY_DEFAULT_IPS
    if client_ip in allowed_ips:
        return True

    return False


def _norm(text: str | None) -> str:
    return (text or "").replace("ي", "ی").replace("ك", "ک").replace("‌", " ").strip().lower()


def format_title(title: str, category_title: str | None, brand_title: str = "مانگ") -> str:
    """
    Format product title according to PDF guidelines:
    Includes category, model/name, and brand for optimal search matching.
    e.g. "مانتو زنانه مانگ مدل تورین 3"
    """
    title = (title or "").strip()
    if not title:
        return ""
    cat = (category_title or "").strip()
    norm_title = _norm(title)
    norm_cat = _norm(cat)
    norm_brand = _norm(brand_title)

    if norm_cat and norm_cat in norm_title:
        # Title already mentions the category (e.g. "کت دو جیب فوتر اسپرت")
        if norm_brand not in norm_title and "زنانه" not in norm_title:
            return f"{title} زنانه {brand_title}"
        return title

    parts = []
    if cat:
        parts.append(cat)
    parts.append("زنانه")
    parts.append(brand_title)

    prefix = " ".join(parts)
    if "مدل" not in norm_title:
        return f"{prefix} مدل {title}"
    return f"{prefix} {title}"


def parse_description(p: Product, attributes: dict | None = None) -> dict[str, str]:
    """
    Build structured key-value description object according to PDF specification.
    Extracts attributes from p.short_desc, the sales software, and p.description.
    """
    desc_dict: dict[str, str] = {"برند": "مانگ"}

    raw = p.short_desc or ""
    if "%" in raw:
        try:
            raw = urllib.parse.unquote(raw)
        except Exception:
            pass

    # Extract #Key\n Value pairs
    for part in raw.split("#"):
        part = part.strip()
        if not part:
            continue
        if "\n" in part:
            k, v = part.split("\n", 1)
            k, v = k.strip(), v.strip()
            if k and v:
                desc_dict[k] = v
        elif ":" in part:
            k, v = part.split(":", 1)
            k, v = k.strip(), v.strip()
            if k and v:
                desc_dict[k] = v

    # Add attributes from the sales software
    for name, value in (attributes or {}).items():
        if value and name not in desc_dict:
            desc_dict[name] = str(value).strip()

    # Add long description if present
    if p.description and p.description.strip():
        desc_dict["توضیحات تکمیلی"] = p.description.strip()

    return desc_dict


def build_snappay_product(
    p: Product,
    bundle: catalog.ProductBundle,
    tree: catalog.CategoryTree | None = None,
    ai: ProductAIProfile | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """
    Build single product dictionary matching the PDF fields with AI Profile enrichment:
    - id: Unique product ID (string)
    - title: Rich AI-crafted SEO title (includes garment type, details, brand, model)
    - subtitle: Model name / English name
    - link: Full canonical website URL (/products-item/<slug>)
    - image_link: Array of absolute image URLs (cover image first)
    - availability: "in stock" | "out of stock"
    - regular_price: Regular price in Rials (integer)
    - sale_price: Discounted sale price in Rials (integer)
    - category: Full category hierarchy (e.g. "مد و پوشاک > زنانه > روپوش > مانتو")
    - description: Rich key-value object (attributes, fabric, style, season, bullets, stylist note, keywords)
    - brand: Brand name ("مانگ")
    - GTIN / gtin: Barcode / GTIN
    - color: Available colors
    - size: Available sizes
    - shipping_cost: 0 (free shipping)
    - delivery_time: Shipping days
    - search_keywords: List of SEO keywords from LEBAZAI
    - summary_bullets: Bullet points from LEBAZAI
    - meta_description: Meta description from LEBAZAI
    """
    if tree is None:
        tree = catalog.category_tree()

    if base_url is None:
        base_url = get_base_url()

    pr = bundle.pricing(p.id)
    erp = bundle.erp.get(p.id)
    name_en = erp.name_en if erp else ""
    imgs = bundle.main_images(p.id)
    in_stk = bundle.in_stock(p.id)

    # 1. Category hierarchy
    cat_chain = ["مد و پوشاک"]
    if p.category_id:
        ancestors = tree.ancestors(p.category_id)
        for c in ancestors:
            if c.title != "مد و پوشاک":
                cat_chain.append(c.title)
    category_str = " > ".join(cat_chain)

    # 2. Title: Use AI Title (LEBAZAI) if available, otherwise formatted ERP title
    if ai and ai.title:
        ai_t = ai.title.strip()
        if "مانگ" not in ai_t:
            title = f"{ai_t} مانگ"
        else:
            title = ai_t
        # Append internal model name if not already in title
        if p.title and p.title not in title and "مدل" not in title:
            title = f"{title} مدل {p.title}"
    else:
        cat_title = p.category.title if p.category else ""
        title = format_title(p.title, cat_title, brand_title="مانگ")

    # 3. Subtitle: Model name or English name
    if name_en:
        subtitle = name_en
    elif ai and ai.title and p.title:
        subtitle = p.title
    else:
        subtitle = ""

    # 4. Description Key-Value Object (Enhanced with AI Attributes, Bullets & Stylist notes)
    desc_dict: dict[str, Any] = {"برند": "مانگ"}
    if ai:
        if ai.attributes and isinstance(ai.attributes, dict):
            attrs = ai.attributes
            if attrs.get("garment_type_fa"):
                desc_dict["نوع لباس"] = attrs["garment_type_fa"]
            if attrs.get("season_fa"):
                desc_dict["فصل"] = attrs["season_fa"]
            if attrs.get("fit_fa"):
                desc_dict["فرم / تن‌خور"] = attrs["fit_fa"]
            if attrs.get("pattern_fa"):
                desc_dict["طرح پارچه"] = attrs["pattern_fa"]
            if attrs.get("formality_fa"):
                desc_dict["میزان رسمی بودن"] = str(attrs["formality_fa"])
            if attrs.get("occasions_fa") and isinstance(attrs["occasions_fa"], list):
                desc_dict["مناسبت"] = "، ".join(attrs["occasions_fa"])
            if attrs.get("styles_fa") and isinstance(attrs["styles_fa"], list):
                desc_dict["سبک استایل"] = "، ".join(attrs["styles_fa"])
            if attrs.get("age_groups_fa") and isinstance(attrs["age_groups_fa"], list):
                desc_dict["رده سنی"] = "، ".join(attrs["age_groups_fa"])
        if ai.summary_bullets:
            desc_dict["ویژگی‌های کلیدی"] = " | ".join(ai.summary_bullets)
        if ai.stylist_note:
            desc_dict["پیشنهاد استایلیست"] = ai.stylist_note
        if ai.search_keywords:
            desc_dict["کلیدواژه‌ها"] = "، ".join(ai.search_keywords)
        if ai.fab:
            desc_dict["مزایا و کاربرد"] = ai.fab
    else:
        desc_dict.update(parse_description(p, erp.attributes if erp else None))

    # Add general description if not already in dictionary
    if p.description and p.description.strip() and "توضیحات تکمیلی" not in desc_dict:
        desc_dict["توضیحات تکمیلی"] = p.description.strip()

    # 5. Image links (Full-resolution WebP URLs rebased to base_url from .env)
    image_links = [
        normalize_url(img["mediaUrl"], base_url)
        for img in imgs
        if img.get("mediaUrl")
    ]

    # 6. Pricing in Rials (integers)
    regular_price = int(pr.base)
    sale_price = int(pr.after)
    if regular_price <= 0 and sale_price > 0:
        regular_price = sale_price
    elif regular_price < sale_price:
        regular_price = sale_price

    # 7. Variants (colors & sizes)
    visible_variants = bundle.visible_variants(p.id)
    colors = list(dict.fromkeys(v.color.name for v in visible_variants if v.color and v.color.name))
    sizes = list(dict.fromkeys(v.size.name for v in visible_variants if v.size and v.size.name))

    link = f"{base_url}/products-item/{p.slug}"

    item: dict[str, Any] = {
        "id": str(p.id),
        "title": title,
        "subtitle": subtitle,
        "link": link,
        "image_link": image_links,
        "availability": "in stock" if in_stk else "out of stock",
        "regular_price": regular_price,
        "sale_price": sale_price,
        "category": category_str,
        "description": desc_dict,
        "brand": "مانگ",
        "GTIN": p.barcode or (erp.subcode if erp else "") or "",
        "gtin": p.barcode or (erp.subcode if erp else "") or "",
    }

    if colors:
        item["color"] = ", ".join(colors)
    if sizes:
        item["size"] = ", ".join(sizes)

    item["shipping_cost"] = 0
    item["delivery_time"] = p.shipping_time or 3

    # Additional SEO fields from AI profile
    if ai:
        if ai.search_keywords:
            item["search_keywords"] = ai.search_keywords
        if ai.meta_description:
            item["meta_description"] = ai.meta_description
        if ai.summary_bullets:
            item["summary_bullets"] = ai.summary_bullets

    return item


def get_all_snappay_products(
    force_refresh: bool = False,
    base_url: str | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch and serialize all live products with AI profile enrichment and caching.
    Supports force_refresh=True to bypass and rebuild the 5-minute cache.
    """
    if base_url is None:
        base_url = get_base_url()

    netloc = urllib.parse.urlsplit(base_url).netloc or "default"
    cache_key = f"{SNAPPAY_FEED_CACHE_KEY}:{netloc}"

    if not force_refresh:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    rows = catalog.listing_rows()
    ids = [r.id for r in rows]
    bundle = catalog.ProductBundle.load(ids)
    tree = catalog.category_tree()
    ai_profiles = ProductAIProfile.objects.filter(product_id__in=ids).in_bulk(field_name="product_id")

    products_data: list[dict[str, Any]] = []
    for r in rows:
        p = bundle.products.get(r.id)
        if not p:
            continue
        ai = ai_profiles.get(p.id)
        item = build_snappay_product(p, bundle, tree, ai=ai, base_url=base_url)
        products_data.append(item)

    cache.set(cache_key, products_data, SNAPPAY_FEED_CACHE_TTL)
    return products_data


def get_single_snappay_product(
    identifier: int | str,
    base_url: str | None = None,
) -> dict[str, Any] | None:
    """Find a single product by ID or Slug with AI profile enrichment (live database lookup)."""
    p = None
    if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
        p = Product.objects.filter(id=int(identifier), is_active=True, is_deleted=False).first()
    if not p and isinstance(identifier, str):
        p = Product.objects.filter(slug=identifier, is_active=True, is_deleted=False).first()
    if not p:
        return None

    bundle = catalog.ProductBundle.load([p.id])
    if p.id not in bundle.products:
        return None

    ai = ProductAIProfile.objects.filter(product=p).first()
    return build_snappay_product(p, bundle, ai=ai, base_url=base_url)


def to_xml(products: list[dict[str, Any]]) -> str:
    """
    Convert product list to standard valid XML feed.
    Follows SnappPay specification:
    - Elements: id, title, subtitle, link, image_link, availability, regular_price, sale_price,
      category, description, brand, GTIN, color, size, shipping_cost, delivery_time.
    - Description: Uses <attribute name="نام ویژگی"><![CDATA[مقدار]]></attribute> for key-values
      to strictly adhere to XML syntax (XML element tag names cannot contain spaces or slashes).
    """
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<products>"]
    for p in products:
        lines.append("  <product>")
        lines.append(f"    <id>{_clean_xml_str(p.get('id', ''))}</id>")
        lines.append(f"    <title><![CDATA[{_clean_xml_str(p.get('title', ''))}]]></title>")
        lines.append(f"    <subtitle><![CDATA[{_clean_xml_str(p.get('subtitle', ''))}]]></subtitle>")
        lines.append(f"    <link><![CDATA[{_clean_xml_str(p.get('link', ''))}]]></link>")
        lines.append("    <image_link>")
        for img in p.get("image_link", []):
            lines.append(f"      <image><![CDATA[{_clean_xml_str(img)}]]></image>")
        lines.append("    </image_link>")
        lines.append(f"    <availability>{_clean_xml_str(p.get('availability', ''))}</availability>")
        lines.append(f"    <regular_price>{p.get('regular_price', 0)}</regular_price>")
        lines.append(f"    <sale_price>{p.get('sale_price', 0)}</sale_price>")
        lines.append(f"    <category><![CDATA[{_clean_xml_str(p.get('category', ''))}]]></category>")
        lines.append("    <description>")
        for k, v in p.get("description", {}).items():
            k_esc = html.escape(str(k), quote=True)
            v_clean = _clean_xml_str(v)
            lines.append(f'      <attribute name="{k_esc}"><![CDATA[{v_clean}]]></attribute>')
        lines.append("    </description>")
        lines.append(f"    <brand><![CDATA[{_clean_xml_str(p.get('brand', ''))}]]></brand>")
        gtin = p.get("GTIN") or p.get("gtin") or ""
        lines.append(f"    <GTIN>{_clean_xml_str(gtin)}</GTIN>")
        if "color" in p and p["color"]:
            lines.append(f"    <color><![CDATA[{_clean_xml_str(p['color'])}]]></color>")
        if "size" in p and p["size"]:
            lines.append(f"    <size><![CDATA[{_clean_xml_str(p['size'])}]]></size>")
        lines.append(f"    <shipping_cost>{p.get('shipping_cost', 0)}</shipping_cost>")
        lines.append(f"    <delivery_time>{p.get('delivery_time', 3)}</delivery_time>")
        if "search_keywords" in p and p["search_keywords"]:
            kw_str = ", ".join(p["search_keywords"])
            lines.append(f"    <keywords><![CDATA[{_clean_xml_str(kw_str)}]]></keywords>")
        if "meta_description" in p and p["meta_description"]:
            lines.append(f"    <meta_description><![CDATA[{_clean_xml_str(p['meta_description'])}]]></meta_description>")
        lines.append("  </product>")
    lines.append("</products>")
    return "\n".join(lines)


# =============================================================================
# Views
# =============================================================================

@method_decorator(csrf_exempt, name="dispatch")
class SnappPayFeedView(View):
    """
    Method 2: Product Feed (JSON / XML).
    GET /api/snappay/feed
    GET /api/snappay/feed.json
    GET /api/snappay/feed.xml
    Pass ?refresh=true or ?nocache=1 to force refresh cache.
    """

    def get(self, request: HttpRequest, *args, **kwargs):
        if not is_snappay_authorized(request):
            return JsonResponse({"error": "Forbidden: IP not allowed"}, status=403)

        force_refresh = _should_force_refresh(request)
        feed_format = request.GET.get("format", "").lower()
        if kwargs.get("format") == "xml" or feed_format == "xml":
            products = get_all_snappay_products(force_refresh=force_refresh)
            return HttpResponse(to_xml(products), content_type="application/xml; charset=utf-8")

        products = get_all_snappay_products(force_refresh=force_refresh)
        return JsonResponse(products, safe=False, json_dumps_params={"ensure_ascii": False})


@method_decorator(csrf_exempt, name="dispatch")
class SnappPayProductsView(View):
    """
    Method 3: Product API with pagination and single product query.
    GET /api/snappay/products?page=1&size=50
    GET /api/snappay/products?id=139
    GET /api/snappay/products?slug=تورین-3
    Pass ?refresh=true to force refresh product cache.
    """

    def get(self, request: HttpRequest, *args, **kwargs):
        if not is_snappay_authorized(request):
            return JsonResponse({"error": "Forbidden: IP not allowed"}, status=403)

        # 1. Single product lookup via query parameter (un-cached, real-time)
        pid = request.GET.get("id")
        slug = request.GET.get("slug")
        if pid or slug:
            item = get_single_snappay_product(pid or slug)
            if not item:
                return JsonResponse({"error": "Product not found"}, status=404)
            return JsonResponse(item, json_dumps_params={"ensure_ascii": False})

        # 2. Paginated list
        force_refresh = _should_force_refresh(request)
        all_products = get_all_snappay_products(force_refresh=force_refresh)
        total_count = len(all_products)

        page_str = request.GET.get("page")
        size_str = request.GET.get("size")

        # If no page/size given and format is raw array requested
        if not page_str and not size_str and request.GET.get("format") == "array":
            return JsonResponse(all_products, safe=False, json_dumps_params={"ensure_ascii": False})

        page = max(1, int(page_str)) if page_str and page_str.isdigit() else 1
        size = max(1, min(200, int(size_str))) if size_str and size_str.isdigit() else 50

        start = (page - 1) * size
        end = start + size
        page_items = all_products[start:end]
        total_pages = math.ceil(total_count / size) if size > 0 else 1

        payload = {
            "total": total_count,
            "count": total_count,
            "page": page,
            "size": size,
            "total_pages": total_pages,
            "data": page_items,
            "results": page_items,
            "products": page_items,
        }

        response = JsonResponse(payload, json_dumps_params={"ensure_ascii": False})
        response["X-Total-Count"] = str(total_count)
        response["X-Page"] = str(page)
        response["X-Page-Size"] = str(size)
        response["X-Total-Pages"] = str(total_pages)
        return response


@method_decorator(csrf_exempt, name="dispatch")
class SnappPayProductDetailView(View):
    """
    Method 3: Direct Single Product Lookup by ID or Slug.
    GET /api/snappay/products/<identifier>
    """

    def get(self, request: HttpRequest, identifier: str, *args, **kwargs):
        if not is_snappay_authorized(request):
            return JsonResponse({"error": "Forbidden: IP not allowed"}, status=403)

        item = get_single_snappay_product(identifier)
        if not item:
            return JsonResponse({"error": "Product not found"}, status=404)
        return JsonResponse(item, json_dumps_params={"ensure_ascii": False})


@method_decorator(csrf_exempt, name="dispatch")
class SnappPayLegacyProductListView(View):
    """
    Backward Compatibility Endpoint:
    Matches legacy .NET route: /api/SnappPay/ProductList
    Supports both GET (standard crawler) and POST (legacy .NET).
    Returns wrapped ResultDto for legacy parser compatibility.
    """

    def _extract_params(self, request: HttpRequest) -> dict[str, Any]:
        params = dict(request.GET.items())
        if request.method == "POST":
            # Form data or JSON body
            params.update(request.POST.items())
            if request.body:
                try:
                    body = json.loads(request.body.decode("utf-8"))
                    if isinstance(body, dict):
                        params.update(body)
                except Exception:
                    pass
        return params

    def _handle(self, request: HttpRequest):
        if not is_snappay_authorized(request):
            return JsonResponse(
                {"result": None, "resultMessage": "Forbidden: IP not whitelisted", "statusCode": 403},
                status=403,
            )

        params = self._extract_params(request)
        pid = params.get("id") or params.get("Id")
        slug = params.get("slug") or params.get("Slug")

        # Single product lookup
        if pid or slug:
            item = get_single_snappay_product(pid or slug)
            if not item:
                return JsonResponse(
                    {
                        "isSuccess": False,
                        "statusCode": 404,
                        "statusMessage": "یافت نشد",
                        "resultMessage": "محصولی با این مشخصات یافت نشد.",
                        "error": None,
                        "errors": None,
                    },
                    status=404,
                )
            return JsonResponse(
                {
                    "isSuccess": True,
                    "statusCode": 200,
                    "statusMessage": "موفق",
                    "resultMessage": "اطلاعات با موفقیت یافت شد.",
                    "result": item,
                },
                json_dumps_params={"ensure_ascii": False},
            )

        # Product list pagination
        force_refresh = str(params.get("refresh", "")).lower() in ("true", "1") or params.get("nocache") == "1"
        all_products = get_all_snappay_products(force_refresh=force_refresh)
        total_count = len(all_products)

        page_val = params.get("page") or params.get("PageNumber") or params.get("pageNumber") or 1
        size_val = params.get("size") or params.get("PageSize") or params.get("pageSize") or 50

        try:
            page = max(1, int(page_val))
        except (ValueError, TypeError):
            page = 1

        try:
            size = max(1, min(200, int(size_val)))
        except (ValueError, TypeError):
            size = 50

        start = (page - 1) * size
        end = start + size
        page_items = all_products[start:end]
        max_pages = math.ceil(total_count / size) if size > 0 else 1

        # Match legacy PaginationResult & ResultDto shape from dadehfa-snappay.pdf
        return JsonResponse(
            {
                "isSuccess": True,
                "statusCode": 200,
                "statusMessage": "موفق",
                "resultMessage": "اطلاعات با موفقیت یافت شد.",
                "result": {
                    "pageNumber": page,
                    "maxPages": max_pages,
                    "totalCount": total_count,
                    "hasNext": page < max_pages,
                    "hasPrevious": page > 1,
                    "data": page_items,
                },
            },
            json_dumps_params={"ensure_ascii": False},
        )

    def get(self, request: HttpRequest):
        return self._handle(request)

    def post(self, request: HttpRequest):
        return self._handle(request)


@method_decorator(csrf_exempt, name="dispatch")
class SnappPayLegacyProductInfoView(View):
    """
    Backward Compatibility Endpoint:
    Matches legacy .NET route: /api/SnappPay/ProductInfo
    Supports both GET and POST.
    """

    def _extract_params(self, request: HttpRequest) -> dict[str, Any]:
        params = dict(request.GET.items())
        if request.method == "POST":
            params.update(request.POST.items())
            if request.body:
                try:
                    body = json.loads(request.body.decode("utf-8"))
                    if isinstance(body, dict):
                        params.update(body)
                except Exception:
                    pass
        return params

    def _handle(self, request: HttpRequest):
        if not is_snappay_authorized(request):
            return JsonResponse(
                {"isSuccess": False, "result": None, "resultMessage": "Forbidden: IP not whitelisted", "statusCode": 403},
                status=403,
            )

        params = self._extract_params(request)
        pid = params.get("id") or params.get("Id")
        slug = params.get("slug") or params.get("Slug")

        if not pid and not slug:
            return JsonResponse(
                {
                    "isSuccess": False,
                    "statusCode": 400,
                    "statusMessage": "درخواست نادرست",
                    "resultMessage": "حداقل یکی از پارامترهای جستجو باید ارسال شود.",
                    "error": {
                        "errorCode": 400,
                        "errorMessage": "حداقل یکی از پارامترهای جستجو باید ارسال شود.",
                    },
                    "errors": None,
                },
                status=400,
                json_dumps_params={"ensure_ascii": False},
            )

        item = get_single_snappay_product(pid or slug)
        if not item:
            return JsonResponse(
                {
                    "isSuccess": False,
                    "statusCode": 404,
                    "statusMessage": "یافت نشد",
                    "resultMessage": "محصولی با این مشخصات یافت نشد.",
                    "error": None,
                    "errors": None,
                },
                status=404,
                json_dumps_params={"ensure_ascii": False},
            )

        return JsonResponse(
            {
                "isSuccess": True,
                "statusCode": 200,
                "statusMessage": "موفق",
                "resultMessage": "اطلاعات با موفقیت یافت شد.",
                "result": item,
            },
            json_dumps_params={"ensure_ascii": False},
        )

    def get(self, request: HttpRequest):
        return self._handle(request)

    def post(self, request: HttpRequest):
        return self._handle(request)
