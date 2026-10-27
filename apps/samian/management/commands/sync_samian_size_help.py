"""
Management command: read each Mong product's size chart (onlinestoresizehelp) from Samian.

The list endpoint does not return the field but can filter on it, so the
products that have one are found in one pass and only those are read one by
one (product/productmain/{id}). Paths go to SamianProduct.size_help_path;
build_images makes the WebP versions. Read only.

    python manage.py sync_samian_size_help
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.samian.client import brand_filter, extract_records, get_samian_client
from apps.samian.models import SamianProduct


class Command(BaseCommand):
    help = "سینک جدول سایز کالاها از سامیان"

    def handle(self, *args, **options):
        client = get_samian_client()
        has_help = [["onlinestoresizehelp", "!=", ""]]
        brands = brand_filter()
        filters = [brands, "and", has_help] if brands else has_help
        ids = [int(i["productmain_id"]) for i in client.iter_keyset(
            "product/productmain", key="productmain_id", take_count=5000, filters=filters)]

        paths: dict[int, str] = {}
        for pid in ids:
            records = extract_records(client.manual_request(f"product/productmain/{pid}"))
            path = (records[0].get("__onlinestoresizehelp_link") or "").strip() if records else ""
            if path:
                paths[pid] = path

        changed = 0
        for sp in SamianProduct.objects.filter(samian_id__in=paths):
            if sp.size_help_path != paths[sp.samian_id]:
                sp.size_help_path = paths[sp.samian_id]
                sp.save(update_fields=["size_help_path"])
                changed += 1
        cleared = SamianProduct.objects.exclude(samian_id__in=paths).exclude(size_help_path="").update(size_help_path="")
        self.stdout.write(self.style.SUCCESS(f"{len(paths)} کالا جدول سایز دارد ({changed} تغییر، {cleared} حذف)"))
