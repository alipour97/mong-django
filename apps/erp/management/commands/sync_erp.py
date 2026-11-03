"""
Management command: copy what the sales software owns into the site's tables.

    python manage.py sync_erp           # products, categories, prices, stock, coupons, gift cards
    python manage.py sync_erp --force   # also when the read is much smaller than what is on sale
"""
from __future__ import annotations

import requests
from django.core.management.base import BaseCommand, CommandError
from sqlalchemy.exc import SQLAlchemyError

from apps.erp import jobs
from apps.erp.connector import SourceError, get_connector
from apps.storefront import catalog


class Command(BaseCommand):
    help = "همگام‌سازی کالا، قیمت و موجودی از نرم‌افزار فروش"

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="حتی اگر تعداد کالاها خیلی کمتر از قبل باشد")

    def handle(self, *args, **opts):
        if not opts["force"]:  # the scheduled run, recorded for the admin panel
            done = jobs.run("erp", log=self.stdout.write)
            if not done.ok:
                raise CommandError(done.error)
            return
        try:
            get_connector().sync(force=True, log=self.stdout.write)
        except (requests.RequestException, SourceError, SQLAlchemyError) as exc:
            raise CommandError(str(exc)) from exc
        catalog.clear_caches()
