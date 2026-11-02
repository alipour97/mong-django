"""Management command: give some products of a department their original LEBAZAI photos (socks, for one); sync_erp shows them on its next run.

    python manage.py add_original_images --department "زنانه/اکسسوری/جوراب" --count 20
    python manage.py add_original_images --department "زنانه/اکسسوری/جوراب" --count 20 --subcode 2383051151
"""
import requests
from django.core.management.base import BaseCommand, CommandError

from apps.erp import lebazai
from apps.erp.connector import SourceError


class Command(BaseCommand):
    help = "افزودن عکس‌های اصلی LEBAZAI به تعدادی از کالاهای یک دپارتمان"

    def add_arguments(self, parser):
        parser.add_argument("--department", action="append", default=[], help="مسیر دپارتمان، مثل زنانه/اکسسوری/جوراب (می‌شود چند بار داد)")
        parser.add_argument("--count", type=int, default=20, help="تعداد کالا برای هر دپارتمان (پیش‌فرض ۲۰)")
        parser.add_argument("--subcode", action="append", default=[], help="کد فرعی که حتماً در میان باشد (می‌شود چند بار داد)")
        parser.add_argument("--kind", choices=["front", "back", "all"], default="all", help="زاویه عکس (پیش‌فرض همه)")
        parser.add_argument("--per-color", type=int, default=None, help="حداکثر عکس برای هر رنگ")
        parser.add_argument("--with-photos", action="store_true", help="کالاهایی که عکس تاییدشده دارند هم بیایند")
        parser.add_argument("--dry-run", action="store_true", help="فقط گزارش، بدون دانلود و ذخیره")

    def handle(self, *args, **opts):
        if not opts["department"] and not opts["subcode"]:
            raise CommandError("--department or --subcode is needed")
        try:
            lebazai.add_originals(
                departments=opts["department"], count=opts["count"], subcodes=opts["subcode"], kind=opts["kind"],
                per_color=opts["per_color"], with_photos=opts["with_photos"], dry_run=opts["dry_run"], log=self.stdout.write,
            )
        except (requests.RequestException, SourceError) as exc:
            raise CommandError(str(exc)) from exc
