from datetime import timedelta
from io import BytesIO
from unittest.mock import call, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.adminapi.models import AdminUser
from apps.samian.models import SamianSalesRow, SamianSalesTransaction
from apps.website.models import CARD_TRANSFER, BankGateway, BankInfo, CardTransferReceipt, Customer, Invoice


class CardTransferTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(cellphone="09120001111")
        self.admin = AdminUser.objects.create(username="reviewer", cellphone="09120002222")
        self.invoice = Invoice.objects.create(customer=self.customer, payable_amount=500000, number="40508101")
        self.customer_client = APIClient()
        self.customer_client.force_authenticate(self.customer)
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(self.admin)
        self.gateway = BankGateway.objects.create(
            bank=BankInfo.objects.get(key=CARD_TRANSFER), card_number="6037991234567890", instructions="تصویر رسید را بفرستید.",
        )

    def submit(self, client=None, content=None, amount=None):
        if content is None:
            buffer = BytesIO()
            Image.new("RGB", (32, 24)).save(buffer, "PNG")
            content = buffer.getvalue()
        return (client or self.customer_client).post(
            f"/api/v1/Bank/CardTransfer/{self.invoice.pk}",
            {"gatewayId": self.gateway.pk, "amount": amount or self.invoice.payable_amount,
             "receipt": SimpleUploadedFile("receipt.png", content, content_type="image/png")},
            format="multipart",
        )

    def image_url(self, payment):
        return f"/api/admin/v1/Invoice/CardTransfer/{payment.pk}/Image"

    def decide(self, payment, approved):
        return self.admin_client.post(
            f"/api/admin/v1/Invoice/CardTransfer/{payment.pk}/Review", {"approved": approved}, format="json",
        )

    @override_settings(SMSIR_CARD_TRANSFER_RECEIVED_TEMPLATE_ID=33, SMSIR_CARD_TRANSFER_APPROVED_TEMPLATE_ID=34)
    def test_approval_is_idempotent_and_hands_invoice_to_existing_outbox(self):
        # Run the SMS worker inline so the provider failure can be observed in the test.
        with patch("apps.storefront.card_transfers.threading.Thread") as worker, \
                patch("apps.storefront.card_transfers.smsir.send_verify", side_effect=RuntimeError("provider unavailable")) as sms, \
                patch("apps.storefront.payments.outbox.send_soon") as outbox, \
                patch("apps.storefront.payments.catalog.clear_caches"):
            worker.side_effect = lambda target, **kwargs: type("Worker", (), {"start": staticmethod(target)})()
            with self.assertLogs("apps.storefront.card_transfers", "ERROR"), self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.submit().status_code, 200)
            payment = self.invoice.payments.get()
            self.invoice.refresh_from_db()
            self.assertEqual(self.invoice.state, Invoice.State.SUSPENDED)
            self.assertFalse(payment.is_success)
            outbox.assert_not_called()

            self.assertEqual(self.submit().status_code, 200)
            self.assertEqual(self.invoice.payments.count(), 1)
            self.assertEqual(self.admin_client.get(self.image_url(payment))["Content-Type"], "image/jpeg")
            self.assertIn(self.customer_client.get(self.image_url(payment)).status_code, (401, 403))
            customer_orders = self.customer_client.get("/api/v1/Invoice/GetAllCustomerInvoice", {
                "invoiceType": 1, "includeSuspended": "true",
            })
            self.assertEqual(customer_orders.data["result"]["data"]["preInvoice"][0]["cardTransferStatus"], "pending")
            self.assertEqual(
                self.admin_client.get(f"/api/admin/v1/Invoice/InvoiceDetails/{self.invoice.pk}").data["data"]["result"]["cardTransfers"],
                [{"id": payment.pk, "amount": payment.amount, "status": "pending"}],
            )

            with self.assertLogs("apps.storefront.card_transfers", "ERROR"), self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.decide(payment, True).status_code, 200)
            self.assertEqual(self.decide(payment, True).status_code, 200)
            self.assertEqual(self.decide(payment, False).status_code, 409)
            self.invoice.refresh_from_db()
            payment.refresh_from_db()
            self.assertEqual(self.invoice.state, Invoice.State.SUCCESSFUL)
            self.assertTrue(payment.is_success)
            self.assertEqual(CardTransferReceipt.objects.get(payment=payment).reviewed_by, self.admin)
            outbox.assert_called_once_with(self.invoice.pk)
            self.assertEqual([call.args[1] for call in sms.call_args_list], [33, 34])

    def test_rejection_cancels_without_sending_to_erp_or_sms(self):
        self.assertEqual(self.submit().status_code, 200)
        payment = self.invoice.payments.get()
        with patch("apps.storefront.payments.outbox.send_soon") as outbox, \
                patch("apps.storefront.card_transfers._notify") as notify, self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.decide(payment, False).status_code, 200)
        self.invoice.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(self.invoice.state, Invoice.State.CANCELLED)
        self.assertFalse(payment.is_success)
        self.assertIsNotNone(payment.verified_at)
        outbox.assert_not_called()
        notify.assert_not_called()

    @override_settings(SMSIR_CARD_TRANSFER_RECEIVED_TEMPLATE_ID=159473, SMSIR_CARD_TRANSFER_PARAM="ORDER")
    def test_receipt_notifies_customer_and_admins_with_invoice_sms_enabled_once(self):
        self.admin.send_invoice_sms = True
        self.admin.save(update_fields=["send_invoice_sms"])
        AdminUser.objects.create(username="muted", cellphone="09120003333")
        AdminUser.objects.create(username="inactive", cellphone="09120004444", send_invoice_sms=True, is_active=False)
        AdminUser.objects.create(username="buyer", cellphone="+989120001111", send_invoice_sms=True)
        with patch("apps.storefront.card_transfers.threading.Thread") as worker, \
                patch("apps.storefront.card_transfers.smsir.send_verify", return_value=True) as sms:
            worker.side_effect = lambda target, **kwargs: type("Worker", (), {"start": staticmethod(target)})()
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.submit().status_code, 200)
                self.assertEqual(self.submit().status_code, 200)
            self.assertEqual(sms.call_args_list, [
                call(self.customer.cellphone, 159473, {"ORDER": self.invoice.number}),
                call(self.admin.cellphone, 159473, {"ORDER": self.invoice.number}),
            ])

    def test_success_view_can_include_pending_card_transfers_with_their_real_state(self):
        self.assertEqual(self.submit().status_code, 200)
        paid = Invoice.objects.create(customer=self.customer, state=Invoice.State.SUCCESSFUL)
        Invoice.objects.create(customer=self.customer, state=Invoice.State.SUSPENDED)

        def listed(**params):
            response = self.admin_client.get("/api/admin/v1/Invoice/GetFilteredInvoices", {"InvoiceState": 3, **params})
            return {row["id"]: row for row in response.data["data"]["result"]["items"]}

        self.assertEqual(set(listed()), {paid.pk})
        rows = listed(IncludePendingCardTransfers="true")
        self.assertEqual(set(rows), {paid.pk, self.invoice.pk})
        self.assertEqual(rows[self.invoice.pk]["invoiceState"], Invoice.State.SUSPENDED)
        self.assertEqual(rows[self.invoice.pk]["paymentType"], "کارت‌به‌کارت · در انتظار بررسی")

        self.assertEqual(self.decide(self.invoice.payments.get(), False).status_code, 200)
        self.assertEqual(set(listed(IncludePendingCardTransfers="true")), {paid.pk})

    def test_invoice_date_filters_and_sort_use_the_payment_date(self):
        today = timezone.now()
        older_invoice = Invoice.objects.create(customer=self.customer, state=Invoice.State.SUCCESSFUL,
                                               paid_at=today - timedelta(days=1))
        Invoice.objects.filter(pk=self.invoice.pk).update(state=Invoice.State.SUCCESSFUL, paid_at=today,
                                                          created=today - timedelta(days=3), reduction_amount=20000)
        url = "/api/admin/v1/Invoice/GetFilteredInvoices"
        rows = self.admin_client.get(url, {"InvoiceState": 3}).data["data"]["result"]["items"]
        self.assertEqual([row["id"] for row in rows], [self.invoice.pk, older_invoice.pk])
        self.assertEqual(rows[0]["createDate"], today.isoformat())
        day = timezone.localdate(today).isoformat()
        filtered = self.admin_client.get(url, {"InvoiceState": 3, "FromDate": day, "ToDate": day})
        self.assertEqual([row["id"] for row in filtered.data["data"]["result"]["items"]], [self.invoice.pk])
        stats = self.admin_client.get("/api/admin/v1/Invoice/GetInvoiceStatistics", {
            "invoiceState": 3, "FromDate": day, "ToDate": day,
        }).data["data"]["result"]
        self.assertEqual(stats, {"totalCount": 1, "recentInvoicesCount": 1, "commentInvoicesCount": 0, "discountInvoicesCount": 1})

    def test_synced_invoice_keeps_its_site_payment_date(self):
        paid_at = timezone.now()
        receipt = SamianSalesTransaction.objects.create(
            samian_id=598, store_order_id=self.invoice.pk, order_web_status_id=2,
            order_date=paid_at - timedelta(days=4), transaction_date=paid_at - timedelta(days=1),
        )
        SamianSalesRow.objects.create(samian_id=499, transaction=receipt, discount_amount=1000)
        Invoice.objects.filter(pk=self.invoice.pk).update(
            state=Invoice.State.SUCCESSFUL, paid_at=paid_at, samian_transaction_id=receipt.samian_id,
        )
        day = timezone.localdate(paid_at).isoformat()
        response = self.admin_client.get("/api/admin/v1/Invoice/GetFilteredInvoices", {
            "InvoiceState": 3, "FromDate": day, "ToDate": day,
        })
        rows = response.data["data"]["result"]["items"]
        self.assertEqual([(row["id"], row["createDate"]) for row in rows], [(receipt.samian_id, paid_at.isoformat())])
        stats = self.admin_client.get("/api/admin/v1/Invoice/GetInvoiceStatistics", {
            "invoiceState": 3, "FromDate": day, "ToDate": day,
        }).data["data"]["result"]
        self.assertEqual((stats["totalCount"], stats["recentInvoicesCount"], stats["discountInvoicesCount"]), (1, 1, 1))

    def test_upload_rejects_foreign_invoice_invalid_image_and_stale_amount(self):
        other = APIClient()
        other.force_authenticate(Customer.objects.create(cellphone="09120003333"))
        self.assertEqual(self.submit(client=other).status_code, 404)
        self.assertEqual(self.submit(content=b"<svg></svg>").status_code, 400)
        self.assertEqual(self.submit(amount=10).status_code, 409)
        self.assertFalse(self.invoice.payments.exists())

    def test_gateway_editor_publishes_the_card_and_instructions(self):
        settings_url = "/api/admin/v1/Bank/UpdateBankGateway"
        fields = {"id": self.gateway.pk, "bankId": self.gateway.bank_id, "instructions": "رسید را ارسال کنید."}
        self.assertEqual(self.admin_client.post(settings_url, {**fields, "cardNumber": "۱۲۳"}, format="json").status_code, 400)
        response = self.admin_client.post(settings_url, {**fields, "cardNumber": "۶۰۳۷-۹۹۱۲-۳۴۵۶-۷۸۹۱"}, format="json")
        self.assertEqual(response.status_code, 200)
        gateways = self.customer_client.get("/api/v1/Bank/GetGateways").data["result"]["data"]
        transfer = next(gateway for gateway in gateways if gateway["gatewayKey"] == CARD_TRANSFER)
        self.assertEqual((transfer["cardNumber"], transfer["instructions"]), ("6037991234567891", fields["instructions"]))

    def test_gateway_priority_and_removal_apply_to_checkout(self):
        bank, _ = BankInfo.objects.get_or_create(key="zarinpal", defaults={"name": "زرین‌پال"})
        online = BankGateway.objects.create(bank=bank, merchant="12345678-1234-1234-1234-123456789012")
        admin_url = "/api/admin/v1/Bank"
        checkout_url = "/api/v1/Bank/GetGateways"

        fields = {
            "id": self.gateway.pk, "bankId": self.gateway.bank_id,
            "cardNumber": self.gateway.card_number,
        }
        response = self.admin_client.post(f"{admin_url}/UpdateBankGateway", {
            **fields, "displayPriority": 0,
        }, format="json")
        self.assertEqual(response.status_code, 400)
        response = self.admin_client.post(f"{admin_url}/UpdateBankGateway", {
            **fields, "displayPriority": 1,
        }, format="json")
        self.assertEqual(response.status_code, 200)
        rows = self.admin_client.get(f"{admin_url}/GetGateway").data["data"]["result"]
        self.assertEqual((rows[0]["id"], rows[0]["displayPriority"]), (self.gateway.pk, 1))
        gateways = self.customer_client.get(checkout_url).data["result"]["data"]
        self.assertEqual([gateway["id"] for gateway in gateways], [self.gateway.pk, online.pk])

        response = self.admin_client.delete(f"{admin_url}/Gateways/{self.gateway.pk}")
        self.assertEqual(response.status_code, 200)
        response = self.admin_client.get(f"{admin_url}/SoftDelete", {"gatewayId": self.gateway.pk, "active": "true"})
        self.assertEqual(response.status_code, 404)
        rows = self.admin_client.get(f"{admin_url}/GetGateway").data["data"]["result"]
        self.assertNotIn(self.gateway.pk, [row["id"] for row in rows])
        gateways = self.customer_client.get(checkout_url).data["result"]["data"]
        self.assertEqual([gateway["id"] for gateway in gateways], [online.pk])
        self.gateway.refresh_from_db()
        self.assertIsNotNone(self.gateway.removed_at)

        response = self.admin_client.post(f"{admin_url}/AddBankGateway", {
            "bankId": self.gateway.bank_id, "cardNumber": self.gateway.card_number,
        }, format="json")
        self.assertEqual(response.status_code, 200)
