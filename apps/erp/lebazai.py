"""
Approved images from LEBAZAI, built into the local image store. Reads only:
mark_as_downloaded is never sent, because it would change LEBAZAI's state.
"""
from __future__ import annotations

import hashlib
import logging
import shutil

import requests
import urllib3
from django.conf import settings

from apps.website import images
from apps.website.services.lebazai_sync import sync_single_product_ai_profile

from .connector import Log, SourceError, get_connector
from .models import ErpProduct, LebazaiImage

logger = logging.getLogger(__name__)

LEBAZAI_TIMEOUT = 90
IMAGE_TIMEOUT = 60


def lebazai_images() -> dict[str, list[str]]:
    """{barcode: [url]} of approved images."""
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    reply = requests.get(f"{settings.LEBAZAI_API_URL}/get_images/", timeout=LEBAZAI_TIMEOUT, verify=False,
                         params={"brand": settings.LEBAZAI_IMAGE_BRAND, "format": "dict"},
                         headers={"X-API-Key": settings.LEBAZAI_API_KEY, "Accept": "application/json"})
    if reply.status_code != 200:
        raise SourceError(f"LEBAZAI: HTTP {reply.status_code} on get_images")
    try:
        data = reply.json()
    except ValueError as exc:
        raise SourceError("LEBAZAI: unreadable reply on get_images") from exc
    data = data.get(settings.LEBAZAI_IMAGE_BRAND.lower(), data) if isinstance(data, dict) else data
    if isinstance(data, list):
        return {code: urls for entry in data for code, urls in entry.items()}
    return data


def _key(url: str, prefix: str = "lz/") -> str:
    return prefix + hashlib.sha1(url.encode()).hexdigest()


# Original (unedited) photos for departments where the approved ones do not suit, e.g. socks. The
# nightly sync_images only removes lz/ keys, so these stay until they are removed by hand.
ORIGINAL_PREFIX = "lo/"


def lebazai_originals(*, department: str = "", subcodes: list[str] = (), kind: str = "all",
                      per_color: int | None = None) -> list[dict]:
    """The products of /original_images/ (format=grouped) for one department path ("a/b/c") or some subcodes."""
    params = {"brand": settings.LEBAZAI_IMAGE_BRAND, "format": "grouped", "kind": kind}
    if per_color:
        params["limit_per_sku"] = per_color
    if subcodes:
        params["subcode"] = ",".join(subcodes)
    for level, title in enumerate((p.strip() for p in department.split("/") if p.strip()), start=1):
        params[f"department{level}"] = title
    reply = requests.get(f"{settings.LEBAZAI_API_URL}/original_images/", params=params, timeout=LEBAZAI_TIMEOUT,
                         verify=getattr(settings, "LEBAZAI_VERIFY_TLS", True),
                         headers={"X-API-Key": settings.LEBAZAI_API_KEY, "Accept": "application/json"})
    if reply.status_code != 200:
        raise SourceError(f"LEBAZAI: HTTP {reply.status_code} on original_images")
    try:
        return reply.json().get("products") or []
    except (ValueError, AttributeError) as exc:
        raise SourceError("LEBAZAI: unreadable reply on original_images") from exc


def add_originals(*, departments: list[str], count: int, subcodes: list[str] = (), kind: str = "all",
                  per_color: int | None = None, with_photos: bool = False, dry_run: bool = False,
                  log: Log = logger.info) -> dict:
    """
    Gives `count` products of each department their original LEBAZAI photos (the subcodes are always among
    them, counted in the first department). Products with approved photos are left as they are unless
    with_photos; products that already got originals count, so a second run picks the same products.
    """
    variant_of: dict[str, tuple[int, int]] = {code: (pid, color) for code, pid, color in get_connector().barcodes()}
    held_back = {pid for pid in LebazaiImage.objects.exclude(key__startswith=ORIGINAL_PREFIX).values_list("product_id", flat=True)}

    def products_of(rows: list[dict]) -> dict[str, dict]:
        """subcode -> {"pid", "colors": {color_id: [url]}} for the rows that are on sale here."""
        found: dict[str, dict] = {}
        for row in rows:
            colors: dict[int, list[str]] = {}
            pid = None
            for sku in row.get("skus") or []:
                urls = [i["url"] for i in sku.get("images") or [] if i.get("url")]
                codes = [str(c).strip() for c in [sku.get("barcode"), *(sku.get("all_barcodes") or [])] if c]
                hit = next((variant_of[c] for c in codes if c in variant_of), None)
                if hit and urls:
                    pid = hit[0]
                    colors.setdefault(hit[1], []).extend(u for u in urls if u not in colors.get(hit[1], []))
            if pid is not None:
                found[str(row.get("subcode"))] = {"pid": pid, "colors": colors}
        return found

    chosen: dict[str, dict] = {}
    missing = []
    if subcodes:
        forced = products_of(lebazai_originals(subcodes=list(subcodes), kind=kind, per_color=per_color))
        missing = [s for s in subcodes if s not in forced]
        chosen.update(forced)
    for n, department in enumerate(departments):
        picked = 0 if n else len(chosen)
        for subcode, item in products_of(lebazai_originals(department=department, kind=kind, per_color=per_color)).items():
            if picked >= count:
                break
            if subcode in chosen or (item["pid"] in held_back and not with_photos):
                continue
            chosen[subcode] = item
            picked += 1
        log(f"{department}: {picked} products")

    built = failed = images_added = 0
    for subcode, item in chosen.items():
        for color_id, urls in item["colors"].items():
            for position, url in enumerate(urls):
                key = _key(url, ORIGINAL_PREFIX)
                if dry_run:
                    images_added += 1
                    continue
                if not images.is_built(key):
                    try:
                        reply = requests.get(url, timeout=IMAGE_TIMEOUT)
                        reply.raise_for_status()
                        images.build(key, reply.content)
                        built += 1
                    except (requests.RequestException, OSError, ValueError) as exc:
                        log(f"image {url}: {exc}")
                        failed += 1
                        continue
                LebazaiImage.objects.update_or_create(
                    product_id=item["pid"], color_id=color_id, key=key,
                    defaults={"source_url": url, "position": 100 + position})  # after the approved photos, if any
                images_added += 1
    log(f"originals: {len(chosen)} products, {images_added} images ({built} built, {failed} failed)"
        + (f", subcodes not on sale or without photos: {', '.join(missing)}" if missing else ""))
    return {"products": len(chosen), "images": images_added, "built": built, "failed": failed, "missing": missing}


def sync_images(log: Log = logger.info) -> dict:
    gallery = lebazai_images()
    if not gallery:
        raise SourceError("LEBAZAI: no images, kept what we have")
    wanted: dict[tuple[int, int, str], tuple[str, int]] = {}
    for barcode, product_id, color_id in get_connector().barcodes():
        for position, url in enumerate(gallery.get(barcode, [])):
            wanted.setdefault((product_id, color_id, _key(url)), (url, position))

    built = failed = 0
    keep = set()
    for (product_id, color_id, key), (url, position) in wanted.items():
        if not images.is_built(key):
            try:
                reply = requests.get(url, timeout=IMAGE_TIMEOUT)
                reply.raise_for_status()
                images.build(key, reply.content)
                built += 1
            except (requests.RequestException, OSError, ValueError) as exc:
                log(f"image {url}: {exc}")
                failed += 1
                continue
        keep.add((product_id, color_id, key))
        LebazaiImage.objects.update_or_create(product_id=product_id, color_id=color_id, key=key,
                                              defaults={"source_url": url, "position": position})
    removed = 0
    for image in LebazaiImage.objects.filter(key__startswith="lz/"):
        if (image.product_id, image.color_id, image.key) not in keep:
            image.delete()
            removed += 1
            if not LebazaiImage.objects.filter(key=image.key).exists():
                shutil.rmtree(images.img_root() / image.key, ignore_errors=True)
    log(f"images: {built} built, {failed} failed, {removed} removed")
    return {"built": built, "failed": failed, "removed": removed}


def sync_profiles(log: Log = logger.info) -> dict:
    """The AI copy of what is on sale, product by product: LEBAZAI's own checkpoint belongs to the other site."""
    saved = missing = 0
    for subcode in ErpProduct.objects.exclude(subcode="").values_list("subcode", flat=True):
        if sync_single_product_ai_profile(subcode).get("ok"):
            saved += 1
        else:
            missing += 1
    log(f"profiles: {saved} saved, {missing} without one")
    return {"saved": saved, "missing": missing}
