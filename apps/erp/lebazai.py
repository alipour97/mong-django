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

from .connector import Log, SourceError
from .models import ErpVariant, LebazaiImage

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


def _key(url: str) -> str:
    return "lz/" + hashlib.sha1(url.encode()).hexdigest()


def sync_images(log: Log = logger.info) -> dict:
    gallery = lebazai_images()
    if not gallery:
        raise SourceError("LEBAZAI: no images, kept what we have")
    wanted: dict[tuple[int, int, str], tuple[str, int]] = {}
    variants = ErpVariant.objects.exclude(barcode="").exclude(color_id=None).values_list("barcode", "product_id", "color_id")
    for barcode, product_id, color_id in variants:
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
    for image in LebazaiImage.objects.all():
        if (image.product_id, image.color_id, image.key) not in keep:
            image.delete()
            removed += 1
            if not LebazaiImage.objects.filter(key=image.key).exists():
                shutil.rmtree(images.img_root() / image.key, ignore_errors=True)
    log(f"images: {built} built, {failed} failed, {removed} removed")
    return {"built": built, "failed": failed, "removed": removed}
