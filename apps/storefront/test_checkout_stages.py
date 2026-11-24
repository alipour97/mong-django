from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from apps.adminapi.views.invoices import _site, _site_header
from apps.storefront.payments import _finish
from apps.website.models import BankGateway, BankInfo, Customer, Invoice, InvoicePayment


class CheckoutStagesTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(cellphone="09120001111")
        self.other = Customer.objects.create(cellphone="09120002222")
        self.invoice = Invoice.objects.create(customer=self.customer)
        self.client = APIClient()
        self.client.force_authenticate(self.customer)
        self.url = "/api/v1/Invoice/CheckoutStage"

    def test_stage_progress_and_admin_visibility(self):
        self.assertEqual(_site_header(_site().get(pk=self.invoice.pk))["checkoutStageTitle"], "در جریان")
        for stage, title in (("checkout", "ثبت سفارش"), ("ready", "آماده پرداخت")):
            response = self.client.post(self.url, {"stage": stage}, format="json")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(_site_header(_site().get(pk=self.invoice.pk))["checkoutStageTitle"], title)
        self.client.post(self.url, {"stage": "checkout"}, format="json")
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.checkout_stage, "checkout")

    def test_browser_cannot_override_payment_or_other_customer(self):
        self.invoice.checkout_stage = "paying"
        self.invoice.save()
        self.client.post(self.url, {"stage": "ready"}, format="json")
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.checkout_stage, "paying")
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(self.url, {"stage": "checkout", "invoiceId": self.invoice.id}, format="json").status_code, 404)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.checkout_stage, "paying")

    @patch("apps.storefront.payments._release_voucher")
    def test_failed_payment_and_old_payment_callback(self, release):
        self.invoice.checkout_stage = "paying"
        self.invoice.save()
        old = InvoicePayment.objects.create(invoice=self.invoice, gateway="zarinpal")
        latest = InvoicePayment.objects.create(invoice=self.invoice, gateway="zarinpal")
        _finish(old, False)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.checkout_stage, "paying")
        _finish(latest, False)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.checkout_stage, "failed")
        self.assertEqual(_site_header(_site().get(pk=self.invoice.pk))["checkoutStageTitle"], "خطا در پرداخت")

    @patch("apps.storefront.payments._release_voucher")
    @patch("apps.storefront.payments._hold_voucher")
    @patch("apps.storefront.payments._enabled", return_value=True)
    @patch("apps.storefront.payments._start_payment", return_value="https://gateway.example/pay")
    def test_start_payment_sets_paying_and_start_failure_sets_failed(self, start, enabled, hold, release):
        self.invoice.payable_amount = 1000
        self.invoice.save()
        bank, _ = BankInfo.objects.get_or_create(key="zarinpal", defaults={"name": "زرین‌پال"})
        gateway = BankGateway.objects.create(bank=bank)
        url = f"/api/v1/Bank/PayInvoiceById?InvoiceId={self.invoice.pk}&GateWayId={gateway.pk}"
        self.assertEqual(self.client.get(url).status_code, 200)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.checkout_stage, "paying")
        start.side_effect = RuntimeError("unavailable")
        with self.assertLogs("apps.storefront.payments", level="ERROR"):
            self.assertEqual(self.client.get(url).status_code, 502)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.checkout_stage, "failed")

    @patch("apps.storefront.payments._mark_paid")
    def test_successful_callback_finalizes(self, mark_paid):
        self.invoice.checkout_stage = "paying"
        self.invoice.save()
        payment = InvoicePayment.objects.create(invoice=self.invoice, gateway="zarinpal")
        _finish(payment, True, test=False)
        mark_paid.assert_called_once()
        payment.refresh_from_db()
        self.assertTrue(payment.is_success)
