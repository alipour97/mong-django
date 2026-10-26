"""
Download product images from Samian ERP to local storage.

Reads filePath from SamianProductColor.colorsgalery and downloads
each image to media/products/<productmain_id>/<filename>.
Skips files already downloaded (by checking file existence and size).
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import requests
from django.conf import settings

from apps.samian.config import get_samian_settings
from apps.samian.models import SamianProductColor, SamianSyncLog

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _samian_file_base_url() -> str:
    cfg = get_samian_settings()
    base = cfg.base_url.rstrip("/")
    if base.endswith("/v2"):
        base = base[:-3]
    return base


def _local_image_path(productmain_id: int, file_path: str) -> Path:
    filename = Path(file_path).name
    return Path(settings.MEDIA_ROOT) / "products" / str(productmain_id) / filename


def download_images(
    *,
    max_colors: int | None = None,
    force: bool = False,
    stdout=None,
) -> dict[str, Any]:
    """
    Download all product gallery images from Samian to local media storage.
    Incremental: skips files that already exist with matching size.
    """
    base_url = _samian_file_base_url()
    session = requests.Session()
    session.headers["User-Agent"] = "MongSamianImageSync/1.0"

    qs = SamianProductColor.objects.filter(has_gallery=True).select_related("samian_product")
    if max_colors:
        qs = qs[:max_colors]

    total = downloaded = skipped = errors = 0
    t0 = time.time()

    for color in qs:
        gallery = color.colorsgalery or []
        pmid = color.productmain_id

        for item in gallery:
            if not isinstance(item, dict):
                continue
            file_path = item.get("filePath", "")
            if not file_path:
                continue

            ext = Path(file_path).suffix.lower()
            if ext not in IMAGE_EXTENSIONS:
                continue

            total += 1
            local_path = _local_image_path(pmid, file_path)
            remote_size = item.get("size", 0)

            if not force and local_path.exists():
                if remote_size and local_path.stat().st_size == remote_size:
                    skipped += 1
                    continue

            url = f"{base_url}/{file_path.lstrip('/')}"
            try:
                resp = session.get(url, timeout=15)
                if resp.status_code != 200:
                    errors += 1
                    logger.warning("HTTP %d for %s", resp.status_code, url)
                    continue

                local_path.parent.mkdir(parents=True, exist_ok=True)
                local_path.write_bytes(resp.content)
                downloaded += 1

            except Exception as exc:
                errors += 1
                logger.warning("Failed to download %s: %s", url, exc)

        if stdout and (downloaded + skipped) % 100 == 0 and (downloaded + skipped) > 0:
            stdout.write(f"  عکس: {downloaded} دانلود، {skipped} تکراری، {errors} خطا...")

    duration = round(time.time() - t0, 2)
    result = {
        "total_images": total,
        "downloaded": downloaded,
        "skipped_existing": skipped,
        "errors": errors,
        "duration_seconds": duration,
    }

    if downloaded > 0 or errors > 0:
        SamianSyncLog.objects.create(
            action=SamianSyncLog.Action.SYNC_COLORS,
            status=SamianSyncLog.Status.SUCCESS if errors == 0 else SamianSyncLog.Status.FAILED,
            records_read=total,
            records_upserted=downloaded,
            details=result,
        )

    return result


def local_image_url(productmain_id: int, file_path: str) -> str | None:
    """Return the local media URL for a downloaded image, or None if not downloaded."""
    local_path = _local_image_path(productmain_id, file_path)
    if local_path.exists():
        return f"/media/products/{productmain_id}/{local_path.name}"
    return None
