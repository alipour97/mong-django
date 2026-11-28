"""Send site accounts to DadehfaOnlineShop and inspect the customer's vouchers."""
from __future__ import annotations

import re

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone
from sqlalchemy.exc import SQLAlchemyError

from apps.erp import customer_sync, jobs
from apps.erp.models import ErpCoupon, ErpGiftCard
from apps.legacy.db import fetch_all
from apps.smsir import normalize_mobile


class Command(BaseCommand):
    help = "ارسال حساب‌های سایت به DadehfaOnlineShop و بررسی کوپن و کارت هدیهٔ مشتری"

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--all", action="store_true", help="ارسال حساب‌های فعال بدون شناسهٔ داده‌فا")
        mode.add_argument("--mobile", help="ارسال یک حساب و نمایش تعداد کوپن‌ها و کارت‌های ثبت‌شده")
        mode.add_argument("--check-mobile", help="فقط بررسی حساب و کوپن و کارت هدیه، بدون نوشتن")

    def handle(self, *args, **options):
        mobile = options["check_mobile"] if options["check_mobile"] is not None else options["mobile"]
        if mobile is not None:
            mobile = normalize_mobile(mobile)
            if not re.fullmatch(customer_sync.VALID_MOBILE, mobile):
                raise CommandError("شمارهٔ موبایل نامعتبر است")

        if options["check_mobile"] is not None:
            self.report(mobile)
            return

        if not options["all"] and mobile is None:
            run = jobs.run("customers", log=self.stdout.write)
            if not run.ok:
                raise CommandError(run.error)
            return

        if settings.ERP_CONNECTOR != "dadehfa" or not settings.ERP_WRITES_ENABLED:
            raise CommandError("ارسال حساب نیازمند ERP_CONNECTOR=dadehfa و ERP_WRITES_ENABLED=true است")

        now = timezone.now()
        if mobile is not None:
            accounts = customer_sync.eligible().filter(cellphone=mobile)
            if not accounts.update(erp_customer_pending_at=now):
                raise CommandError("حساب فعال با این موبایل در سایت جدید پیدا نشد")
            if not customer_sync.send(accounts.get()):
                raise CommandError("ارسال حساب ناموفق بود. حساب برای تلاش بعدی در صف است")
            self.report(mobile)
            return

        accounts = customer_sync.eligible().filter(erp_customer_id__isnull=True)
        added = accounts.filter(erp_customer_pending_at__isnull=True).update(erp_customer_pending_at=now)
        self.stdout.write(f"{added} حساب به صف اضافه شد")
        run = jobs.run("customers", trigger="manual", log=self.stdout.write)
        if not run.ok:
            raise CommandError(run.error)
        for line in run.changes:
            self.stdout.write(line)

    def report(self, mobile: str) -> None:
        try:
            accounts = fetch_all(
                """SELECT Id, CASE WHEN NULLIF(MapId, '') IS NULL THEN 0 ELSE 1 END AS LinkedToPos
                FROM Customers WHERE CellPhone=:mobile AND IsDeleted=0 ORDER BY Id""",
                {"mobile": mobile},
            )
            legacy = fetch_all(
                """WITH matching AS (SELECT Id FROM Customers WHERE CellPhone=:mobile AND IsDeleted=0)
                SELECT (SELECT COUNT(*) FROM Coupons c WHERE c.IsDeleted=0
                        AND c.CustomerId IN (SELECT Id FROM matching)) AS Coupons,
                       (SELECT COUNT(*) FROM GiftCards g WHERE g.IsDeleted=0
                        AND (g.CustomerMobile=:mobile OR g.CustomerId IN (SELECT Id FROM matching))) AS GiftCards""",
                {"mobile": mobile},
            )[0]
        except (SQLAlchemyError, RuntimeError) as exc:
            raise CommandError("بررسی وضعیت در دیتابیس آنلاین‌شاپ ناموفق بود") from exc

        ids = [row["Id"] for row in accounts]
        self.stdout.write(
            f"دیتابیس آنلاین‌شاپ داده‌فا: {len(ids)} حساب، "
            f"{sum(row['LinkedToPos'] for row in accounts)} پیوند به نرم‌افزار فروش، "
            f"{legacy['Coupons']} کوپن، {legacy['GiftCards']} کارت هدیه"
        )
        site_accounts = customer_sync.eligible().filter(cellphone=mobile).count()
        coupons = ErpCoupon.objects.filter(customer_erp_id__in=ids).count()
        cards = ErpGiftCard.objects.filter(Q(customer_erp_id__in=ids) | Q(mobile=mobile)).count()
        self.stdout.write(f"دیتابیس سایت جدید: {site_accounts} حساب فعال، {coupons} کوپن، {cards} کارت هدیه")
