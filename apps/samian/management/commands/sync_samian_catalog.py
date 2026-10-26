"""
Management command: orchestrates complete catalog synchronization from Samian ERP.
"""
from __future__ import annotations

import logging
import time
from django.core.management import call_command
from django.core.management.base import BaseCommand
from apps.samian import CatalogService, InventoryService
from apps.samian.models import SamianBrand, SamianDepartment, SamianWarehouse

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "همگام‌سازی کامل کاتالوگ سامین (برندها، دپارتمان‌ها، انبارها، محصولات و رنگ‌ها)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-records",
            type=int,
            default=None,
            help="حداکثر رکوردهای تستی دریافتی برای محصولات و رنگ‌ها",
        )

    def handle(self, *args, **options):
        max_records = options.get("max_records")
        t0 = time.time()
        self.stdout.write(self.style.NOTICE("=================================================="))
        self.stdout.write(self.style.NOTICE("  آغاز همگام‌سازی جامع کاتالوگ سامین ERP"))
        self.stdout.write(self.style.NOTICE("=================================================="))

        catalog = CatalogService()
        inventory = InventoryService()

        # 1. Sync Brands
        self.stdout.write("\n۱. همگام‌سازی برندها (/v2/product/codingbrand)...")
        brands = catalog.get_brands()
        brand_objs = [
            SamianBrand(
                samian_id=int(b["codingbrand_id"]),
                title=str(b.get("title") or "").strip(),
                title_en=str(b.get("titleen") or "").strip(),
                brand_code=str(b.get("brandcode") or "").strip(),
                erp_code=str(b.get("erpcode") or "").strip(),
                supplier_name=str(b.get("__supplieraccount_id_value") or "").strip(),
                raw_data={},
            )
            for b in brands if b.get("codingbrand_id")
        ]
        SamianBrand.objects.bulk_create(
            brand_objs,
            update_conflicts=True,
            unique_fields=["samian_id"],
            update_fields=["title", "title_en", "brand_code", "erp_code", "supplier_name", "updated_at"],
        )
        self.stdout.write(self.style.SUCCESS(f"  ثبت {len(brand_objs)} برند در دیتابیس."))

        # 2. Sync Departments
        self.stdout.write("\n۲. همگام‌سازی ساختار دپارتمان‌ها (/v2/product/codingdepartment)...")
        dept_paths = catalog.get_department_paths()
        depts = catalog.get_departments()
        dept_objs = [
            SamianDepartment(
                samian_id=int(d["codingdepartment_id"]),
                title=str(d.get("title") or "").strip(),
                level=int(d["currentlevel"]) if d.get("currentlevel") is not None else 0,
                department1=dept_paths.get(int(d["codingdepartment_id"]), ("", "", ""))[0],
                department2=dept_paths.get(int(d["codingdepartment_id"]), ("", "", ""))[1],
                department3=dept_paths.get(int(d["codingdepartment_id"]), ("", "", ""))[2],
                raw_data={},
            )
            for d in depts if d.get("codingdepartment_id")
        ]
        SamianDepartment.objects.bulk_create(
            dept_objs,
            update_conflicts=True,
            unique_fields=["samian_id"],
            update_fields=["title", "level", "department1", "department2", "department3", "updated_at"],
        )
        self.stdout.write(self.style.SUCCESS(f"  ثبت {len(dept_objs)} دپارتمان در دیتابیس."))

        # 3. Sync Warehouses
        self.stdout.write("\n۳. همگام‌سازی انبارها (/v2/accounting/warehouse)...")
        warehouses = inventory.get_warehouses()
        wh_objs = [
            SamianWarehouse(
                samian_id=int(w["warehouse_id"] or w["id"]),
                title=str(w.get("warehousetitle") or "").strip(),
                department_id=int(w["departmentinfo_id"]) if w.get("departmentinfo_id") else None,
                is_active=bool(w.get("isactive", True)),
                raw_data={},
            )
            for w in warehouses if w.get("warehouse_id") or w.get("id")
        ]
        SamianWarehouse.objects.bulk_create(
            wh_objs,
            update_conflicts=True,
            unique_fields=["samian_id"],
            update_fields=["title", "department_id", "is_active", "updated_at"],
        )
        self.stdout.write(self.style.SUCCESS(f"  ثبت {len(wh_objs)} انبار در دیتابیس."))

        # 4. Sync Products
        self.stdout.write("\n۴. فراخوانی دستور همگام‌سازی محصولات...")
        call_command("sync_samian_products", max_records=max_records)

        # 5. Sync Colors
        self.stdout.write("\n۵. فراخوانی دستور همگام‌سازی رنگ‌ها و گالری...")
        call_command("sync_samian_product_colors", max_records=max_records)

        total_duration = time.time() - t0
        self.stdout.write(self.style.NOTICE("\n=================================================="))
        self.stdout.write(self.style.SUCCESS(f"کاتالوگ جامع سامین در {total_duration:.1f} ثانیه همگام‌سازی گردید."))
        self.stdout.write(self.style.NOTICE("=================================================="))
