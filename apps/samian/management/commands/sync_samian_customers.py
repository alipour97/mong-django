"""
Management command: read site customers' data from Samian (read only).

For every website.Customer: the Samian customer with the same mobile and its
addresses, and attaches the Mong invoices of sync_samian_sales to them.
See services/customers.py.

    python manage.py sync_samian_customers
    python manage.py sync_samian_customers --customer 1052 --customer 1053
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.samian.services.customers import sync_site_customers


class Command(BaseCommand):
    help = "سینک مشتری و آدرس مشتریان سایت از سامیان"

    def add_arguments(self, parser):
        parser.add_argument("--customer", type=int, action="append", help="فقط این مشتری سایت (id)")

    def handle(self, *args, **options):
        result = sync_site_customers(customer_ids=options.get("customer"))
        self.stdout.write(self.style.SUCCESS(json.dumps(result, ensure_ascii=False)))
