"""
Sync product AI profiles from LEBAZAI (office.lebazacenter.com) to mong_samian.

Reads product copy, SEO metadata, FAB bullet points, stylist notes, and style tags
from the /api/product_profile/ endpoint and stores them in ProductAIProfile.
Supports incremental batch syncing via apl_key checkpoints.
"""
from __future__ import annotations

import logging
import urllib.parse
import time
from typing import Callable, Optional
import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.website.models import Product, ProductAIProfile, ProductTag, Tag

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "https://office.lebazacenter.com/api"
DEFAULT_API_KEY = "lebaza-ai-staging-test-key-2026"
DEFAULT_BRAND = "Mong"
DEFAULT_APL_KEY = "mong_website_app"


def get_lebazai_config() -> dict:
    return {
        "api_url": getattr(settings, "LEBAZAI_API_URL", DEFAULT_API_URL).rstrip("/"),
        "api_key": getattr(settings, "LEBAZAI_API_KEY", "") or DEFAULT_API_KEY,
        "brand": getattr(settings, "LEBAZAI_BRAND", DEFAULT_BRAND),
        "apl_key": getattr(settings, "LEBAZAI_APL_KEY", DEFAULT_APL_KEY),
    }


def _update_product_tags(product: Product, keywords: list[str]) -> None:
    """Link search keywords as ProductTags if not already present. On Dadehfa the tags are the software's own."""
    if not keywords or settings.ERP_CONNECTOR == "dadehfa":
        return
    existing_tags = set(
        ProductTag.objects.filter(product=product, is_deleted=False)
        .values_list("tag__title", flat=True)
    )
    for kw in keywords:
        kw_clean = str(kw).strip()
        if not kw_clean or kw_clean in existing_tags:
            continue
        tag, _ = Tag.objects.get_or_create(
            title=kw_clean,
            defaults={"created": timezone.now()},
        )
        ProductTag.objects.get_or_create(
            product=product,
            tag=tag,
            defaults={"created": timezone.now()},
        )
        existing_tags.add(kw_clean)


def _save_ai_profile_item(item: dict) -> tuple[Optional[ProductAIProfile], bool, str]:
    """
    Save or update one item returned from the LEBAZAI API into ProductAIProfile.
    Returns (profile_obj, is_created, status_message).
    """
    prod_data = item.get("product") or {}
    ai_data = item.get("ai_profile") or {}

    subcode = str(prod_data.get("subcode") or "").strip()
    if not subcode:
        return None, False, "فاقد کد فرعی (subcode)"

    # Match Product by barcode (which stores subcode in mong_samian)
    product = Product.objects.filter(barcode=subcode, is_deleted=False).first()
    if not product:
        # Check without is_deleted filter just in case
        product = Product.objects.filter(barcode=subcode).first()
    if not product:
        return None, False, f"محصول با بارکد/کد فرعی {subcode} در دیتابیس سایت یافت نشد"

    ai_updated_at = None
    if ai_data.get("updated_at"):
        try:
            ai_updated_at = parse_datetime(ai_data["updated_at"])
        except Exception:
            ai_updated_at = None

    profile, created = ProductAIProfile.objects.update_or_create(
        product=product,
        defaults={
            "subcode": subcode,
            "title": ai_data.get("title") or "",
            "seo_title": ai_data.get("seo_title") or "",
            "description": ai_data.get("description") or "",
            "summary_bullets": ai_data.get("summary_bullets") or [],
            "fab": ai_data.get("fab") or "",
            "meta_description": ai_data.get("meta_description") or "",
            "search_keywords": ai_data.get("search_keywords") or [],
            "stylist_note": ai_data.get("stylist_note") or "",
            "tags": ai_data.get("tags") or [],
            "attributes": ai_data.get("attributes") or {},
            "model_name": ai_data.get("model") or "",
            "prompt_version": ai_data.get("prompt_version") or "",
            "source": ai_data.get("source") or "ai",
            "ai_updated_at": ai_updated_at,
        },
    )

    # If product description is completely empty, populate it from AI description
    if not product.description and ai_data.get("description"):
        product.description = ai_data["description"]
        product.save(update_fields=["description"])

    # If product short_desc is empty, populate from meta_description
    if not product.short_desc and ai_data.get("meta_description"):
        product.short_desc = ai_data["meta_description"]
        product.save(update_fields=["short_desc"])

    # Sync search keywords to ProductTags
    keywords = ai_data.get("search_keywords") or []
    if keywords:
        _update_product_tags(product, keywords)

    return profile, created, "موفق"


def sync_product_ai_profiles(
    brand: Optional[str] = None,
    apl_key: Optional[str] = None,
    reset: bool = False,
    limit: int = 100,
    on_progress: Optional[Callable[[str], None]] = None,
) -> dict:
    """
    Sync AI profiles for all products of a brand incrementally.
    Uses the server-side checkpoint mechanism (apl_key).
    """
    cfg = get_lebazai_config()
    target_brand = brand or cfg["brand"]
    target_apl_key = apl_key or cfg["apl_key"]
    base_url = f"{cfg['api_url']}/product_profile/"
    headers = {
        "X-API-Key": cfg["api_key"],
        "Accept": "application/json",
    }

    log = on_progress or (lambda msg: logger.info(msg))
    log(f"شروع همگام‌سازی پروفایل‌های هوش مصنوعی برای برند «{target_brand}»...")

    total_created = 0
    total_updated = 0
    total_skipped = 0
    total_batches = 0
    current_offset = 0
    is_first_page = True

    while True:
        total_batches += 1
        params = {
            "brand": target_brand,
            "apl_key": target_apl_key,
            "limit": limit,
            "offset": current_offset,
        }
        if reset and is_first_page:
            params["reset"] = "true"

        try:
            resp = requests.get(base_url, headers=headers, params=params, timeout=45, verify=False)
            if resp.status_code != 200:
                err_msg = f"خطای پاسخ سرور لبازا: {resp.status_code} - {resp.text[:200]}"
                log(err_msg)
                return {
                    "ok": False,
                    "error": err_msg,
                    "batches": total_batches,
                    "created": total_created,
                    "updated": total_updated,
                    "skipped": total_skipped,
                }
            payload = resp.json()
        except Exception as exc:
            err_msg = f"خطا در ارتباط با سرور LEBAZAI: {exc}"
            log(err_msg)
            return {
                "ok": False,
                "error": err_msg,
                "batches": total_batches,
                "created": total_created,
                "updated": total_updated,
                "skipped": total_skipped,
            }

        items = payload.get("items") or []
        sync_info = payload.get("sync_info") or {}

        if not items:
            msg = payload.get("message") or "هیچ کالای جدید یا تغییریافته‌ای یافت نشد."
            log(f"  {msg}")
            break

        log(f"دریافت بچ {total_batches}: تعداد {len(items)} کالا از سرور هوش مصنوعی...")
        with transaction.atomic():
            for it in items:
                prof, created, status_desc = _save_ai_profile_item(it)
                if prof:
                    if created:
                        total_created += 1
                    else:
                        total_updated += 1
                else:
                    total_skipped += 1

        time.sleep(0.05)
        current_offset += len(items)
        is_first_page = False
        has_more = sync_info.get("has_more", False)
        if not has_more:
            break

    summary = {
        "ok": True,
        "batches": total_batches,
        "created": total_created,
        "updated": total_updated,
        "skipped": total_skipped,
        "total_processed": total_created + total_updated + total_skipped,
    }
    log(
        f"پایان همگام‌سازی هوش مصنوعی: {total_created} پروفایل جدید ایجاد شد، "
        f"{total_updated} پروفایل به‌روزرسانی شد، {total_skipped} کالا منطبق نشد."
    )
    try:
        from apps.storefront.snappay_crawler import invalidate_snappay_cache
        invalidate_snappay_cache()
    except Exception:
        pass

    return summary


def sync_single_product_ai_profile(subcode: str, brand: Optional[str] = None) -> dict:
    """Fetch and sync the AI profile of a single product by subcode/barcode."""
    cfg = get_lebazai_config()
    target_brand = brand or cfg["brand"]
    url = f"{cfg['api_url']}/product_profile/"
    headers = {
        "X-API-Key": cfg["api_key"],
        "Accept": "application/json",
    }
    params = {
        "subcode": subcode.strip(),
        "brand": target_brand,
    }

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=20, verify=False)
        if resp.status_code != 200:
            return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        data = resp.json()
        if data.get("status") != "success":
            return {"ok": False, "error": data.get("message", "پاسخ ناموفق")}
        profile, created, msg = _save_ai_profile_item(data)
        if not profile:
            return {"ok": False, "error": msg}
        return {"ok": True, "created": created, "profile_id": profile.id, "subcode": subcode}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
