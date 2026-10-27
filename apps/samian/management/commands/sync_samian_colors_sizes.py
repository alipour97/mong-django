"""
Management command: Samian's color table and the sizes used on Mong barcodes (read only).

    product/colorinfo        -> SamianColor (name, display name, hex swatch)
    SamianBarcode.size       -> SamianSize  (one row per size; new sizes get a
                                default order, edited orders are kept)

Run after the barcode sync.
"""
from __future__ import annotations

import re

from django.core.management.base import BaseCommand

from apps.samian.client import get_samian_client
from apps.samian.models import SamianBarcode, SamianColor, SamianSize

LETTER_SIZES = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL", "3XL", "4XL", "5XL"]


def default_priority(size: str) -> int:
    """Numbers first in numeric order, then XS..5XL, then everything else."""
    text = size.strip().upper()
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return int(float(text) * 10)
    if text in LETTER_SIZES:
        return 10_000 + LETTER_SIZES.index(text)
    return 20_000


class Command(BaseCommand):
    help = "سینک جدول رنگ سامیان و سایزهای بارکدها"

    def handle(self, *args, **options):
        client = get_samian_client()
        colors = [
            SamianColor(
                samian_id=int(item["colorinfo_id"]),
                title=(item.get("colorinfotitle") or "").strip(),
                panel_title=(item.get("panelinfotitle") or "").strip(),
                english_title=(item.get("englishtitle") or "").strip(),
                hex_code=(item.get("colorhexcode") or "").strip().lstrip("#").upper(),
                color_code=str(item.get("colorcode") or "").strip(),
            )
            for item in client.iter_keyset("product/colorinfo", key="colorinfo_id", take_count=1000)
            if item.get("colorinfo_id")
        ]
        SamianColor.objects.bulk_create(
            colors, update_conflicts=True, unique_fields=["samian_id"],
            update_fields=["title", "panel_title", "english_title", "hex_code", "color_code", "updated_at"],
        )
        known = set(SamianSize.objects.values_list("name", flat=True))
        used = set(SamianBarcode.objects.exclude(size="").values_list("size", flat=True).distinct())
        new = [SamianSize(name=s, display_priority=default_priority(s)) for s in sorted(used - known)]
        SamianSize.objects.bulk_create(new)
        self.stdout.write(self.style.SUCCESS(f"{len(colors)} رنگ، {len(new)} سایز جدید (کل {len(known) + len(new)})"))
