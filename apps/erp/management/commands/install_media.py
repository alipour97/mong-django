"""
Management command: install the media pack in one go, instead of syncing file by file.

    python manage.py install_media https://example.com/media_pack.zip
    python manage.py install_media /app/public/media_pack.zip

Extracts into MEDIA_ROOT and loads the LEBAZAI image and AI rows the pack carries,
so run it after the products are imported. Safe to run again: a file already there
with the same size is skipped, and photos uploaded in the admin (up/) stay.
A downloaded pack is deleted afterwards; one given as a path is left where it is.
The pack is made by export_media.
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
from django.db.models import Q

from apps.erp.models import LebazaiImage
from apps.storefront import catalog
from apps.website.models import Product, ProductAIProfile
from apps.website.services.lebazai_sync import fill_product

DATA = "dadehfa_data.json"
CHUNK = 1024 * 1024
AI_FIELDS = ("title", "seo_title", "description", "summary_bullets", "fab", "meta_description", "search_keywords", "stylist_note",
             "tags", "attributes", "model_name", "prompt_version", "source", "ai_updated_at")


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
            names = archive.infolist()
            skipped = 0
            for number, entry in enumerate(names, 1):
                target = (root / entry.filename).resolve()
                if root.resolve() not in target.parents:
                    raise CommandError(f"unsafe path in the pack: {entry.filename}")
                if number % 5000 == 0:
                    self.stdout.write(f"{number}/{len(names)}")
                if entry.is_dir():
                    continue
                if target.exists() and target.stat().st_size == entry.file_size:
                    skipped += 1
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as stream, target.open("wb") as out:
                    shutil.copyfileobj(stream, out, CHUNK)
        if downloaded:
            pack.unlink()

        data = root / DATA
        if data.exists():
            self.load(data)
            data.unlink()
        self.stdout.write(f"installed {len(names)} files in {root}, {skipped} were already there")

    def load(self, data: Path) -> None:
        rows = json.loads(data.read_text(encoding="utf8"))
        products = Product.objects.in_bulk()
        images, profiles = [], []
        for row in rows:
            fields = row["fields"]
            if row["model"] == "dadehfa.colorimage":
                images.append(LebazaiImage(product_id=fields["product"], color_id=fields["color_id"], key=fields["key"],
                                           source_url=fields["source_url"], position=fields["position"]))
            elif row["model"] == "dadehfa.aiprofile" and fields["product"] in products:
                profiles.append((fields["product"], {name: fields[name] for name in AI_FIELDS}))
        with transaction.atomic():
            LebazaiImage.objects.filter(Q(key__startswith="lz/") | Q(key__startswith="lo/")).delete()
            LebazaiImage.objects.bulk_create(images, batch_size=2000, ignore_conflicts=True)
            for product_id, values in profiles:
                product = products[product_id]
                ProductAIProfile.objects.update_or_create(product=product, defaults={**values, "subcode": product.barcode})
                fill_product(product, values)
        catalog.clear_caches()
        self.stdout.write(f"{len(images)} images, {len(profiles)} AI profiles")

    def download(self, url: str, target: Path) -> None:
        with requests.get(url, stream=True, timeout=(30, 300)) as reply:
            if reply.status_code != 200:
                raise CommandError(f"download failed: HTTP {reply.status_code}")
            with target.open("wb") as out:
                for chunk in reply.iter_content(CHUNK):
                    out.write(chunk)
