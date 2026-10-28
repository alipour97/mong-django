"""
Turn our own absolute URLs stored in the database into relative paths.

    python manage.py strip_hardcoded_domains [--dry-run]

https://<one of settings.OWN_HOSTS>/media/x.webp -> /media/x.webp, in every field
that keeps a media URL (and inside PrimaryConfig JSON). Other hosts (cdn.mong.ir,
page links to mong.ir) are left as they are. Safe to run again.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.website import images
from apps.website.models import (
    Article, Banner, CustomTheme, FileMedia, MediaAttachment, Page, PrimaryConfig, ShippingMethod, Theme,
)

URL_FIELDS = [
    (FileMedia, "url"), (MediaAttachment, "media_url"), (Banner, "media_url"), (Article, "thumbnail"),
    (ShippingMethod, "icon"), (Page, "image_url"),
    (Theme, "mobile_image"), (Theme, "header_image"), (Theme, "desktop_image"),
    (CustomTheme, "mobile_image"), (CustomTheme, "header_image"), (CustomTheme, "desktop_image"),
]
TEXT_FIELDS = [(PrimaryConfig, "value")]


class Command(BaseCommand):
    help = "آدرس‌های کامل دامنه‌ی خودمان را در دیتابیس به مسیر نسبی تبدیل می‌کند"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="فقط شمارش، بدون ذخیره")

    def handle(self, *args, dry_run=False, **options):
        total = 0
        with transaction.atomic():
            for model, field, fix in [(m, f, images.strip_domain) for m, f in URL_FIELDS] + \
                                     [(m, f, images.strip_domains_in_text) for m, f in TEXT_FIELDS]:
                changed = []
                for pk, value in model.objects.filter(**{f"{field}__icontains": "://"}).values_list("pk", field):
                    new = fix(value)
                    if new != value:
                        changed.append((pk, new))
                if changed and not dry_run:
                    for pk, new in changed:
                        model.objects.filter(pk=pk).update(**{field: new})
                if changed:
                    self.stdout.write(f"  {model.__name__}.{field}: {len(changed)}")
                total += len(changed)
        self.stdout.write(self.style.SUCCESS(f"{'(dry run) ' if dry_run else ''}{total} مقدار نسبی شد"))
