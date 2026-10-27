"""
Management command: create the Branch table from the businessDepartments config.

Run once. After that branches are edited in the admin and the config's
departmentList is generated from them (storefront PrimaryConfig views).
Each branch is linked to the Samian warehouse whose name it contains; the
warehouses in STOREFRONT_STOCK_WAREHOUSE_IDS are marked sells_online.

    python manage.py seed_branches          # only when the table is empty
    python manage.py seed_branches --force  # delete and recreate
"""
from __future__ import annotations

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.samian.models import SamianWarehouse
from apps.storefront.catalog import norm
from apps.website.models import Branch, PrimaryConfig

CONFIG_KEY = "businessDepartments"


def _warehouse_for(title: str, warehouses: list[SamianWarehouse]) -> SamianWarehouse | None:
    """The warehouse with the longest name contained in the branch title."""
    text = norm(title)
    best = None
    for wh in warehouses:
        name = norm(wh.title).replace("انبار", "").strip()
        if name and name in text and (best is None or len(name) > len(norm(best.title))):
            best = wh
    return best


class Command(BaseCommand):
    help = "ساخت جدول شعبه‌ها از کانفیگ businessDepartments"

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="حذف شعبه‌های فعلی و ساخت دوباره")

    def handle(self, *args, **options):
        if Branch.objects.exists() and not options["force"]:
            raise CommandError("شعبه‌ها قبلاً ساخته شده‌اند؛ برای ساخت دوباره --force بدهید")
        pc = PrimaryConfig.objects.filter(key=CONFIG_KEY, is_deleted=False).first()
        if not pc:
            raise CommandError(f"کانفیگ {CONFIG_KEY} پیدا نشد")
        departments = json.loads(pc.value).get("departmentList") or []

        warehouses = [
            wh for wh in SamianWarehouse.objects.filter(is_active=True)
            if not any(w in wh.title for w in ("ضايعات", "دپو"))
        ]
        online = set(settings.STOREFRONT_STOCK_WAREHOUSE_IDS)
        with transaction.atomic():
            Branch.objects.all().delete()
            for order, dep in enumerate(departments, start=1):
                loc = dep.get("location") or {}
                wh = _warehouse_for(dep.get("depTitle", ""), warehouses)
                branch = Branch.objects.create(
                    title=dep.get("depTitle", ""),
                    address=dep.get("address", ""),
                    phones="\n".join(p.get("phoneNumber", "") for p in dep.get("phoneNumbers") or []),
                    latitude=loc.get("lat"),
                    longitude=loc.get("lng"),
                    warehouse=wh,
                    sells_online=bool(wh and wh.samian_id in online),
                    display_order=order,
                    front_id=dep.get("id"),
                )
                self.stdout.write(
                    f"  {branch.title:<28} انبار: {wh.title if wh else '—':<20}"
                    + ("  فروش آنلاین" if branch.sells_online else "")
                )
            missing = online - set(Branch.objects.filter(sells_online=True).values_list("warehouse__samian_id", flat=True))
            if missing:
                self.stdout.write(self.style.WARNING(f"انبارهای فروش آنلاین بدون شعبه: {sorted(missing)}"))
        self.stdout.write(self.style.SUCCESS(f"{len(departments)} شعبه ساخته شد"))
