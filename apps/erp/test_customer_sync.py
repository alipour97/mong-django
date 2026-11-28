import io
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.website.models import Customer, Invoice

from . import customer_sync, dadehfa_write
from .models import ErpCoupon, ErpGiftCard, ErpWriteLog, SyncRun
from .tests import FakeDb


@override_settings(ERP_CONNECTOR="dadehfa", ERP_WRITES_ENABLED=True)
class CustomerSyncTests(TestCase):
    mobile = "09120001111"

    def test_signup_queues_an_account_without_waiting_for_a_purchase(self):
        with patch("apps.storefront.account._check_code", return_value=True), patch.object(dadehfa_write, "get_engine") as engine:
            response = APIClient().post(
                "/api/v1/Customer/SignUp",
                {"cellPhone": self.mobile, "confirmationCode": "1234", "firstName": "مریم", "email": "user@example.com"},
                format="json",
            )
            engine.assert_not_called()
            self.assertEqual(response.status_code, 200)
            account = Customer.objects.get(cellphone=self.mobile)
            self.assertIsNotNone(account.erp_customer_pending_at)

            db = FakeDb()
            engine.return_value.begin.return_value = db
            call_command("sync_dadehfa_customers", stdout=io.StringIO())
            call_command("sync_dadehfa_customers", stdout=io.StringIO())

        account.refresh_from_db()
        self.assertEqual(account.erp_customer_id, 101)
        self.assertIsNone(account.erp_customer_pending_at)
        self.assertFalse(Invoice.objects.exists())
        writes = [p for sql, p in db.statements if sql.startswith("INSERT")]
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]["Email"], "user@example.com")
        log = ErpWriteLog.objects.get(customer_id=account.pk)
        self.assertTrue(log.ok)
        self.assertIsNone(log.invoice_id)
        self.assertNotIn("SecretKey", log.params)
        self.assertEqual(SyncRun.objects.filter(job="customers", ok=True).count(), 2)

    def test_retry_reuses_the_customer_already_in_the_legacy_database(self):
        account = Customer.objects.create(cellphone=self.mobile, erp_customer_pending_at=timezone.now())
        with patch.object(dadehfa_write, "get_engine", side_effect=RuntimeError("offline")):
            self.assertFalse(customer_sync.send(account))
        account.refresh_from_db()
        self.assertIsNotNone(account.erp_customer_pending_at)
        db = FakeDb({"FROM Customers": 650})
        with patch.object(dadehfa_write, "get_engine") as engine:
            engine.return_value.begin.return_value = db
            self.assertTrue(customer_sync.send(account))
        account.refresh_from_db()
        self.assertEqual(account.erp_customer_id, 650)
        self.assertIsNone(account.erp_customer_pending_at)
        self.assertFalse(any(sql.startswith("INSERT") for sql, _ in db.statements))
        self.assertEqual(ErpWriteLog.objects.get(customer_id=account.pk).error, "offline")

    def test_backfill_queues_only_active_unlinked_accounts(self):
        waiting = Customer.objects.create(cellphone=self.mobile)
        linked = Customer.objects.create(cellphone="09120002222", erp_customer_id=88)
        inactive = Customer.objects.create(cellphone="09120003333", is_active=False)
        with patch.object(dadehfa_write, "push_customer", return_value=650) as push:
            call_command("sync_dadehfa_customers", "--all", stdout=io.StringIO())
        push.assert_called_once_with(waiting)
        self.assertEqual(Customer.objects.get(pk=waiting.pk).erp_customer_id, 650)
        self.assertEqual(Customer.objects.get(pk=linked.pk).erp_customer_id, 88)
        self.assertIsNone(Customer.objects.get(pk=inactive.pk).erp_customer_pending_at)

    @override_settings(ERP_WRITES_ENABLED=False)
    def test_report_reads_both_databases_when_writes_are_disabled(self):
        ErpCoupon.objects.create(id=31, serial="sample", customer_erp_id=650)
        ErpGiftCard.objects.create(id=32, number="sample", mobile=self.mobile)
        out = io.StringIO()
        with patch(
            "apps.erp.management.commands.sync_dadehfa_customers.fetch_all",
            side_effect=[[{"Id": 650, "LinkedToPos": True}], [{"Coupons": 2, "GiftCards": 3}]],
        ) as read, patch.object(dadehfa_write, "push_customer") as push:
            call_command("sync_dadehfa_customers", "--check-mobile", "+989120001111", stdout=out)
        push.assert_not_called()
        self.assertEqual(read.call_args.args[1], {"mobile": self.mobile})
        self.assertIn("2 کوپن، 3 کارت هدیه", out.getvalue())
        self.assertIn("1 کوپن، 1 کارت هدیه", out.getvalue())
