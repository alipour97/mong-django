"""
Management command: sync AI product profiles from LEBAZAI (office.lebazacenter.com).

Usage:
  python manage.py sync_ai_profiles
  python manage.py sync_ai_profiles --reset
  python manage.py sync_ai_profiles --subcode 2383051151
  python manage.py sync_ai_profiles --limit 50
"""
from django.core.management.base import BaseCommand
from apps.website.services.lebazai_sync import (
    sync_product_ai_profiles,
    sync_single_product_ai_profile,
)


class Command(BaseCommand):
    help = "همگام‌سازی پروفایل‌های هوش مصنوعی (عناوین سئو، توضیحات، FAB، تگ‌ها) از office.lebazacenter.com"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="ریست کردن چکپوینت و همگام‌سازی کامل از ابتدا",
        )
        parser.add_argument(
            "--subcode",
            type=str,
            default=None,
            help="همگام‌سازی تکی یک کالا بر پایه کد فرعی/بارکد",
        )
        parser.add_argument(
            "--brand",
            type=str,
            default="Mong",
            help="نام برند (پیش‌فرض: Mong)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="اندازه بچ در هر درخواست (پیش‌فرض: ۱۰۰)",
        )

    def handle(self, *args, **options):
        subcode = options.get("subcode")
        brand = options.get("brand")
        reset = options.get("reset", False)
        limit = options.get("limit", 100)

        if subcode:
            self.stdout.write(f"همگام‌سازی تک کالای {subcode}...")
            res = sync_single_product_ai_profile(subcode, brand=brand)
            if res.get("ok"):
                action = "ایجاد شد" if res.get("created") else "به‌روزرسانی شد"
                self.stdout.write(self.style.SUCCESS(f"پروفایل هوش مصنوعی کالای {subcode} با موفقیت {action}."))
            else:
                self.stdout.write(self.style.ERROR(f"خطا در همگام‌سازی: {res.get('error')}"))
            return

        res = sync_product_ai_profiles(
            brand=brand,
            reset=reset,
            limit=limit,
            on_progress=lambda msg: self.stdout.write(msg),
        )

        if res.get("ok"):
            self.stdout.write(self.style.SUCCESS(
                f"\nهمگام‌سازی با موفقیت انجام شد:\n"
                f"  تعداد کل پردازش شده: {res['total_processed']}\n"
                f"  پروفایل‌های جدید ایجاد شده: {res['created']}\n"
                f"  پروفایل‌های به‌روزرسانی شده: {res['updated']}\n"
                f"  تعداد کالاهای بدون انطباق: {res['skipped']}\n"
            ))
        else:
            self.stdout.write(self.style.ERROR(f"خطا در فرایند همگام‌سازی: {res.get('error')}"))
