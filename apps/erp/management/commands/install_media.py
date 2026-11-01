"""
Management command: install the media pack in one go, instead of syncing file by file.

    python manage.py install_media https://example.com/media_pack.zip
    python manage.py install_media /app/public/media_pack.zip

Extracts into MEDIA_ROOT and loads the LEBAZAI image and AI rows the pack carries,
so run it after the products are imported.
A downloaded pack is deleted afterwards; one given as a path is left where it is.
"""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.erp.models import LebazaiImage
from apps.website.models import Product, ProductAIProfile

DATA = "dadehfa_data.json"
CHUNK = 1024 * 1024
AI_FIELDS = ("title", "seo_title", "description", "summary_bullets", "fab", "meta_description", "search_keywords", "stylist_note",
             "tags", "attributes")


class Command(BaseCommand):
    help = "نصب بستهٔ عکس و ویدیو از یک فایل زیپ"

    def add_arguments(self, parser):
        parser.add_argument("source", help="آدرس اینترنتی یا مسیر فایل زیپ")

    def handle(self, *args, **opts):
        root = Path(settings.MEDIA_ROOT)
        root.mkdir(parents=True, exist_ok=True)
        source = opts["source"]
        pack, downloaded = Path(source), False
        if source.startswith(("http://", "https://")):
            pack, downloaded = root / ".media_pack.zip", True
            self.download(source, pack)
        if not zipfile.is_zipfile(pack):
            raise CommandError(f"not a zip file: {pack}")

        with zipfile.ZipFile(pack) as archive:
            names = archive.namelist()
            for number, name in enumerate(names, 1):
                target = (root / name).resolve()
                if root.resolve() not in target.parents:
                    raise CommandError(f"unsafe path in the pack: {name}")
                if name.endswith("/"):
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as stream, target.open("wb") as out:
                    shutil.copyfileobj(stream, out, CHUNK)
                if number % 5000 == 0:
                    self.stdout.write(f"{number}/{len(names)}")
        if downloaded:
            pack.unlink()

        data = root / DATA
        if data.exists():
            self.load(data)
            data.unlink()
        self.stdout.write(f"installed {len(names)} files in {root}")

    def load(self, data: Path) -> None:
        rows = json.loads(data.read_text(encoding="utf8"))
        barcodes = dict(Product.objects.values_list("id", "barcode"))
        images, profiles = [], []
        for row in rows:
            fields = row["fields"]
            if row["model"] == "dadehfa.colorimage":
                images.append(LebazaiImage(product_id=fields["product"], color_id=fields["color_id"], key=fields["key"],
                                           source_url=fields["source_url"], position=fields["position"]))
            elif row["model"] == "dadehfa.aiprofile" and fields["product"] in barcodes:
                profiles.append((fields["product"], {name: fields[name] for name in AI_FIELDS}))
        with transaction.atomic():
            LebazaiImage.objects.all().delete()
            LebazaiImage.objects.bulk_create(images, batch_size=2000)
            for product_id, values in profiles:
                ProductAIProfile.objects.update_or_create(
                    product_id=product_id, defaults={**values, "subcode": barcodes[product_id]})
        self.stdout.write(f"{len(images)} images, {len(profiles)} AI profiles")

    def download(self, url: str, target: Path) -> None:
        with requests.get(url, stream=True, timeout=(30, 300)) as reply:
            if reply.status_code != 200:
                raise CommandError(f"download failed: HTTP {reply.status_code}")
            with target.open("wb") as out:
                for chunk in reply.iter_content(CHUNK):
                    out.write(chunk)
