"""
Management command: the media pack, so a new server starts from a file instead of a long sync.

    python manage.py export_media
    python manage.py export_media --output /some/where/media_pack.zip

Puts in one zip the images under MEDIA_ROOT (img/ and cdn/, nothing a customer sent), every LebazaiImage
row and the AI profiles. install_media installs it; after that sync_lebazai_images only fetches what is new.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from apps.erp.models import LebazaiImage
from apps.website import images
from apps.website.models import ProductAIProfile

from .install_media import AI_FIELDS, DATA

FOLDERS = ("img", "cdn")
DEFAULT_OUTPUT = Path(settings.BASE_DIR) / "dist" / "runflare" / "media_pack.zip"


class Command(BaseCommand):
    help = "ساخت بستهٔ عکس‌ها و پروفایل‌ها در یک فایل زیپ"

    def add_arguments(self, parser):
        parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="مسیر فایل زیپ")

    def handle(self, *args, **opts):
        rows = self.rows()
        missing = sum(not images.is_built(row["fields"]["key"]) for row in rows if row["model"] == "dadehfa.colorimage")
        if missing:
            raise CommandError(f"{missing} photos are not built, run sync_lebazai_images first")
        root = Path(settings.MEDIA_ROOT)
        output = Path(opts["output"])
        output.parent.mkdir(parents=True, exist_ok=True)
        partial = output.with_suffix(".tmp")
        files = 0
        # The images are compressed already: stored as they are, the pack builds in minutes.
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_STORED, allowZip64=True) as archive:
            archive.writestr(DATA, json.dumps(rows, ensure_ascii=False, cls=DjangoJSONEncoder), zipfile.ZIP_DEFLATED)
            for folder in FOLDERS:
                for path in sorted((root / folder).rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(root))
                        files += 1
                        if files % 20000 == 0:
                            self.stdout.write(f"{files} files")
        partial.replace(output)
        self.stdout.write(f"{output}: {files} files, {len(rows)} rows, {output.stat().st_size / 1e9:.2f} GB")

    def rows(self) -> list[dict]:
        rows = [
            {"model": "dadehfa.colorimage", "fields": {"product": i.product_id, "color_id": i.color_id, "key": i.key,
                                                       "source_url": i.source_url, "position": i.position}}
            for i in LebazaiImage.objects.all()
        ]
        rows += [
            {"model": "dadehfa.aiprofile", "fields": {"product": p.product_id, **{name: getattr(p, name) for name in AI_FIELDS}}}
            for p in ProductAIProfile.objects.all()
        ]
        return rows
