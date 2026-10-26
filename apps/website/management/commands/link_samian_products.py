"""
Management command: link website products to Samian products.

A website product's code (Product.barcode, the legacy PTC product code) is
compared with Samian's productmain code (k_bar_code, stored as
SamianProduct.subcode). Only exact matches are linked automatically; manual
links are never overwritten. Everything that could not be linked is listed.
"""
from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.samian.models import SamianProduct
from apps.website.models import Product, ProductSamianLink


class Command(BaseCommand):
    help = "اتصال محصولات سایت به محصولات سامیان بر اساس کد کالا"

    def add_arguments(self, parser):
        parser.add_argument("--show-unmatched", type=int, default=20, help="تعداد نمونه‌های بدون تطابق برای نمایش")

    def handle(self, *args, **options):
        by_code = defaultdict(list)
        for pid, code in Product.objects.filter(is_deleted=False).exclude(barcode="").values_list("id", "barcode"):
            by_code[code.strip()].append(pid)

        manual = set(
            ProductSamianLink.objects.filter(method=ProductSamianLink.Method.MANUAL).values_list("product_id", flat=True)
        )
        linked, ambiguous, unmatched = 0, [], []

        with transaction.atomic():
            ProductSamianLink.objects.filter(method=ProductSamianLink.Method.EXACT_CODE).delete()
            links = []
            seen_product_ids: set[int] = set()
            for sp in SamianProduct.objects.all().only("samian_id", "subcode", "name"):
                candidates = [pid for pid in by_code.get((sp.subcode or "").strip(), []) if pid not in manual and pid not in seen_product_ids]
                if len(candidates) == 1:
                    links.append(ProductSamianLink(
                        product_id=candidates[0], samian_product_id=sp.samian_id,
                        method=ProductSamianLink.Method.EXACT_CODE,
                    ))
                    seen_product_ids.add(candidates[0])
                elif len(candidates) > 1:
                    ambiguous.append((sp, candidates))
                else:
                    unmatched.append(sp)
            ProductSamianLink.objects.bulk_create(links)
            linked = len(links)

        total = linked + len(ambiguous) + len(unmatched)
        self.stdout.write(self.style.SUCCESS(f"متصل شد: {linked} از {total} محصول سامیان"))
        if ambiguous:
            self.stdout.write(self.style.WARNING(f"چند محصول سایت با یک کد ({len(ambiguous)}):"))
            for sp, pids in ambiguous[: options["show_unmatched"]]:
                self.stdout.write(f"  {sp.subcode}  {sp.name}  -> {pids}")
        if unmatched:
            self.stdout.write(self.style.WARNING(f"بدون محصول سایت ({len(unmatched)}):"))
            for sp in unmatched[: options["show_unmatched"]]:
                self.stdout.write(f"  {sp.subcode}  {sp.name}")
