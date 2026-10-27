"""
Management command: read Mong sales from Samian (read only).

Scans sale rows added since the last run and keeps those of Mong products
(brands مانگ and توليد), from every branch, Lebaza's included; then reads
their invoices. See services/sales.py.

    python manage.py sync_samian_sales          # new rows only
    python manage.py sync_samian_sales --full   # every row, refreshes invoice headers
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.samian.services.sales import link_customers, sync_sales


class Command(BaseCommand):
    help = "سینک فروش کالاهای مانگ از سامیان"

    def add_arguments(self, parser):
        parser.add_argument("--full", action="store_true", help="همه‌ی ردیف‌ها از اول، با به‌روزرسانی سربرگ فاکتورها")

    def handle(self, *args, **options):
        result = sync_sales(full=options["full"])
        result["invoices_attached"] = link_customers()
        self.stdout.write(self.style.SUCCESS(json.dumps(result, ensure_ascii=False)))
