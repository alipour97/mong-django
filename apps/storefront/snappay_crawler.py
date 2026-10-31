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

import json
import math
import urllib.parse
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from apps.samian.models import SamianProduct
from apps.storefront import catalog
from apps.website.models import Product

# Official SearchWise / SnappPay crawler IPs from specification
SNAPPAY_DEFAULT_IPS = {
    "185.206.93.115",
    "185.206.94.25",
    "37.152.176.176",
    "188.121.106.231",
}

SNAPPAY_FEED_CACHE_KEY = "snappay:products:feed:v1"
SNAPPAY_FEED_CACHE_TTL = 300  # 5 minutes


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


def parse_description(p: Product, sp: SamianProduct | None = None) -> dict[str, str]:
    """
    Build structured key-value description object according to PDF specification.
    Extracts attributes from p.short_desc, SamianProduct, and p.description.
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

    # Add attributes from Samian ERP
    if sp:
        if sp.material and "جنس" not in desc_dict:
            desc_dict["جنس"] = sp.material.strip()
        if sp.style and "سبک" not in desc_dict:
            desc_dict["سبک"] = sp.style.strip()
        if sp.season and "فصل" not in desc_dict:
            desc_dict["فصل"] = str(sp.season).strip()

    # Add long description if present
    if p.description and p.description.strip():
        desc_dict["توضیحات تکمیلی"] = p.description.strip()

    return desc_dict


def build_snappay_product(
    p: Product,
    bundle: catalog.ProductBundle,
    tree: catalog.CategoryTree | None = None,
) -> dict[str, Any]:
    """
    Build single product dictionary matching the PDF fields:
    - id: Unique product ID (string)
    - title: Full product title
    - subtitle: English / subtitle
    - link: Full canonical website URL
    - image_link: Array of absolute image URLs (cover image first)
    - availability: "in stock" | "out of stock"
    - regular_price: Regular price in Rials (integer)
    - sale_price: Discounted sale price in Rials (integer)
    - category: Full category hierarchy (e.g. "مد و پوشاک > زنانه > روپوش > مانتو")
    - description: Key-value object
    - brand: Brand name ("مانگ")
    - GTIN: Barcode / GTIN
    - color: Available colors
    - size: Available sizes
    - shipping_cost: 0 (free shipping)
    - delivery_time: Shipping days
    """
    if tree is None:
        tree = catalog.category_tree()

    pr = bundle.pricing(p.id)
    sp = bundle.samian.get(p.id)
    imgs = bundle.main_images(p.id)
    in_stk = bundle.in_stock(p.id)

    # Category hierarchy
    cat_chain = ["مد و پوشاک"]
    if p.category_id:
        ancestors = tree.ancestors(p.category_id)
        for c in ancestors:
            if c.title != "مد و پوشاک":
                cat_chain.append(c.title)
    category_str = " > ".join(cat_chain)

    cat_title = p.category.title if p.category else ""
    title = format_title(p.title, cat_title, brand_title="مانگ")

    # Image links
    image_links = [img["mediaUrl"] for img in imgs if img.get("mediaUrl")]

    # Pricing in Rials (integers)
    regular_price = int(pr.base)
    sale_price = int(pr.after)
    if regular_price <= 0 and sale_price > 0:
        regular_price = sale_price
    elif regular_price < sale_price:
        regular_price = sale_price

    # Variants (colors & sizes)
    visible_variants = bundle.visible_variants(p.id)
    colors = list(dict.fromkeys(v.color.name for v in visible_variants if v.color and v.color.name))
    sizes = list(dict.fromkeys(v.size.name for v in visible_variants if v.size and v.size.name))

    base_url = settings.PUBLIC_BASE_URL.rstrip("/")
    link = f"{base_url}/products-item/{p.slug}"

    item: dict[str, Any] = {
        "id": str(p.id),
        "title": title,
        "subtitle": sp.name_en if sp and sp.name_en else "",
        "link": link,
        "image_link": image_links,
        "availability": "in stock" if in_stk else "out of stock",
        "regular_price": regular_price,
        "sale_price": sale_price,
        "category": category_str,
        "description": parse_description(p, sp),
        "brand": "مانگ",
        "GTIN": p.barcode or (sp.subcode if sp else "") or "",
        "gtin": p.barcode or (sp.subcode if sp else "") or "",
    }

    if colors:
        item["color"] = ", ".join(colors)
    if sizes:
        item["size"] = ", ".join(sizes)

    item["shipping_cost"] = 0
    item["delivery_time"] = p.shipping_time or 3

    return item


def get_all_snappay_products() -> list[dict[str, Any]]:
    """Fetch and serialize all live products with caching."""
    cached = cache.get(SNAPPAY_FEED_CACHE_KEY)
    if cached is not None:
        return cached

    rows = catalog.listing_rows()
    ids = [r.id for r in rows]
    bundle = catalog.ProductBundle.load(ids)
    tree = catalog.category_tree()

    products_data: list[dict[str, Any]] = []
    for r in rows:
        p = bundle.products.get(r.id)
        if not p:
            continue
        item = build_snappay_product(p, bundle, tree)
        products_data.append(item)

    cache.set(SNAPPAY_FEED_CACHE_KEY, products_data, SNAPPAY_FEED_CACHE_TTL)
    return products_data


def get_single_snappay_product(identifier: int | str) -> dict[str, Any] | None:
    """Find a single product by ID or Slug."""
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

    return build_snappay_product(p, bundle)


def to_xml(products: list[dict[str, Any]]) -> str:
    """Convert product list to standard XML feed."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<products>"]
    for p in products:
        lines.append("  <product>")
        lines.append(f"    <id>{p['id']}</id>")
        lines.append(f"    <title><![CDATA[{p['title']}]]></title>")
        lines.append(f"    <subtitle><![CDATA[{p.get('subtitle', '')}]]></subtitle>")
        lines.append(f"    <link>{p['link']}</link>")
        lines.append("    <image_link>")
        for img in p.get("image_link", []):
            lines.append(f"      <image>{img}</image>")
        lines.append("    </image_link>")
        lines.append(f"    <availability>{p['availability']}</availability>")
        lines.append(f"    <regular_price>{p['regular_price']}</regular_price>")
        lines.append(f"    <sale_price>{p['sale_price']}</sale_price>")
        lines.append(f"    <category><![CDATA[{p['category']}]]></category>")
        lines.append("    <description>")
        for k, v in p.get("description", {}).items():
            lines.append(f"      <{k}><![CDATA[{v}]]></{k}>")
        lines.append("    </description>")
        lines.append(f"    <brand><![CDATA[{p['brand']}]]></brand>")
        lines.append(f"    <GTIN>{p.get('GTIN', '')}</GTIN>")
        if "color" in p:
            lines.append(f"    <color><![CDATA[{p['color']}]]></color>")
        if "size" in p:
            lines.append(f"    <size><![CDATA[{p['size']}]]></size>")
        lines.append(f"    <shipping_cost>{p.get('shipping_cost', 0)}</shipping_cost>")
        lines.append(f"    <delivery_time>{p.get('delivery_time', 3)}</delivery_time>")
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
    """

    def get(self, request: HttpRequest, *args, **kwargs):
        if not is_snappay_authorized(request):
            return JsonResponse({"error": "Forbidden: IP not allowed"}, status=403)

        feed_format = request.GET.get("format", "").lower()
        if kwargs.get("format") == "xml" or feed_format == "xml":
            products = get_all_snappay_products()
            return HttpResponse(to_xml(products), content_type="application/xml; charset=utf-8")

        products = get_all_snappay_products()
        return JsonResponse(products, safe=False, json_dumps_params={"ensure_ascii": False})


@method_decorator(csrf_exempt, name="dispatch")
class SnappPayProductsView(View):
    """
    Method 3: Product API with pagination and single product query.
    GET /api/snappay/products?page=1&size=50
    GET /api/snappay/products?id=139
    GET /api/snappay/products?slug=تورین-3
    """

    def get(self, request: HttpRequest, *args, **kwargs):
        if not is_snappay_authorized(request):
            return JsonResponse({"error": "Forbidden: IP not allowed"}, status=403)

        # 1. Single product lookup via query parameter
        pid = request.GET.get("id")
        slug = request.GET.get("slug")
        if pid or slug:
            item = get_single_snappay_product(pid or slug)
            if not item:
                return JsonResponse({"error": "Product not found"}, status=404)
            return JsonResponse(item, json_dumps_params={"ensure_ascii": False})

        # 2. Paginated list
        all_products = get_all_snappay_products()
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
        all_products = get_all_snappay_products()
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
