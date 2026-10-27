"""
Management command: read site customers' data from Samian (read only).

For every website.Customer: the Samian customer with the same mobile, its
addresses, its invoices and the invoice rows. See services/customers.py.

    python manage.py sync_samian_customers
    python manage.py sync_samian_customers --customer 1052 --customer 1053
    python manage.py sync_samian_customers --all-rows   # re-read rows of every invoice
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.samian.services.customers import sync_site_customers


class Command(BaseCommand):
    help = "سینک مشتری، آدرس و سابقه‌ی خرید مشتریان سایت از سامیان"

    def add_arguments(self, parser):
        parser.add_argument("--customer", type=int, action="append", help="فقط این مشتری سایت (id)")
        parser.add_argument("--all-rows", action="store_true", help="ردیف‌های همه‌ی فاکتورها دوباره خوانده شوند")

    def handle(self, *args, **options):
        result = sync_site_customers(customer_ids=options.get("customer"), all_rows=options["all_rows"])
        self.stdout.write(self.style.SUCCESS(json.dumps(result, ensure_ascii=False)))
