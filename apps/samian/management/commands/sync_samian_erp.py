"""
Unified Samian ERP sync command.

Default: syncs prices + inventory together in one run.
Use --only to run a specific sync type.

Usage:
    python manage.py sync_samian_erp                    # prices + inventory (default)
    python manage.py sync_samian_erp --only prices      # just prices
    python manage.py sync_samian_erp --only inventory   # just inventory
    python manage.py sync_samian_erp --full             # full sweep (not incremental)
"""
from __future__ import annotations

import time

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

from apps.samian.services.erp_sync import (
    sync_barcodes,
    sync_inventory,
    sync_prices,
    sync_prices_and_inventory,
)
from apps.samian.client import get_samian_client


SYNC_TYPES = ("prices", "inventory", "barcodes")


class Command(BaseCommand):
    help = "سینک قیمت و موجودی از سامیان ERP (پیش‌فرض: هر دو با هم)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--only",
            choices=SYNC_TYPES,
            default=None,
            help="فقط یک نوع سینک اجرا شود (prices یا inventory)",
        )
        parser.add_argument(
            "--full",
            action="store_true",
            default=False,
            help="سینک کامل (بدون incremental)",
        )
        parser.add_argument(
            "--take-count",
            type=int,
            default=None,
            help="تعداد رکورد در هر صفحه API",
        )
        parser.add_argument(
            "--max-records",
            type=int,
            default=None,
            help="حداکثر تعداد رکوردها",
        )

    def handle(self, *args, **options):
        only = options["only"]
        full = options["full"]
        take_count = options["take_count"]
        max_records = options["max_records"]

        client = get_samian_client()
        t0 = time.time()

        try:
            if only == "prices":
                self.stdout.write(self.style.NOTICE("سینک قیمت‌ها از سامیان..."))
                result = sync_prices(
                    client,
                    take_count=take_count or 1000,
                    max_records=max_records,
                    stdout=self.stdout,
                )
                self._report("قیمت", result, t0)

            elif only == "barcodes":
                self.stdout.write(self.style.NOTICE("سینک بارکدها از سامیان..."))
                result = sync_barcodes(
                    client,
                    take_count=take_count or 500,
                    max_records=max_records,
                    stdout=self.stdout,
                )
                self._report("بارکد", result, t0)

            elif only == "inventory":
                self.stdout.write(self.style.NOTICE("سینک موجودی از سامیان..."))
                result = sync_inventory(
                    client,
                    full=full,
                    take_count=take_count or 5000,
                    max_records=max_records,
                    stdout=self.stdout,
                )
                self._report("موجودی", result, t0)

            else:
                self.stdout.write(self.style.NOTICE("سینک قیمت + موجودی از سامیان..."))
                result = sync_prices_and_inventory(
                    client,
                    full=full,
                    price_take_count=take_count or 1000,
                    inventory_take_count=take_count or 5000,
                    max_records=max_records,
                    stdout=self.stdout,
                )
                self.stdout.write(self.style.SUCCESS(
                    f"\nسینک قیمت و موجودی با موفقیت انجام شد:"
                    f"\n  قیمت: {result['prices'].get('synced', 0)} محصول از {result['prices'].get('total', 0)}"
                    f"\n  موجودی: {result['inventory'].get('synced', 0)} ردیف از {result['inventory'].get('total', 0)}"
                    f"\n  مدت زمان: {time.time() - t0:.1f} ثانیه"
                ))

            if settings.ERP_CONNECTOR == "samian":
                call_command("sync_erp", stdout=self.stdout)

        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"سینک ناموفق: {exc}"))
            raise

    def _report(self, label: str, result: dict, t0: float):
        self.stdout.write(self.style.SUCCESS(
            f"\nسینک {label} با موفقیت انجام شد:"
            f"\n  خوانده‌شده: {result.get('total', 0)}"
            f"\n  بروزرسانی: {result.get('synced', 0)}"
            f"\n  مدت زمان: {time.time() - t0:.1f} ثانیه"
        ))
