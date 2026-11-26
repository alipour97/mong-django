from datetime import timedelta
from uuid import uuid4

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.adminapi.models import AdminUser
from apps.website.models import City, Customer, Invoice, Product, ProductVariant, Province, StoreActivity, StoreVisitor


class StoreActivityTests(TestCase):
    def setUp(self):
        self.shop = APIClient()
        self.panel = APIClient()
        self.panel.force_authenticate(AdminUser.objects.create(username="activity", cellphone="09120000001"))
        self.product = Product.objects.create(title="شلوار لینن", slug="linen-activity")
        self.variant = ProductVariant.objects.create(product=self.product)
        self.customer = Customer.objects.create(cellphone="09120000002")
        self.customer.set_password("linen-password")
        self.customer.save(update_fields=["password"])
        self.visitor_id = str(uuid4())

    def _record(self, kind, visitor=None):
        return self.shop.post("/api/v1/Activity/Product", {
            "visitorId": visitor or self.visitor_id, "kind": kind,
            "productId": self.product.pk, "variantId": self.variant.pk,
        }, format="json")

    def _items(self, path, **params):
        response = self.panel.get("/api/admin/v1/Invoice/" + path, params)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["data"]["result"]["items"]

    def test_guest_history_moves_to_invoice_after_successful_login(self):
        self.assertEqual(self._record("product_view").status_code, 200)
        self.assertEqual(self._record("cart_add").status_code, 200)
        self.assertEqual(self._record("cart_add", str(uuid4())).status_code, 200)
        guests = self._items("GuestVisitors", product="لینن")
        self.assertEqual(len(guests), 1)
        self.assertEqual(guests[0]["viewCount"], 1)
        self.assertEqual(self._items("GuestVisitors", product="نام دیگر"), [])
        self.assertEqual(self.shop.get("/api/admin/v1/Invoice/GuestVisitors").status_code, 401)
        guest_id = guests[0]["id"]
        self.assertEqual(len(self._items(f"GuestVisitors/{guest_id}/Activity")), 2)

        response = self.shop.post("/api/v1/Authentication/CustomerAuthenticate", {
            "cellPhone": self.customer.cellphone, "password": "linen-password", "visitorId": self.visitor_id,
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.shop.credentials(HTTP_AUTHORIZATION=f"Bearer {response.json()['result']['data']['token']}")
        self.assertEqual(self._items("GuestVisitors"), [])
        self.assertEqual(self.panel.get(f"/api/admin/v1/Invoice/GuestVisitors/{guest_id}/Activity").status_code, 404)
        invoice = Invoice.objects.create(customer=self.customer)
        province = Province.objects.create(name="تهران")
        city = City.objects.create(name="تهران", province=province)
        self.assertEqual(self.shop.post("/api/v1/Customer/AddCustomerAddress", {
            "provinceId": province.pk, "cityId": city.pk, "address": "نشانی آزمایشی",
        }, format="json").status_code, 200)
        for stage in ("checkout", "ready", "ready"):
            response = self.shop.post("/api/v1/Invoice/CheckoutStage", {"stage": stage}, format="json")
            self.assertEqual(response.status_code, 200)
        invoice.refresh_from_db()
        events = self._items(f"Activity/{invoice.pk}")
        self.assertEqual([event["label"] for event in events], [
            "مشاهده کالا", "افزودن به سبد", "ایجاد سبد سفارش", "افزودن آدرس", "ثبت سفارش", "آماده پرداخت",
        ])
        self.assertEqual(events[0]["detail"], self.product.title)
        self.assertEqual(events[3]["detail"], "")
        self.assertEqual(events[-1]["at"], invoice.status_changed_at.isoformat())
        self.assertEqual(self._items("GetFilteredInvoices")[0]["statusChangedAt"], events[-1]["at"])

    def test_invoice_history_is_bounded_by_order_and_customer(self):
        now = timezone.now()
        previous = Invoice.objects.create(customer=self.customer, state=Invoice.State.SUCCESSFUL, paid_at=now - timedelta(hours=1))
        Invoice.objects.filter(pk=previous.pk).update(created=now - timedelta(hours=2))
        invoice = Invoice.objects.create(customer=self.customer, state=Invoice.State.SUCCESSFUL, paid_at=now)
        visitor = StoreVisitor.objects.create(browser_id=uuid4(), customer=self.customer, identified_at=now - timedelta(minutes=10))
        for minutes, detail in ((-90, "قبلی"), (-30, "مرتبط"), (-5, "مهمان پس از ورود")):
            StoreActivity.objects.create(
                kind=StoreActivity.Kind.PRODUCT_VIEW, visitor=visitor, detail=detail, occurred_at=now + timedelta(minutes=minutes),
            )
        other = Customer.objects.create(cellphone="09120000003")
        StoreActivity.objects.create(kind=StoreActivity.Kind.CART_ADD, visitor=visitor, customer=other, detail="کاربر دیگر")
        events = self._items(f"Activity/{invoice.pk}")
        self.assertEqual([event["detail"] for event in events if event["detail"]], ["مرتبط"])
        self.assertIn("تأیید پرداخت", [event["label"] for event in events])
