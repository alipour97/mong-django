"""
Management command: refresh what the site sells from the sales software in use.

    python manage.py sync_erp          # prices, stock, variants, images (every few minutes)
    python manage.py sync_erp --full   # plus what changes rarely (nightly)
"""
from __future__ import annotations

import requests
from django.core.management.base import BaseCommand, CommandError
from sqlalchemy.exc import SQLAlchemyError

from apps.erp.connector import SourceError, get_connector
from apps.storefront import catalog


class Command(BaseCommand):
    help = "همگام‌سازی کالا، قیمت و موجودی از نرم‌افزار فروش"

    def add_arguments(self, parser):
        parser.add_argument("--full", action="store_true", help="با داده‌هایی که کم عوض می‌شوند")

    def handle(self, *args, **opts):
        try:
            get_connector().sync(full=opts["full"], log=self.stdout.write)
        except (requests.RequestException, SourceError, SQLAlchemyError) as exc:
            raise CommandError(str(exc)) from exc
        catalog.clear_caches()
