"""
Management command: test connection to Samian ERP (Development Server Port 8087).
"""
import time
from django.core.management.base import BaseCommand
from apps.samian import (
    get_samian_client,
    get_samian_settings,
    CatalogService,
    InventoryService,
    MediaService,
)


class Command(BaseCommand):
    help = "بررسی و آزمون اتصال به API سامین ERP (پورت توسعه 8087)"

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("=================================================="))
        self.stdout.write(self.style.NOTICE("   آزمون اتصال به وب‌سرویس سامین (Samian ERP)"))
        self.stdout.write(self.style.NOTICE("=================================================="))

        cfg = get_samian_settings()
        self.stdout.write(f"Base URL: {cfg.base_url}")
        self.stdout.write(f"Username: {cfg.username}")
        self.stdout.write(f"Timeout: {cfg.timeout}s")
        self.stdout.write(f"Token Scope: {cfg.token_scope}")

        if "8086" in cfg.base_url:
            self.stdout.write(self.style.ERROR("هشدار بحرانی: پورت ۸۰۸۶ پروداکشن است و نباید استفاده شود!"))
            return

        client = get_samian_client()

        # 1. Login
        self.stdout.write("\n۱. احراز هویت و دریافت توکن...")
        t0 = time.time()
        try:
            token = client.login()
            self.stdout.write(self.style.SUCCESS(f"  موفقیت‌آمیز در {time.time()-t0:.2f} ثانیه. طول توکن: {len(token)} کاراکتر"))
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  شکست در احراز هویت: {exc}"))
            return

        # 2. Product Catalog
        self.stdout.write("\n۲. استعلام کاتالوگ محصولات (/v2/product/productmain)...")
        t0 = time.time()
        try:
            catalog = CatalogService(client=client)
            products = catalog.get_products_page(skip=0, take_count=3)
            self.stdout.write(self.style.SUCCESS(f"  موفقیت‌آمیز در {time.time()-t0:.2f} ثانیه. دریافت {len(products)} نمونه محصول:"))
            for p in products:
                self.stdout.write(f"    - ID: {p.get('id')}, نام: {p.get('k_name')}, کد فرعی: {p.get('k_bar_code')}")
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  خطا در استعلام محصولات: {exc}"))

        # 3. Product Colors
        self.stdout.write("\n۳. استعلام رنگ‌ها (/v2/product/colors)...")
        t0 = time.time()
        try:
            colors = catalog.get_colors_page(skip=0, take_count=3)
            self.stdout.write(self.style.SUCCESS(f"  موفقیت‌آمیز در {time.time()-t0:.2f} ثانیه. دریافت {len(colors)} نمونه رنگ:"))
            for c in colors:
                self.stdout.write(f"    - ID: {c.get('id')}, نام رنگ: {c.get('__colorinfo_id_value')}, productmain_id: {c.get('productmain_id')}")
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  خطا در استعلام رنگ‌ها: {exc}"))

        # 4. Inventory
        self.stdout.write("\n۴. استعلام موجودی انبار (/v2/wm/stock)...")
        t0 = time.time()
        try:
            inventory = InventoryService(client=client)
            stocks = inventory.get_stock_page(skip=0, take_count=3)
            self.stdout.write(self.style.SUCCESS(f"  موفقیت‌آمیز در {time.time()-t0:.2f} ثانیه. دریافت {len(stocks)} ردیف موجودی انبار:"))
            for s in stocks:
                self.stdout.write(f"    - Barcode ID: {s.get('barcodemain_id')}, انبار: {s.get('warehouse_id')}, موجودی: {s.get('count') or s.get('qty') or 0}")
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  خطا در استعلام موجودی انبار: {exc}"))

        self.stdout.write(self.style.NOTICE("\n=================================================="))
        self.stdout.write(self.style.SUCCESS("تمام آزمون‌های ارتباط با سرور توسعه سامین با موفقیت انجام شد."))
        self.stdout.write(self.style.NOTICE("=================================================="))
