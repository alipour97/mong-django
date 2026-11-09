"""
SnappPay search feed in the shape of SearchWise's WooCommerce plugin (v1.0.2).

SnappPay's product search reads shops through that plugin: POST /wp-json/v1/product/feed with an
`x-api-key` header, and the parameters limit/page, products (ids, comma-separated), slugs
(comma-separated) and include_content. This view answers the same request with the same JSON,
built from the site's own tables (snappay_crawler.build_snappay_product), never from the ERP.

The front end serves the same address on the shop's own host (front/src/app/wp-json/...) and
passes the request here.

The key: the feed is open unless SNAPPAY_FEED_REQUIRE_KEY=true. Then, when SNAPPAY_FEED_API_KEY is set, the header must equal it. Otherwise the key is checked
the way the plugin checks it, with SearchWise's server (merchant domain + key); a good answer is
kept for an hour so a full crawl asks once.
"""
from __future__ import annotations

import hmac
import json
import logging
import math
import urllib.parse
import urllib.request
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from apps.storefront import catalog
from apps.storefront.snappay_crawler import build_snappay_product, get_all_snappay_products, get_base_url
from apps.website import slugs
from apps.website.models import Product, ProductAIProfile, ProductSlugAlias

log = logging.getLogger(__name__)

PLUGIN_VERSION = "1.0.2"
VALIDATE_URL = "https://merchants.searchwise.ir/api/v1/feed/validate-token"
MAX_LIMIT = 500


def merchant_domain() -> str:
    return getattr(settings, "SNAPPAY_MERCHANT_DOMAIN", "") or urllib.parse.urlsplit(get_base_url()).hostname or ""


def _remote_check(api_key: str) -> bool | None:
    """SearchWise's own check. True/False, or None when their server can't be reached."""
    key = "searchwise:key:" + hmac.new(b"searchwise", api_key.encode(), "sha256").hexdigest()
    known = cache.get(key)
    if known is not None:
        return known
    body = urllib.parse.urlencode({
        "merchant_domain": merchant_domain(), "api_key": api_key, "plugin_version": PLUGIN_VERSION,
    }).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(VALIDATE_URL, data=body, method="POST"), timeout=5) as r:
            ok = json.loads(r.read().decode() or "{}").get("success") is True
    except Exception as exc:  # network, bad JSON
        log.warning("searchwise key check failed: %s", exc)
        return None
    cache.set(key, ok, 3600 if ok else 60)
    return ok


def check_key(request: HttpRequest) -> JsonResponse | None:
    """None when the caller may read the feed, else the plugin's own error answer."""
    if not getattr(settings, "SNAPPAY_FEED_REQUIRE_KEY", False):
        return None  # open feed: the same public product data the shop shows
    api_key = (request.headers.get("x-api-key") or request.headers.get("x_api_key") or "").strip()
    expected = getattr(settings, "SNAPPAY_FEED_API_KEY", "")
    if expected:
        ok = bool(api_key) and hmac.compare_digest(api_key, expected)
    elif not api_key:
        ok = False
    else:
        ok = _remote_check(api_key)
        if ok is None:
            return JsonResponse({"code": "error", "message": "Authentication server could not be reached.",
                                 "data": {"status": 503}}, status=503)
    if ok:
        return None
    return JsonResponse({"code": "rest_forbidden", "message": "Invalid API Key.", "data": {"status": 401}}, status=401)


def _params(request: HttpRequest) -> dict[str, Any]:
    """WordPress merges query, form and JSON body parameters; so does this."""
    params: dict[str, Any] = {k: v for k, v in request.GET.items()}
    if "json" not in (request.content_type or ""):
        params.update({k: v for k, v in request.POST.items()})
    elif request.body:
        try:
            data = json.loads(request.body)
            if isinstance(data, dict):
                params.update(data)
        except ValueError:
            pass
    return params


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        items = value
    else:
        items = str(value or "").split(",")
    return [str(x).strip() for x in items if str(x).strip()]


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def plugin_item(item: dict[str, Any], p: Product, include_content: bool) -> dict[str, Any]:
    """One product in the plugin's fields, from the SnappPay feed item."""
    category = [c.strip() for c in item["category"].split(">") if c.strip() and c.strip() != "مد و پوشاک"]
    out: dict[str, Any] = {
        "id": p.id,
        "slug": p.slug,
        "title": item["title"],
        "subtitle": item.get("subtitle", ""),
    }
    if include_content:
        out["content"] = p.description or ""
    out.update({
        "regular_price": item["regular_price"],
        "sale_price": item["sale_price"],
        "availability": "instock" if item["availability"] == "in stock" else "outofstock",
        "category": category,
        "image_link": item["image_link"],
        "link": item["link"],
        "short_description": item.get("meta_description", "") or "",
        "description": item["description"],
        "shipping_cost": item["shipping_cost"],
        "delivery_time": item["delivery_time"],
        "brand": item["brand"],
        "GTIN": item.get("GTIN", ""),
    })
    if item.get("color"):
        out["color"] = item["color"]
    if item.get("size"):
        out["size"] = item["size"]
    return out


def _build(products: list[Product], include_content: bool) -> list[dict[str, Any]]:
    """Live lookup for a few products (the ones SnappPay refreshes more often)."""
    listed = {r.id for r in catalog.listing_rows()}
    products = [p for p in products if p.id in listed]  # only what the shop itself shows
    if not products:
        return []
    ids = [p.id for p in products]
    bundle = catalog.ProductBundle.load(ids)
    tree = catalog.category_tree()
    ai = ProductAIProfile.objects.filter(product_id__in=ids).in_bulk(field_name="product_id")
    base_url = get_base_url()
    out = []
    for p in products:
        bp = bundle.products.get(p.id)
        if bp:
            out.append(plugin_item(build_snappay_product(bp, bundle, tree, ai=ai.get(p.id), base_url=base_url),
                                   bp, include_content))
    return out


def _by_ids(raw: list[str], include_content: bool) -> list[dict[str, Any]]:
    ids = [int(x) for x in raw if x.isdigit()]
    found = Product.objects.filter(id__in=ids, is_active=True, is_deleted=False).in_bulk()
    return _build([found[i] for i in dict.fromkeys(ids) if i in found], include_content)


def _by_slugs(raw: list[str], include_content: bool) -> list[dict[str, Any]]:
    products: list[Product] = []
    for s in raw:
        key = slugs.slug_key(urllib.parse.unquote(s))
        p = Product.objects.filter(slug_key=key, is_active=True, is_deleted=False).order_by("id").first()
        if not p:
            alias = ProductSlugAlias.objects.filter(slug_key=key).select_related("product").first()
            p = alias.product if alias and alias.product.is_active and not alias.product.is_deleted else None
        if p and p not in products:
            products.append(p)
    return _build(products, include_content)


@method_decorator(csrf_exempt, name="dispatch")
class SearchwiseFeedView(View):
    """POST (or GET) /wp-json/v1/product/feed — the SearchWise plugin's API."""

    def post(self, request: HttpRequest, *args, **kwargs):
        denied = check_key(request)
        if denied:
            return denied
        params = _params(request)
        include_content = _truthy(params.get("include_content", ""))
        ids, slug_list = _list(params.get("products")), _list(params.get("slugs"))

        if ids:
            data: dict[str, Any] = {"products": _by_ids(ids, include_content)}
        elif slug_list:
            data = {"products": _by_slugs(slug_list, include_content)}
        else:
            limit = max(1, min(MAX_LIMIT, _int(params.get("limit") or params.get("size"), 100)))
            page = max(1, _int(params.get("page"), 1))
            # Newest first, like the plugin (ORDER BY ID DESC), so pages stay stable.
            feed = sorted(get_all_snappay_products(), key=lambda x: int(x["id"]), reverse=True)
            chunk = feed[(page - 1) * limit: page * limit]
            products = Product.objects.in_bulk([int(x["id"]) for x in chunk])
            data = {
                "count": len(feed),
                "max_pages": math.ceil(len(feed) / limit),
                "products": [plugin_item(x, products[int(x["id"])], include_content)
                             for x in chunk if int(x["id"]) in products],
            }
        data.update({"plugin_version": PLUGIN_VERSION, "wc_version": "not_installed", "wp_version": "not_installed"})
        return JsonResponse(data, json_dumps_params={"ensure_ascii": False})

    get = post
