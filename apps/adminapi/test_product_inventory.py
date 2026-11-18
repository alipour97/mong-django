from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.adminapi.models import AdminUser
from apps.storefront import catalog, warm
from apps.website.models import Category, Product, ProductVariant, SiteSetting, VariantStock


@override_settings(ERP_CONNECTOR="dadehfa", DADEHFA_STOREFRONT_WAREHOUSE_IDS=[2, 3])
class ProductInventoryTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(AdminUser.objects.create(username="inventory", cellphone="09120000001"))
        self.category = Category.objects.create(title="لباس", slug="clothes", is_online_active=True)
        self.product = Product.objects.create(title="لباس تست", slug="test", barcode="001",
                                              category=self.category, on_sale=True, price=1000000, sale_price=1000000)
        self.small = ProductVariant.objects.create(product=self.product, barcode="00138", color_id=1,
                                                   color_name="مشکی", size_id=38, size_name="38")
        self.large = ProductVariant.objects.create(product=self.product, barcode="00140", color_id=1,
                                                   color_name="مشکی", size_id=40, size_name="40")
        self.empty = ProductVariant.objects.create(product=self.product, barcode="00142", color_id=1,
                                                   color_name="مشکی", size_id=42, size_name="42")
        for variant, warehouse, title, qty in (
            (self.small, 2, "گلسار", 5), (self.small, 3, "مروارید", 3),
            (self.large, 2, "گلسار", 7), (self.large, 3, "مروارید", 2),
            (self.small, 10, "خارج از فروش اینترنتی", 100),
        ):
            VariantStock.objects.create(variant=variant, warehouse_id=warehouse, warehouse_title=title, qty=qty)
        for key in (catalog.ADMIN_ROWS_CACHE_KEY, catalog.TREE_CACHE_KEY):
            warm.drop(key)
            self.addCleanup(warm.drop, key)

    def list(self, **params):
        return self.client.get("/api/admin/v1/Products/GetAllProduct", params).json()["data"]["result"]["items"]

    def test_list_includes_numeric_totals_for_each_online_warehouse(self):
        row = self.list()[0]
        self.assertEqual(row["qty"], 17)
        self.assertEqual({w["id"]: w["qty"] for w in row["warehouses"]}, {2: 12, 3: 5})

    def test_details_include_zero_stock_sizes_and_variant_codes(self):
        SiteSetting.objects.create(min_qty=1)
        response = self.client.get(f"/api/admin/v1/Products/GetDetailProduct/{self.product.id}")
        sizes = response.json()["data"]["result"]["details"][1]["items"]
        rows = {row["name"]: row for row in sizes}
        self.assertEqual(set(rows), {"38", "40", "42"})
        self.assertEqual(rows["38"]["barcode"], "00138")
        self.assertEqual(rows["38"]["mojodi"], 7)
        self.assertEqual(rows["38"]["realQty"], 8)
        self.assertEqual({w["warehouseId"]: w["realQty"] for w in rows["38"]["warehouses"]}, {2: 5, 3: 3})
        self.assertEqual(rows["42"]["mojodi"], 0)

    def test_quantity_sort_is_applied_before_pagination_in_both_directions(self):
        other = Product.objects.create(title="ناموجود", slug="empty", barcode="002", category=self.category,
                                       on_sale=True, price=1000000, sale_price=1000000)
        warm.drop(catalog.ADMIN_ROWS_CACHE_KEY)
        self.assertEqual(self.list(SortBy="qty", SortDesc="true", pageSize=1)[0]["id"], self.product.id)
        self.assertEqual(self.list(SortBy="qty", SortDesc="false", pageSize=1)[0]["id"], other.id)
