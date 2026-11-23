from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.adminapi.models import AdminUser
from apps.adminapi.products import AdminRow
from apps.erp.models import ErpCoupon, ErpGiftCard
from apps.storefront import catalog, warm
from apps.website.models import (
    Article, ArticleComment, ArticleLike, Category, Collection, CooperationRequest, Customer, Invoice,
    InvoiceLine, MediaAttachment, Product, ProductCollection, ProductComment,
)


class AdminSortingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(AdminUser.objects.create(username="sort-test", cellphone="09120000556"))
        self.now = timezone.now()
        self.old = self.now - timedelta(days=2)
        self.category = Category.objects.create(title="آزمایش اصلی", slug="sorting", is_online_active=True)
        self.product = Product.objects.create(title="آزمایش کالا", slug="sorting-item", category=self.category, on_sale=True)
        for key in (catalog.ADMIN_ROWS_CACHE_KEY, catalog.TREE_CACHE_KEY):
            warm.drop(key)
            self.addCleanup(warm.drop, key)

    def assert_order(self, endpoint, columns, low, high, *, method="get", id_key="id", params=None, query=False):
        for column in columns:
            for descending in (False, True):
                first, second = (high, low) if descending else (low, high)
                for page, expected in ((1, first), (2, second)):
                    with self.subTest(endpoint=endpoint, column=column, descending=descending, page=page):
                        filters = {**(params or {}), "SortBy": column, "SortDesc": str(descending).lower(),
                                   "pageSize": 1, "pageNumber": page}
                        base = f"/api/admin/v1/{endpoint}"
                        if method == "get":
                            response = self.client.get(base, filters)
                        elif query:
                            response = self.client.post(base, {}, format="json", query_params=filters)
                        else:
                            response = self.client.post(base, filters, format="json")
                        self.assertEqual(response.status_code, 200, response.data)
                        result = response.json().get("data", response.json())["result"]
                        self.assertEqual([row[id_key] for row in result["items"]], [expected])

    def test_invoices_and_customers(self):
        first = Customer.objects.create(first_name="آزمایش ب", cellphone="09120000101", created=self.old)
        second = Customer.objects.create(first_name="آزمایش پ", cellphone="09120000102", created=self.now)
        older = Invoice.objects.create(customer=second, paid_at=self.old, state=Invoice.State.SUCCESSFUL, payable_amount=10)
        newer = Invoice.objects.create(customer=second, paid_at=self.now, state=Invoice.State.SUCCESSFUL, payable_amount=20)
        Invoice.objects.filter(id=older.id).update(created=self.now)
        Invoice.objects.filter(id=newer.id).update(created=self.old)
        for invoice, qty in ((older, 1), (newer, 2)):
            InvoiceLine.objects.create(invoice=invoice, product=self.product, variant_id=1, qty=qty)
        self.assert_order("Invoice/GetFilteredInvoices", ("qty", "payableAmount", "createDate"), older.id, newer.id)
        self.assert_order("Customer/GetCustomers", ("invoiceCount", "registrationDate"), first.id, second.id, id_key="customerId")
        Customer.objects.filter(id__in=[first.id, second.id]).update(is_bulletin_enabled=True)
        first.email, second.email = "test1@example.test", "test2@example.test"
        first.save(update_fields=["email"])
        second.save(update_fields=["email"])
        self.assert_order("Customer/BulletinMembers", ("fullName",), first.id, second.id, method="post")

    def test_products(self):
        other = Product.objects.create(title="آزمایش کالا دو", slug="sorting-item-2", category=self.category, on_sale=True)
        def row(prod, n):
            return AdminRow(prod.id, prod.title, prod.title, str(n), self.category.id, n > 1,
                            n * 100, n, n * 80, n * 10, n, False, False, False)
        with patch("apps.adminapi.products.admin_rows", return_value=[row(other, 2), row(self.product, 1)]):
            self.assert_order("Products/GetAllProduct", ("price", "reduction", "mediaCount", "qty", "isSaleable"), self.product.id, other.id)

    def test_comments(self):
        for status, date_field in ((1, "confirmedDate"), (2, "rejectedDate")):
            first = ProductComment.objects.create(product=self.product, score=1, status=status, created=self.old, last_modified=self.old)
            second = ProductComment.objects.create(product=self.product, score=5, status=status, created=self.now, last_modified=self.now)
            self.assert_order("ProductComment/GetFilteredComments", ("score", "createDate", date_field), first.id, second.id,
                              params={"Status": status})

    def test_categories_and_collections(self):
        Category.objects.filter(id=self.category.id).update(is_online_active=False)
        other = Category.objects.create(title="آزمایش دوم", slug="sorting-2", is_online_active=True, in_main_page=True)
        leaf = Category.objects.create(title="آزمایش هدف فرعی", slug="sorting-3", parent=other, is_online_active=True, in_main_page=True)
        Product.objects.create(title="فرعی", slug="sorting-other", category=leaf, on_sale=True)
        Product.objects.create(title="فرعی دو", slug="sorting-other-2", category=leaf, on_sale=True)
        MediaAttachment.objects.create(table=MediaAttachment.Table.CATEGORIES, record_id=other.id)
        MediaAttachment.objects.create(table=MediaAttachment.Table.CATEGORIES, record_id=leaf.id)
        self.assert_order("Category/GetParents", ("productCounts", "inMainPage", "isOnlineActive", "hasMedia"),
                          self.category.id, other.id, method="post", params={"isActive": False})
        another = Category.objects.create(title="آزمایش هدف غیرفعال", slug="sorting-4", parent=other, is_online_active=False)
        Category.objects.create(title="آزمایش برگ", slug="sorting-5", parent=leaf, is_online_active=True)
        self.assert_order("Category/GetChildren", ("totalChildrenCount", "inMainPage", "isOnlineActive", "hasMedia"), another.id, leaf.id,
                          method="post", params={"isActive": False, "search": "هدف"})
        first = Collection.objects.create(title="آزمایش یک", created=self.old, beginning_date=self.old, end_date=self.old)
        second = Collection.objects.create(title="آزمایش دو", created=self.now, beginning_date=self.now, end_date=self.now)
        ProductCollection.objects.create(collection=second, product=self.product)
        self.assert_order("Collection/All", ("productCount", "created", "beginningDate", "endDate"), first.id, second.id)

    def test_blog_and_search_sort_values(self):
        first = Article.objects.create(title="آزمایش یک", uniq_url="sort-first", created=self.old, view_count=1, show_on_page=False)
        second = Article.objects.create(title="آزمایش دو", uniq_url="sort-second", created=self.now, view_count=10)
        ArticleComment.objects.create(article=second, status=1)
        ArticleLike.objects.create(article=second, customer_id=9)
        self.assert_order("Article/All", ("createDate", "viewCount", "comment", "likeCount", "showOnPage"), first.id, second.id)
        col = Collection.objects.create(title="آزمایش اول", created=self.now)
        ProductCollection.objects.create(collection=col, product=self.product)
        ProductComment.objects.create(product=self.product, title="آزمایش نظر", status=1, last_modified=self.now)
        result = self.client.get("/api/admin/v1/Dashboard/Search", {"query": "آزمایش"}).data["data"]["result"]
        self.assertEqual(next(x for x in result["articles"] if x["id"] == second.id)["comment"], 1)
        self.assertEqual(result["collections"][0]["productCount"], 1)
        self.assertEqual(result["categories"][0]["depthLevel"], 1)
        self.assertTrue(result["approvedComments"][0]["confirmedDate"])

    def test_coupons_and_gift_cards(self):
        for idx, date in ((1, self.old), (2, self.now)):
            ErpCoupon.objects.create(id=idx, serial=str(idx), reduction=idx, min_price=idx, max_price=idx * 10,
                                     used_at=date, is_active=idx == 2, is_used=idx == 2)
            ErpGiftCard.objects.create(id=idx, number=str(idx), starts=date, expires=date, balance=idx * 10,
                                       min_price=idx, invoice_count=idx, is_active=idx == 2)
        self.assert_order("Coupon/GetAll", ("minPrice", "maxPrice", "reduction", "isUsed", "usedDate", "isActive"), 1, 2)
        self.assert_order("Customer/GetAllGiftCard", ("startDate", "expDate", "gcBalance", "minFactorPrice", "invoiceCount", "isActive"),
                          1, 2, method="post", query=True)

    def test_cooperation(self):
        first = CooperationRequest.objects.create(created=self.old)
        second = CooperationRequest.objects.create(created=self.now)
        for action in ("GetAllCooperationRequests", "GetNewCooperationRequests"):
            self.assert_order(f"Cooperation/{action}", ("submitTime",), first.id, second.id, method="post")
