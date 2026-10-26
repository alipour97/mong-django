"""
Management command: build compressed WebP images (nightly).

Collects every image the site shows (Samian color galleries of synced
products, and legacy site media: product/color/category/collection media,
banners, company logo, images inside PrimaryConfig values), and builds the
ones not built yet into MEDIA_ROOT/img (see apps/website/images.py).

    python manage.py build_images              # new images only
    python manage.py build_images --workers 8
    python manage.py build_images --prune      # also delete images no longer used
"""
from __future__ import annotations

import shutil
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import requests
from django.core.management.base import BaseCommand

from apps.samian.config import get_samian_settings
from apps.samian.models import SamianProductColor
from apps.website import images
from apps.website.models import Banner, MediaAttachment, PrimaryConfig


def _samian_base() -> str:
    base = get_samian_settings().base_url.rstrip("/")
    return base[:-3] if base.endswith("/v2") else base


def collect_jobs() -> dict[str, tuple[str, str]]:
    """key -> (kind, source) where kind is "samian" (URL) or "legacy" (cdn.mong.ir URL)."""
    jobs: dict[str, tuple[str, str]] = {}
    base = _samian_base()
    for color in SamianProductColor.objects.filter(has_gallery=True).only("productmain_id", "colorsgalery"):
        for item in color.colorsgalery or []:
            fp = item.get("filePath", "") if isinstance(item, dict) else ""
            if fp and Path(fp).suffix.lower() in images.IMAGE_EXT:
                jobs[images.samian_key(color.productmain_id, fp)] = ("samian", f"{base}/{fp.lstrip('/')}")

    urls = set(MediaAttachment.objects.filter(is_deleted=False).values_list("media_url", flat=True))
    urls |= set(Banner.objects.filter(is_deleted=False).values_list("media_url", flat=True))
    for value in PrimaryConfig.objects.filter(is_deleted=False).values_list("value", flat=True):
        urls |= {m.group(0) for m in images.LEGACY_CDN.finditer(value or "")}
    for url in urls:
        key = images.legacy_key(url)
        if key:
            jobs[key] = ("legacy", url)
    return jobs


def _run(job: tuple[str, str, str]) -> tuple[str, str, int]:
    key, kind, source = job
    try:
        if kind == "legacy":
            local = images.legacy_local_path(source)
            if local and local.exists():
                data = local.read_bytes()
            else:
                resp = requests.get(source, timeout=30)
                resp.raise_for_status()
                data = resp.content
        else:
            resp = requests.get(source, timeout=30)
            resp.raise_for_status()
            data = resp.content
        return key, "ok", images.build(key, data)
    except Exception as exc:  # keep going; report at the end
        return key, f"error: {type(exc).__name__}: {str(exc)[:120]}", 0


class Command(BaseCommand):
    help = "ساخت نسخه‌های فشرده‌ی WebP عکس‌ها (اجرای شبانه)"

    def add_arguments(self, parser):
        parser.add_argument("--workers", type=int, default=12)
        parser.add_argument("--force", action="store_true", help="ساخت دوباره‌ی همه")
        parser.add_argument("--prune", action="store_true", help="حذف عکس‌هایی که دیگر استفاده نمی‌شوند")
        parser.add_argument("--limit", type=int, default=None)

    def handle(self, *args, **opts):
        t0 = time.time()
        jobs = collect_jobs()
        todo = [(k, *v) for k, v in jobs.items() if opts["force"] or not images.is_built(k)]
        if opts["limit"]:
            todo = todo[: opts["limit"]]
        self.stdout.write(f"عکس‌های مورد استفاده: {len(jobs)} — برای ساخت: {len(todo)}")

        ok = errors = written = 0
        failed = []
        with ProcessPoolExecutor(max_workers=opts["workers"]) as pool:
            for i, fut in enumerate(as_completed(pool.submit(_run, j) for j in todo), start=1):
                key, status, size = fut.result()
                if status == "ok":
                    ok += 1
                    written += size
                else:
                    errors += 1
                    failed.append((key, status))
                if i % 1000 == 0:
                    self.stdout.write(f"  {i}/{len(todo)} ...")

        pruned = 0
        if opts["prune"]:
            root = images.img_root()
            for full in root.glob("**/full.webp"):
                key = str(full.parent.relative_to(root))
                if key not in jobs:
                    shutil.rmtree(full.parent)
                    pruned += 1

        self.stdout.write(self.style.SUCCESS(
            f"ساخته شد: {ok}، خطا: {errors}، حذف: {pruned}، حجم نوشته‌شده: {written / 1e6:.1f} MB، "
            f"زمان: {time.time() - t0:.0f} ثانیه"
        ))
        for key, status in failed[:20]:
            self.stdout.write(self.style.WARNING(f"  {key}: {status}"))
