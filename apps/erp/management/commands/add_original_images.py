"""Management command: give some products their original LEBAZAI photos (socks, for one).

    python manage.py add_original_images --department "زنانه/اکسسوری/جوراب" --count 20
    python manage.py add_original_images --department "زنانه/اکسسوری/جوراب" --count 20 --subcode 2383051151
    python manage.py add_original_images --category جوراب     (every product on sale in such a category, without photos)
"""
import requests
from django.core.management.base import BaseCommand, CommandError

from apps.erp import lebazai
from apps.erp.connector import SourceError
from apps.erp.models import LebazaiImage
from apps.website.models import Product

SUBCODES_PER_CALL = 100


class Command(BaseCommand):
    help = "افزودن عکس‌های اصلی LEBAZAI به تعدادی از کالاهای یک دپارتمان"

    def add_arguments(self, parser):
        parser.add_argument("--department", action="append", default=[], help="مسیر دپارتمان، مثل زنانه/اکسسوری/جوراب (می‌شود چند بار داد)")
        parser.add_argument("--category", default="", help="همهٔ کالاهای در حال فروش دسته‌هایی که عنوانشان این باشد و عکس ندارند")
        parser.add_argument("--count", type=int, default=20, help="تعداد کالا برای هر دپارتمان (پیش‌فرض ۲۰)")
        parser.add_argument("--subcode", action="append", default=[], help="کد فرعی که حتماً در میان باشد (می‌شود چند بار داد)")
        parser.add_argument("--kind", choices=["front", "back", "all"], default="all", help="زاویه عکس (پیش‌فرض همه)")
        parser.add_argument("--per-color", type=int, default=None, help="حداکثر عکس برای هر رنگ")
        parser.add_argument("--with-photos", action="store_true", help="کالاهایی که عکس تاییدشده دارند هم بیایند")
        parser.add_argument("--dry-run", action="store_true", help="فقط گزارش، بدون دانلود و ذخیره")

    def handle(self, *args, **opts):
        if not opts["department"] and not opts["subcode"] and not opts["category"]:
            raise CommandError("--department, --subcode or --category is needed")
        common = {"kind": opts["kind"], "per_color": opts["per_color"], "with_photos": opts["with_photos"],
                  "dry_run": opts["dry_run"], "log": self.stdout.write}
        try:
            if opts["department"] or opts["subcode"]:
                lebazai.add_originals(departments=opts["department"], count=opts["count"], subcodes=opts["subcode"], **common)
            if opts["category"]:
                products = Product.objects.filter(on_sale=True, category__title=opts["category"]).exclude(barcode="")
                if not opts["with_photos"]:
                    approved = LebazaiImage.objects.exclude(key__startswith=lebazai.ORIGINAL_PREFIX).values("product_id")
                    products = products.exclude(id__in=approved)
                subcodes = list(products.values_list("barcode", flat=True))
                for start in range(0, len(subcodes), SUBCODES_PER_CALL):
                    lebazai.add_originals(departments=[], count=0, subcodes=subcodes[start:start + SUBCODES_PER_CALL], **common)
        except (requests.RequestException, SourceError) as exc:
            raise CommandError(str(exc)) from exc
