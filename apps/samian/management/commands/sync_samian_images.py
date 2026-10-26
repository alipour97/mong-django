"""
Download product gallery images from Samian ERP to local storage.

Usage:
    python manage.py sync_samian_images                  # incremental (skip existing)
    python manage.py sync_samian_images --force           # re-download all
    python manage.py sync_samian_images --max-colors 50   # limit for testing
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.samian.services.image_download import download_images


class Command(BaseCommand):
    help = "دانلود عکس‌های محصولات از سامیان به storage محلی"

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-colors",
            type=int,
            default=None,
            help="حداکثر تعداد رکوردهای رنگ برای پردازش",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            default=False,
            help="دانلود مجدد حتی اگر فایل موجود باشد",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("شروع دانلود عکس‌های محصولات از سامیان..."))

        result = download_images(
            max_colors=options["max_colors"],
            force=options["force"],
            stdout=self.stdout,
        )

        self.stdout.write(self.style.SUCCESS(
            f"\nدانلود عکس‌ها تمام شد:"
            f"\n  کل عکس‌ها: {result['total_images']}"
            f"\n  دانلود شده: {result['downloaded']}"
            f"\n  تکراری (skip): {result['skipped_existing']}"
            f"\n  خطا: {result['errors']}"
            f"\n  مدت زمان: {result['duration_seconds']:.1f} ثانیه"
        ))
