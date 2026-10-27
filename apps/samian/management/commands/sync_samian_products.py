"""
Management command: sync product master list from Samian ERP to SamianProduct.

Only products of settings.SAMIAN_BRAND_IDS are fetched (keyset paging on
productmain_id). Products of other brands left from earlier syncs are removed.
"""
from __future__ import annotations

import logging
import time
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings

from apps.samian import get_samian_client
from apps.samian.client import brand_filter
from apps.samian.models import SamianDepartment, SamianProduct, SamianSyncLog

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

        self.stdout.write(self.style.NOTICE("شروع همگام‌سازی محصولات سامین..."))

        sync_log = SamianSyncLog.objects.create(
            action=SamianSyncLog.Action.SYNC_PRODUCTS,
            status=SamianSyncLog.Status.RUNNING,
        )

        client = get_samian_client()
        t0 = time.time()
        read_count = 0
        upserted_count = 0
        batch: list[SamianProduct] = []

        department_pks = dict(SamianDepartment.objects.values_list("samian_id", "pk"))
        try:
            seen_ids: set[int] = set()
            for item in client.iter_keyset(
                "product/productmain", key="productmain_id", take_count=take_count, filters=brand_filter()
            ):
                if max_records is not None and read_count >= max_records:
                    break
                read_count += 1
                samian_id = item.get("productmain_id") or item.get("id")
                if not samian_id:
                    continue

                seen_ids.add(int(samian_id))
                prod = SamianProduct(
                    samian_id=int(samian_id),
                    subcode=str(item.get("k_bar_code") or "").strip(),
                    name=str(item.get("k_name") or "").strip(),
                    name_en=str(item.get("k_name_en") or "").strip(),
                    description=str(item.get("k_desc") or "").strip(),
                    brand_name=str(item.get("__codingbrand_id_value") or "").strip(),
                    department_name=str(item.get("__codingdepartment_id_value") or "").strip(),
                    department_id=int(item["codingdepartment_id"]) if item.get("codingdepartment_id") else None,
                    samian_department_id=department_pks.get(int(item["codingdepartment_id"])) if item.get("codingdepartment_id") else None,
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
                            "brand_name", "department_name", "department_id", "samian_department", "season",
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
                        "brand_name", "department_name", "department_id", "samian_department", "season",
                        "style", "is_active", "is_saleable", "updated_at",
                    ],
                )
                upserted_count += len(batch)

            pruned = 0
            if settings.SAMIAN_BRAND_IDS and max_records is None:
                stale = list(set(SamianProduct.objects.values_list("samian_id", flat=True)) - seen_ids)
                for i in range(0, len(stale), 500):
                    pruned += SamianProduct.objects.filter(samian_id__in=stale[i:i + 500]).delete()[1].get("samian.SamianProduct", 0)
                self.stdout.write(f"  حذف {pruned} رکورد مربوط به برندهای دیگر")

            duration = time.time() - t0
            sync_log.status = SamianSyncLog.Status.SUCCESS
            sync_log.finished_at = timezone.now()
            sync_log.records_read = read_count
            sync_log.records_upserted = upserted_count
            sync_log.details = {"duration_seconds": round(duration, 2), "pruned": pruned}
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
