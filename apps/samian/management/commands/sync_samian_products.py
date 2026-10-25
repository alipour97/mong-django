"""
Management command: sync product master list from Samian ERP to SamianProduct.
"""
from __future__ import annotations

import logging
import time
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.samian import CatalogService, get_samian_client
from apps.samian.models import SamianProduct, SamianSyncLog

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "همگام‌سازی کاتالوگ محصولات از سامین ERP (/v2/product/productmain)"

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
            default=100,
            help="تعداد رکورد در هر صفحه API (پیش‌فرض: ۱۰۰)",
        )
        parser.add_argument(
            "--max-records",
            type=int,
            default=None,
            help="حداکثر تعداد رکوردهای دریافتی (پیش‌فرض: همه)",
        )

    def handle(self, *args, **options):
        batch_size = options.get("batch_size", 500)
        take_count = options.get("take_count", 100)
        max_records = options.get("max_records")

        self.stdout.write(self.style.NOTICE("شروع همگام‌سازی محصولات سامین..."))

        sync_log = SamianSyncLog.objects.create(
            action=SamianSyncLog.Action.SYNC_PRODUCTS,
            status=SamianSyncLog.Status.RUNNING,
        )

        catalog = CatalogService()
        t0 = time.time()
        read_count = 0
        upserted_count = 0
        batch: list[SamianProduct] = []

        try:
            for item in catalog.iter_products(take_count=take_count, max_records=max_records):
                read_count += 1
                samian_id = item.get("productmain_id") or item.get("id")
                if not samian_id:
                    continue

                prod = SamianProduct(
                    samian_id=int(samian_id),
                    subcode=str(item.get("k_bar_code") or "").strip(),
                    name=str(item.get("k_name") or "").strip(),
                    name_en=str(item.get("k_name_en") or "").strip(),
                    description=str(item.get("k_desc") or "").strip(),
                    brand_name=str(item.get("__codingbrand_id_value") or "").strip(),
                    department_name=str(item.get("__codingdepartment_id_value") or "").strip(),
                    season=str(item.get("seasonused") or "").strip(),
                    style=str(item.get("stylenew") or "").strip(),
                    is_active=bool(item.get("isactive", True)),
                    is_saleable=bool(item.get("issaleable", True)),
                    raw_data={},
                )
                batch.append(prod)

                if len(batch) >= batch_size:
                    SamianProduct.objects.bulk_create(
                        batch,
                        update_conflicts=True,
                        unique_fields=["samian_id"],
                        update_fields=[
                            "subcode", "name", "name_en", "description",
                            "brand_name", "department_name", "season",
                            "style", "is_active", "is_saleable", "updated_at",
                        ],
                    )
                    upserted_count += len(batch)
                    self.stdout.write(f"  ثبت {upserted_count} محصول در دیتابیس...")
                    batch = []

            if batch:
                SamianProduct.objects.bulk_create(
                    batch,
                    update_conflicts=True,
                    unique_fields=["samian_id"],
                    update_fields=[
                        "subcode", "name", "name_en", "description",
                        "brand_name", "department_name", "season",
                        "style", "is_active", "is_saleable", "updated_at",
                    ],
                )
                upserted_count += len(batch)

            duration = time.time() - t0
            sync_log.status = SamianSyncLog.Status.SUCCESS
            sync_log.finished_at = timezone.now()
            sync_log.records_read = read_count
            sync_log.records_upserted = upserted_count
            sync_log.details = {"duration_seconds": round(duration, 2)}
            sync_log.save()

            self.stdout.write(self.style.SUCCESS(
                f"\nهمگام‌سازی محصولات با موفقیت به پایان رسید:\n"
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
            self.stdout.write(self.style.ERROR(f"همگام‌سازی ناموفق بود: {exc}"))
            raise
