"""
Management command: sync stock levels from Samian ERP (/v2/wm/stock) to SamianInventory.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from apps.samian import InventoryService
from apps.samian.models import SamianInventory, SamianSyncLog

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "همگام‌سازی موجودی انبار از سامین ERP (/v2/wm/stock)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="اندازه بچ در هر تراکنش دیتابیس (پیش‌فرض: ۱۰۰۰)",
        )
        parser.add_argument(
            "--take-count",
            type=int,
            default=5000,
            help="تعداد رکورد در هر صفحه API (پیش‌فرض: ۵۰۰۰)",
        )
        parser.add_argument(
            "--full",
            action="store_true",
            help="خواندن کل جدول موجودی به‌جای حالت افزایشی",
        )
        parser.add_argument(
            "--since",
            default=None,
            help="فقط رکوردهای تغییریافته بعد از این تاریخ (قالب: YYYY-MM-DD HH:MM)",
        )
        parser.add_argument(
            "--max-records",
            type=int,
            default=None,
            help="حداکثر رکوردهای دریافتی (پیش‌فرض: همه)",
        )

    def handle(self, *args, **options):
        batch_size = options.get("batch_size", 1000)
        take_count = options.get("take_count", 5000)
        full = options.get("full", False)
        max_records = options.get("max_records")

        since_dt = None
        if options["since"]:
            parsed = parse_datetime(options["since"].replace(" ", "T"))
            if parsed is None:
                raise CommandError("قالب تاریخ --since نامعتبر است. نمونه: '2026-10-18 08:00'")
            since_dt = timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed
        elif not full:
            # Incremental default: newest updated_at minus 15 minutes safety margin
            latest_stock = SamianInventory.objects.order_by("-updated_at_samian").first()
            if latest_stock and latest_stock.updated_at_samian:
                since_dt = latest_stock.updated_at_samian - timedelta(minutes=15)

        mode_str = "کامل" if full else f"افزایشی (از {since_dt or 'ابتدا'})"
        self.stdout.write(self.style.NOTICE(f"شروع همگام‌سازی موجودی سامین ({mode_str})..."))

        sync_log = SamianSyncLog.objects.create(
            action=SamianSyncLog.Action.SYNC_INVENTORY,
            status=SamianSyncLog.Status.RUNNING,
        )

        inventory = InventoryService()
        t0 = time.time()
        read_count = 0
        upserted_count = 0
        batch: list[SamianInventory] = []

        try:
            for item in inventory.iter_stock(take_count=take_count, updated_since=since_dt, max_records=max_records):
                read_count += 1
                samian_id = item.get("id")
                barcodemain_id = item.get("barcodemain_id")
                warehouse_id = item.get("warehouse_id")
                if not samian_id or not barcodemain_id or not warehouse_id:
                    continue

                count_val = item.get("count") or item.get("qty") or item.get("stock") or 0
                try:
                    count_int = int(float(count_val))
                except (ValueError, TypeError):
                    count_int = 0

                updatedate_raw = item.get("updatedate")
                updatedate_dt = None
                if updatedate_raw:
                    try:
                        p_dt = parse_datetime(str(updatedate_raw).replace(" ", "T"))
                        if p_dt:
                            updatedate_dt = timezone.make_aware(p_dt) if timezone.is_naive(p_dt) else p_dt
                    except Exception:
                        pass

                stock_obj = SamianInventory(
                    samian_id=int(samian_id),
                    barcodemain_id=int(barcodemain_id),
                    warehouse_id=int(warehouse_id),
                    barcode=str(item.get("__barcodemain_id_value") or "").strip(),
                    count=count_int,
                    updated_at_samian=updatedate_dt,
                    raw_data={},
                )
                batch.append(stock_obj)

                if len(batch) >= batch_size:
                    SamianInventory.objects.bulk_create(
                        batch,
                        update_conflicts=True,
                        unique_fields=["samian_id"],
                        update_fields=["count", "updated_at_samian", "updated_at"],
                    )
                    upserted_count += len(batch)
                    self.stdout.write(f"  ثبت {upserted_count} ردیف موجودی در دیتابیس...")
                    batch = []

            if batch:
                SamianInventory.objects.bulk_create(
                    batch,
                    update_conflicts=True,
                    unique_fields=["samian_id"],
                    update_fields=["count", "updated_at_samian", "updated_at"],
                )
                upserted_count += len(batch)

            duration = time.time() - t0
            sync_log.status = SamianSyncLog.Status.SUCCESS
            sync_log.finished_at = timezone.now()
            sync_log.records_read = read_count
            sync_log.records_upserted = upserted_count
            sync_log.details = {"duration_seconds": round(duration, 2), "mode": "full" if full else "incremental"}
            sync_log.save()

            self.stdout.write(self.style.SUCCESS(
                f"\nهمگام‌سازی موجودی با موفقیت به پایان رسید:\n"
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
            self.stdout.write(self.style.ERROR(f"همگام‌سازی موجودی ناموفق بود: {exc}"))
            raise
