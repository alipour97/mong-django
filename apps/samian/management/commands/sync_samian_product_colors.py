"""
Management command: sync product color definitions and galleries from Samian ERP.
"""
from __future__ import annotations

import logging
import time
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.samian import MediaService, get_samian_client
from apps.samian.models import SamianProduct, SamianProductColor, SamianSyncLog

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "همگام‌سازی رنگ‌ها و گالری تصاویر از سامین ERP (/v2/product/colors)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="اندازه بچ در هر تراکنش دیتابیس (پیش‌فرض: ۵۰۰)",
        )
        parser.add_argument(
            "--take-count",
            type=int,
            default=5000,
            help="تعداد رکورد در هر صفحه API (پیش‌فرض: ۵۰۰۰)",
        )
        parser.add_argument(
            "--max-records",
            type=int,
            default=None,
            help="حداکثر تعداد رکوردهای دریافتی (پیش‌فرض: همه)",
        )

    def handle(self, *args, **options):
        batch_size = options.get("batch_size", 500)
        take_count = options.get("take_count", 5000)
        max_records = options.get("max_records")

        self.stdout.write(self.style.NOTICE("شروع همگام‌سازی رنگ‌ها و گالری‌های سامین..."))

        sync_log = SamianSyncLog.objects.create(
            action=SamianSyncLog.Action.SYNC_COLORS,
            status=SamianSyncLog.Status.RUNNING,
        )

        client = get_samian_client()
        media = MediaService()
        # colors have no brand field and ignore keyset filters: read all with skip, keep those of synced products
        product_pks = dict(SamianProduct.objects.values_list("samian_id", "pk"))
        t0 = time.time()
        read_count = 0
        upserted_count = 0
        batch: list[SamianProductColor] = []

        try:
            for item in client.iter_paginated("product/colors", take_count=take_count, sort="id", sort_type="asc"):
                if max_records is not None and read_count >= max_records:
                    break
                read_count += 1
                color_id = item.get("id")
                productmain_id = item.get("productmain_id")
                if not color_id or int(productmain_id or 0) not in product_pks:
                    continue

                gallery_items = media.parse_gallery(item.get("colorsgalery"))
                has_gallery = bool(gallery_items)

                subcode_hint = ""
                for g in gallery_items:
                    fp = g.get("filePath") or ""
                    if "/" in fp:
                        subcode_hint = fp.split("/")[0]
                        break

                color_obj = SamianProductColor(
                    samian_id=int(color_id),
                    samian_product_id=product_pks[int(productmain_id)],
                    productmain_id=int(productmain_id),
                    colorinfo_id=int(item["colorinfo_id"]) if item.get("colorinfo_id") else None,
                    color_name=str(item.get("__colorinfo_id_value") or "").strip(),
                    colorsgalery=gallery_items,
                    has_gallery=has_gallery,
                    subcode_hint=subcode_hint,
                )
                batch.append(color_obj)

                if len(batch) >= batch_size:
                    SamianProductColor.objects.bulk_create(
                        batch,
                        update_conflicts=True,
                        unique_fields=["samian_id"],
                        update_fields=[
                            "samian_product", "productmain_id", "colorinfo_id", "color_name",
                            "colorsgalery", "has_gallery", "subcode_hint", "updated_at",
                        ],
                    )
                    upserted_count += len(batch)
                    self.stdout.write(f"  ثبت {upserted_count} رکورد رنگ در دیتابیس...")
                    batch = []

            if batch:
                SamianProductColor.objects.bulk_create(
                    batch,
                    update_conflicts=True,
                    unique_fields=["samian_id"],
                    update_fields=[
                        "samian_product", "productmain_id", "colorinfo_id", "color_name",
                        "colorsgalery", "has_gallery", "subcode_hint", "updated_at",
                    ],
                )
                upserted_count += len(batch)

            # Link with existing SamianProducts
            self.stdout.write("اتصال رنگ‌ها به رکوردهای محصولات سامین...")
            product_map = dict(SamianProduct.objects.values_list("samian_id", "id"))
            to_update = []
            for pc in SamianProductColor.objects.filter(samian_product__isnull=True):
                local_prod_id = product_map.get(pc.productmain_id)
                if local_prod_id:
                    pc.samian_product_id = local_prod_id
                    to_update.append(pc)
            if to_update:
                SamianProductColor.objects.bulk_update(to_update, ["samian_product"], batch_size=1000)
                self.stdout.write(f"  اتصال {len(to_update)} رنگ به محصولات متناظر.")

            duration = time.time() - t0
            sync_log.status = SamianSyncLog.Status.SUCCESS
            sync_log.finished_at = timezone.now()
            sync_log.records_read = read_count
            sync_log.records_upserted = upserted_count
            sync_log.details = {"duration_seconds": round(duration, 2)}
            sync_log.save()

            self.stdout.write(self.style.SUCCESS(
                f"\nهمگام‌سازی رنگ‌ها با موفقیت به پایان رسید:\n"
                f"  تعداد رکورد خوانده‌شده: {read_count}\n"
                f"  تعداد رکورد ذخیره‌شده: {upserted_count}\n"
                f"  مدت زمان: {duration:.2f} ثانیه"
            ))

        except Exception as exc:
            duration = time.time() - t0
            sync_log.status = SamianSyncLog.Status.FAILED
            sync_log.finished_at = timezone.now()
            sync_log.error_message = str(exc)
            sync_log.records_read = read_count
            sync_log.records_upserted = upserted_count
            sync_log.details = {"duration_seconds": round(duration, 2)}
            sync_log.save()
            self.stdout.write(self.style.ERROR(f"همگام‌سازی رنگ‌ها ناموفق بود: {exc}"))
            raise
