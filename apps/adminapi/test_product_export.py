from io import BytesIO
from unittest import mock

from django.test import TestCase
from openpyxl import load_workbook
from rest_framework.test import APIClient

from apps.adminapi.models import AdminUser
from apps.erp.models import LebazaiImage
from apps.website.models import HiddenImage, Product, ProductAIProfile, ProductVariant, VariantStock
from apps.adminapi.product_export import product_workbook


class ProductExportTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(AdminUser.objects.create(username="export", cellphone="09120000000"))
        self.product = Product.objects.create(
            title="=SUM(1,2)", barcode="001234", price=1000000, sale_price=750000,
            on_sale=True, description="جزئیات فارسی", attributes={"جنس": "پنبه"},
        )
        ProductAIProfile.objects.create(product=self.product, subcode="000456", title="نام تکمیلی")
        variant = ProductVariant.objects.create(
            product=self.product, barcode="000789", color_id=11, color_name="قرمز", size_id=1, size_name="M",
        )
        VariantStock.objects.create(variant=variant, warehouse_id=2, warehouse_title="آنلاین", qty=3)
        for pos in range(2):
            LebazaiImage.objects.create(product_id=self.product.id, color_id=11, key=f"test/{pos}",
                                        source_url=f"https://example.com/{pos}.jpg", position=pos)
        HiddenImage.objects.create(key="test/1")

    @mock.patch("apps.adminapi.views.auth.AdminView.authentication_classes", [])
    def test_complete_report_ignores_pagination_and_filters(self):
        other = Product.objects.create(title="ناموجود", barcode="002", is_active=False)
        Product.objects.create(title="حذف شده", is_deleted=True)
        response = self.client.get("/api/admin/v1/Products/ExportExcel?pageNumber=2&pageSize=1&Search=missing")
        self.assertEqual(response.status_code, 200)
        self.assertIn(".xlsx", response["Content-Disposition"])
        wb = load_workbook(BytesIO(b"".join(response.streaming_content)))
        self.assertEqual(len(wb.sheetnames), 7)
        sheet = wb["Products"]
        rows = list(sheet.values)
        data = [dict(zip(rows[0], row)) for row in rows[1:]]
        self.assertEqual({r["id"] for r in data}, {self.product.id, other.id})
        row = next(r for r in data if r["id"] == self.product.id)
        for key, expected in {"subcode": "000456", "barcode": "001234", "price (IRR)": 1000000,
                              "sale_price (IRR)": 750000, "description": "جزئیات فارسی",
                              "image_count": 2, "visible_image_count": 1}.items():
            self.assertEqual(row[key], expected)
        self.assertEqual(sheet.cell(2, rows[0].index("title") + 1).data_type, "s")
        self.assertEqual(wb["Colors"].cell(2, 7).value, 2)
        self.assertEqual(wb["Colors"].cell(2, 8).value, 1)
        self.assertEqual(wb["Features"].cell(2, 5).value, "پنبه")
        self.assertEqual(wb["Variants"].max_row, 2)
        self.assertEqual(wb["Warehouse Stock"].max_row, 2)
        self.assertTrue(sheet.sheet_view.rightToLeft)
        self.assertTrue(sheet.auto_filter.ref.endswith("3"))

    def test_export_crosses_batch_boundary(self):
        Product.objects.bulk_create([Product(title=f"Product {i}", barcode=f"00{i}") for i in range(1001)])
        wb = load_workbook(product_workbook(), read_only=True)
        self.assertEqual(sum(1 for _ in wb["Products"].values), 1003)
        wb.close()

    def test_requires_admin_authentication(self):
        self.client.force_authenticate(user=None)
        self.assertIn(self.client.get("/api/admin/v1/Products/ExportExcel").status_code, (401, 403))
