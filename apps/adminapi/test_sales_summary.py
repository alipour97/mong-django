from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.adminapi.models import AdminUser
from apps.website.models import Customer, Invoice, InvoiceLine


class SalesSummaryTests(TestCase):
    endpoint = "/api/admin/v1/Dashboard/SalesSummary"

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(AdminUser.objects.create(username="sales-test", cellphone="09120000551"))

    def summary(self, **params):
        response = self.client.get(self.endpoint, params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.json()["data"]["result"]

    @patch("apps.adminapi.views.dashboard.timezone.localdate", return_value=date(2026, 3, 24))
    def test_presets_use_saturday_and_persian_months(self, _localdate):
        ranges = {
            "today": ("2026-03-24", "2026-03-24"),
            "yesterday": ("2026-03-23", "2026-03-23"),
            "thisWeek": ("2026-03-21", "2026-03-24"),
            "lastWeek": ("2026-03-14", "2026-03-20"),
            "thisMonth": ("2026-03-21", "2026-03-24"),
            "lastMonth": ("2026-02-20", "2026-03-20"),
        }
        for period, expected in ranges.items():
            with self.subTest(period=period):
                result = self.summary(period=period)
                self.assertEqual((result["fromDate"], result["toDate"]), expected)
                self.assertEqual(result["invoiceCount"], 0)
                self.assertEqual(result["netSales"], 0)

    def test_totals_and_unique_buyer_counts_use_paid_orders_and_prior_history(self):
        start = timezone.make_aware(datetime(2026, 3, 24))
        end = start + timedelta(days=2)

        def customer(mobile, created, **fields):
            customer = Customer.objects.create(cellphone=mobile, **fields)
            Customer.objects.filter(pk=customer.pk).update(created=created)
            return customer

        def invoice(buyer, paid_at, *, created=None, qty=1, **fields):
            values = dict(state=Invoice.State.SUCCESSFUL, amount=1000, reduction_amount=100,
                          deduction_amount=50, delivery_amount=25, payable_amount=875)
            receipt = Invoice.objects.create(customer=buyer, paid_at=paid_at, **(values | fields))
            Invoice.objects.filter(pk=receipt.pk).update(created=created or paid_at)
            InvoiceLine.objects.create(invoice=receipt, product_id=999, variant_id=1, qty=qty)
            return receipt

        returning = customer("09120000001", start - timedelta(days=30))
        new_buyer = customer("09120000002", start)
        one_purchase = customer("09120000003", end - timedelta(seconds=1))
        customer("09120000004", end)
        customer("09120000005", start, is_deleted=True)
        invoice(returning, start - timedelta(seconds=1))
        first_in_period = invoice(returning, start, created=start - timedelta(days=1), qty=2)
        InvoiceLine.objects.create(invoice=first_in_period, product_id=999, variant_id=2, qty=1)
        invoice(returning, end - timedelta(seconds=1), qty=Decimal("0.50"))
        invoice(new_buyer, start - timedelta(days=1), is_test=True)
        invoice(new_buyer, start + timedelta(hours=1))
        invoice(new_buyer, start + timedelta(hours=2))
        invoice(one_purchase, None, created=start + timedelta(hours=3))
        invoice(one_purchase, start, is_deleted=True)
        invoice(one_purchase, start, state=Invoice.State.SUSPENDED)
        invoice(one_purchase, end, created=start)

        result = self.summary(period="custom", fromDate="2026-03-24", toDate="2026-03-25")
        self.assertEqual(result, {
            "fromDate": "2026-03-24", "toDate": "2026-03-25", "registrations": 2,
            "firstPurchases": 2, "repeatPurchases": 2, "invoiceCount": 5,
            "unitsSold": 6.5, "grossSales": 5000, "discount": 750, "netSales": 4375,
        })

    def test_invalid_ranges_return_bad_request_and_endpoint_requires_admin(self):
        for params in (
            {"period": "year"}, {"period": "custom"},
            {"period": "custom", "fromDate": "2026-02-31", "toDate": "2026-03-01"},
            {"period": "custom", "fromDate": "2026-03-02", "toDate": "2026-03-01"},
        ):
            with self.subTest(params=params):
                self.assertEqual(self.client.get(self.endpoint, params).status_code, 400)
        self.assertEqual(APIClient().get(self.endpoint).status_code, 401)
