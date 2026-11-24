"""Official Mellat protocol and checkout regression tests; all HTTP is mocked."""
from datetime import timedelta
from unittest import mock
from xml.etree import ElementTree as ET

import requests
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.adminapi.models import AdminUser
from apps.website.models import BankGateway, BankInfo, Customer, Invoice, InvoiceLine, InvoicePayment

from . import mellat, service
from .models import PayRecord

S = PayRecord.State
HUB = "https://hub.test"
SITE = "https://site.test"


def soap(method, value="0", status=200):
    content = (f'<s:Envelope xmlns:s="{mellat.SOAP}"><s:Body>'
               f'<m:{method}Response xmlns:m="{mellat.NAMESPACE}"><return>{value}</return>'
               f'</m:{method}Response></s:Body></s:Envelope>').encode()
    return mock.Mock(status_code=status, content=content)


CONFIG = dict(MELLAT_SANDBOX=True, MELLAT_TERMINAL_ID="1234", MELLAT_USERNAME="test-user",
              MELLAT_PASSWORD="secret<&", PAYHUB_PUBLIC_URL=HUB, SITE_URL=SITE, PUBLIC_BASE_URL=SITE,
              PAYHUB_ALLOWED_CALLBACK_HOSTS=["site.test"], PAYHUB_OLD_HUB_URL="",
              CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})


@override_settings(**CONFIG)
class MellatProtocolTests(SimpleTestCase):
    def test_soap_request_is_test_only_and_uses_documented_names_and_rial(self):
        with mock.patch("apps.payhub.mellat.requests.post", return_value=soap("bpPayRequest", "0,AbCd123")) as post:
            reply = mellat.request("1234", True, "81", 150000, "https://site.test/return?a=1&b=2", "فاکتور")
        self.assertEqual((reply.code, reply.authority), (0, "AbCd123"))
        self.assertEqual(post.call_args.args[0], mellat.TEST_BASE + "/services/pgw")
        args = post.call_args.kwargs
        self.assertFalse(args["allow_redirects"])
        self.assertEqual(args["timeout"], 30)
        body = ET.fromstring(args["data"]).find(f"{{{mellat.SOAP}}}Body/{{{mellat.NAMESPACE}}}bpPayRequest")
        params = {child.tag: child.text for child in body}
        self.assertEqual(params["userPassword"], "secret<&")
        self.assertEqual(params["callBackUrl"], "https://site.test/return?a=1&b=2")
        self.assertEqual((params["amount"], params["payerId"], params["orderId"]), ("150000", "0", "81"))
        self.assertRegex(params["localDate"], r"^[0-9]{8}$")
        self.assertRegex(params["localTime"], r"^[0-9]{6}$")

    def test_network_failure_fault_html_and_malformed_xml_are_not_success(self):
        answers = [requests.Timeout(), soap("wrongMethod"), soap("bpPayRequest", "0,"),
                   soap("bpPayRequest", "0,AbC", 500), mock.Mock(status_code=200, content=b"<html>bad</html>"),
                   mock.Mock(status_code=200, content=b'<!DOCTYPE r [<!ENTITY x "x">]><r>&x;</r>'),
                   mock.Mock(status_code=200, content=b"<broken"),
                   mock.Mock(status_code=302, content=b"")]
        for answer in answers:
            with self.subTest(answer=answer), mock.patch("apps.payhub.mellat.requests.post") as post:
                if isinstance(answer, Exception):
                    post.side_effect = answer
                else:
                    post.return_value = answer
                result = mellat.request("1234", True, "81", 150000, "https://site.test/return", "test")
                self.assertIn(result.code, (mellat.NO_ANSWER, mellat.BAD_REPLY))


@override_settings(**CONFIG)
class MellatCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.methods = []
        self.answers = {}
        self.http = mock.patch("apps.payhub.mellat.requests.post", side_effect=self.fake).start()
        self.addCleanup(mock.patch.stopall)

    def fake(self, url, **kwargs):
        self.assertEqual(url, mellat.TEST_BASE + "/services/pgw")
        operation = list(ET.fromstring(kwargs["data"]).find(f"{{{mellat.SOAP}}}Body"))[0]
        method = operation.tag.split("}")[-1]
        self.methods.append(method)
        answers = self.answers.get(method, ["0,AbCd123" if method == "bpPayRequest" else "0"])
        answer = answers.pop(0) if len(answers) > 1 else answers[0]
        if isinstance(answer, Exception):
            raise answer
        return soap(method, answer)

    def started(self):
        record = service.create(gateway="mellat", amount=150000, success=SITE + "/success", failed=SITE + "/failed",
                                customer_key="42")
        service.start_mellat(record, "71", 150000)
        return record

    def fields(self, record, **extra):
        return {"RefId": record.authority, "ResCode": "0", "SaleOrderId": record.gateway_transaction_id,
                "SaleReferenceId": "987654321", "CardHolderPan": "610433******5689", **extra}

    def returned(self):
        record = self.started()
        response = self.client.post(f"/mellat/callback/{record.token}", self.fields(record))
        self.assertEqual(response.status_code, 302)
        record.refresh_from_db()
        return record


class MellatFlowTests(MellatCase):
    def test_checkout_post_form_uses_official_dev_host_and_mode_is_pinned(self):
        record = self.started()
        with override_settings(MELLAT_SANDBOX=False):
            page = self.client.get(f"/mellat/pay/{record.token}")
        self.assertContains(page, 'method="post"')
        self.assertContains(page, mellat.TEST_BASE + "/startpay.mellat")
        self.assertIn(f"form-action {mellat.TEST_BASE}/startpay.mellat;", page["Content-Security-Policy"])
        self.assertContains(page, 'name="RefId" value="AbCd123"')
        self.assertNotContains(page, "bpm.shaparak.ir")
        self.assertEqual(page["Cache-Control"], "no-store")
        self.assertEqual(self.methods, ["bpPayRequest"])
        self.assertEqual(service.start_mellat(record, "71", 150000), service.mellat_page_url(record))
        self.assertEqual(self.methods, ["bpPayRequest"])

    def test_live_form_policy_allows_the_exact_post_target(self):
        record = self.started()
        PayRecord.objects.filter(pk=record.pk).update(mellat_sandbox=False)
        page = self.client.get(f"/mellat/pay/{record.token}")
        action = f"{mellat.LIVE_BASE}/startpay.mellat"
        self.assertContains(page, f'action="{action}"')
        self.assertIn(f"form-action {action};", page["Content-Security-Policy"])
        self.assertNotIn(mellat.TEST_BASE, page["Content-Security-Policy"])
        self.assertEqual(self.methods, ["bpPayRequest"])

    def test_success_verifies_then_settles_exactly_once(self):
        record = self.returned()
        self.assertEqual(record.state, S.RETURNED)
        self.assertEqual(self.methods, ["bpPayRequest"])
        self.assertEqual(service.confirm(record, "71", 150000)["status"], "ok")
        self.assertEqual((record.ref_id, record.card_pan, record.state), ("987654321", "610433******5689", S.CONSUMED))
        self.assertEqual(service.confirm(record, "71", 150000)["status"], "duplicate")
        self.assertEqual(self.methods, ["bpPayRequest", "bpVerifyRequest", "bpSettleRequest"])
        replay = self.client.post(f"/mellat/callback/{record.token}", self.fields(record))
        self.assertEqual(replay.status_code, 302)
        self.assertEqual(len(self.methods), 3)
        self.assertNotIn("secret", str(record.events))

    def test_callback_identifiers_are_checked_before_any_bank_operation_even_after_success(self):
        record = self.started()
        for state in (S.REDIRECTED, S.CONSUMED):
            PayRecord.objects.filter(pk=record.pk).update(state=state)
            for fields in ({"RefId": "abcd123"}, {"SaleOrderId": "999"}, {"SaleReferenceId": "0"}, {"ResCode": ""}):
                with self.subTest(state=state, fields=fields):
                    response = self.client.post(f"/mellat/callback/{record.token}", self.fields(record, **fields))
                    self.assertEqual(response.status_code, 400)
        self.assertEqual(self.methods, ["bpPayRequest"])

    def test_cancel_does_not_verify_or_settle(self):
        record = self.started()
        response = self.client.post(f"/mellat/callback/{record.token}", self.fields(record, ResCode="17", SaleReferenceId=""))
        self.assertIn("/failed", response["Location"])
        record.refresh_from_db()
        self.assertEqual(record.state, S.FAILED)
        self.assertEqual(service.confirm(record, "71", 150000)["status"], "not_paid")
        self.assertEqual(self.methods, ["bpPayRequest"])

    def test_amount_invoice_and_reference_cannot_be_replaced(self):
        record = self.returned()
        self.assertEqual(service.confirm(record, "72", 150000)["status"], "mismatch")
        self.assertEqual(service.confirm(record, "71", 150001)["status"], "mismatch")
        response = self.client.post(f"/mellat/callback/{record.token}", self.fields(record, SaleReferenceId="987654322"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.methods, ["bpPayRequest"])

    def test_already_verified_and_already_settled_are_success(self):
        self.answers = {"bpVerifyRequest": ["43"], "bpSettleRequest": ["45"]}
        record = self.returned()
        self.assertEqual(service.confirm(record, "71", 150000)["status"], "ok")

    def test_verify_timeout_is_retried_then_inquired_before_settlement(self):
        self.answers = {"bpVerifyRequest": [requests.Timeout()], "bpInquiryRequest": ["0"]}
        record = self.returned()
        self.assertEqual(service.confirm(record, "71", 150000)["status"], "ok")
        self.assertEqual(self.methods, ["bpPayRequest", "bpVerifyRequest", "bpVerifyRequest", "bpInquiryRequest", "bpSettleRequest"])

    def test_unresolved_verify_is_reversed_and_not_marked_paid(self):
        self.answers = {"bpVerifyRequest": [requests.Timeout()], "bpInquiryRequest": [requests.Timeout()]}
        record = self.returned()
        self.assertEqual(service.confirm(record, "71", 150000)["status"], "failed")
        self.assertEqual(record.state, S.REVERTED)
        self.assertEqual(self.methods[-1], "bpReversalRequest")
        self.assertNotIn("bpSettleRequest", self.methods)

    def test_settle_timeout_does_not_report_success_and_can_be_retried(self):
        self.answers = {"bpSettleRequest": [requests.Timeout(), "45"], "bpInquiryRequest": [requests.Timeout()]}
        record = self.returned()
        self.assertEqual(service.confirm(record, "71", 150000)["status"], "failed")
        self.assertEqual(record.state, S.RETURNED)
        self.assertEqual(service.confirm(record, "71", 150000)["status"], "ok")
        self.assertNotIn("bpReversalRequest", self.methods)

    def test_settle_timeout_can_be_resolved_by_inquiry(self):
        self.answers = {"bpSettleRequest": [requests.Timeout()], "bpInquiryRequest": ["45"]}
        record = self.returned()
        self.assertEqual(service.confirm(record, "71", 150000)["status"], "ok")

    def test_refunded_payment_never_settles(self):
        self.answers = {"bpVerifyRequest": ["48"]}
        record = self.returned()
        self.assertEqual(service.confirm(record, "71", 150000)["status"], "failed")
        self.assertEqual(record.state, S.REVERTED)
        self.assertNotIn("bpSettleRequest", self.methods)

    def test_request_failure_and_mismatched_amount_do_not_reuse_order(self):
        first = self.started()
        with self.assertRaises(service.Refused):
            service.start_mellat(first, "71", 150001)
        second = self.started()
        self.assertNotEqual(first.gateway_transaction_id, second.gateway_transaction_id)
        self.answers["bpPayRequest"] = ["24"]
        with self.assertRaises(service.Refused):
            self.started()
        self.assertEqual(PayRecord.objects.latest("pk").state, S.FAILED)

    def test_reconciliation_reverses_unconfirmed_payments_using_mellat_only(self):
        record = self.returned()
        PayRecord.objects.filter(pk=record.pk).update(updated=timezone.now() - timedelta(minutes=25))
        self.assertEqual(service.reconcile(), 1)
        record.refresh_from_db()
        self.assertEqual(record.state, S.REVERTED)
        self.assertEqual(self.methods[-3:], ["bpInquiryRequest", "bpVerifyRequest", "bpReversalRequest"])

    def test_reconciliation_leaves_unclaimed_settlement_for_review(self):
        record = self.returned()
        self.answers["bpInquiryRequest"] = ["45"]
        PayRecord.objects.filter(pk=record.pk).update(updated=timezone.now() - timedelta(minutes=25))
        service.reconcile()
        record.refresh_from_db()
        self.assertEqual(record.state, S.REVIEW)
        self.assertNotIn("bpReversalRequest", self.methods)

    def test_legacy_contract_can_start_mellat_in_test_mode(self):
        reply = self.client.post("/GenerateToken", {"gateway": "mellat", "payAmount": 150000,
                                 "successCallBack": SITE + "/success", "failedCallBack": SITE + "/failed"}, format="json")
        token = reply.json()["token"]
        response = self.client.get(f"/GoToPayPage/{token}/71/150000")
        self.assertEqual(response["Location"], HUB + f"/mellat/pay/{token}")

    def test_panel_credentials_are_used_and_password_is_never_returned(self):
        bank = BankInfo.objects.get(key="mellat")
        self.client.force_authenticate(AdminUser.objects.create(username="mellat-admin", cellphone="09120000009"))
        path = "/api/admin/v1/Bank"
        response = self.client.post(path + "/AddBankGateway", {
            "bankId": bank.pk, "terminalId": "5678", "sandbox": True,
            "username": "panel-user", "password": "panel-secret",
        }, format="json")
        self.assertEqual(response.status_code, 200)
        gateway = BankGateway.objects.get(bank=bank)
        listing = self.client.get(path + "/GetGateway").json()
        self.assertNotIn("panel-secret", str(listing))
        row = next(row for row in listing["data"]["result"] if row["id"] == gateway.pk)
        self.assertEqual((row["username"], row["sandbox"], row["hasPassword"], row["configurationSource"]),
                         ("panel-user", True, True, "panel"))
        self.assertTrue(row["configurationComplete"])
        response = self.client.post(path + "/UpdateBankGateway", {
            "id": gateway.pk, "bankId": bank.pk, "terminalId": "5678", "sandbox": True,
            "username": "panel-user", "password": "",
        }, format="json")
        self.assertEqual(response.status_code, 200)
        gateway.refresh_from_db()
        self.assertEqual(gateway.mellat_password, "panel-secret")
        with override_settings(MELLAT_USERNAME="", MELLAT_PASSWORD="", MELLAT_SANDBOX=False):
            self.assertTrue(mellat.configured())
            record = self.started()
            self.assertTrue(record.mellat_sandbox)
            self.assertEqual(record.merchant_id, "5678")
            body = ET.fromstring(self.http.call_args.kwargs["data"])
            self.assertEqual(next(e.text for e in body.iter() if e.tag == "userName"), "panel-user")
            self.assertEqual(next(e.text for e in body.iter() if e.tag == "userPassword"), "panel-secret")
            removed = self.client.delete(f"{path}/Gateways/{gateway.pk}")
            self.assertEqual(removed.status_code, 200)
            service.mellat_return(record, self.fields(record))
            self.assertEqual(service.confirm(record, "71", 150000)["status"], "ok")

    def test_admin_can_add_and_edit_terminal_and_get_stable_gateway_key(self):
        bank = BankInfo.objects.get(key="mellat")
        self.client.force_authenticate(AdminUser.objects.create(username="test-admin", cellphone="09120000000"))
        prefix = "/api/admin/v1/Bank"
        info = self.client.get(prefix + "/GetInfo")
        option = next(b for b in info.json()["data"]["result"] if b["bankId"] == bank.pk)
        self.assertEqual((option["gatewayKey"], option["sandbox"]), ("mellat", True))
        invalid = self.client.post(prefix + "/AddBankGateway", {"bankId": bank.pk, "terminalId": "bad"}, format="json")
        self.assertEqual(invalid.status_code, 400)
        added = self.client.post(prefix + "/AddBankGateway", {"bankId": bank.pk, "terminalId": "5678"}, format="json")
        self.assertEqual(added.status_code, 200)
        gateway = BankGateway.objects.get(bank=bank)
        edited = self.client.post(prefix + "/UpdateBankGateway", {"id": gateway.pk, "bankId": bank.pk,
                                  "terminalId": "6789"}, format="json")
        self.assertEqual(edited.status_code, 200)
        gateway.refresh_from_db()
        self.assertEqual(gateway.terminal_id, "6789")


@override_settings(**CONFIG)
class MellatSiteTests(MellatCase):
    def setUp(self):
        super().setUp()
        self.customer = Customer.objects.create(cellphone="09121234567")
        self.invoice = Invoice.objects.create(customer=self.customer, amount=150000, payable_amount=150000)
        InvoiceLine.objects.create(invoice=self.invoice, product_id=1, variant_id=11, name="پیراهن", qty=1,
                                   price=150000, price_after_reduction=150000)
        self.gateway = BankGateway.objects.create(bank=BankInfo.objects.get(key="mellat"), terminal_id="5678")
        self.client.force_authenticate(self.customer)
        mock.patch("apps.storefront.payments._out_of_stock", return_value=False).start()
        mock.patch("apps.storefront.payments.erp_store.take").start()

    def test_storefront_pays_in_test_mode_with_saved_reference_and_masked_card(self):
        banks = self.client.get("/api/v1/Bank/GetGateways").json()["result"]["data"]
        option = next(bank for bank in banks if bank["gatewayKey"] == "mellat")
        self.assertTrue(option["iconUrl"].startswith("data:image/png;base64,"))
        response = self.client.get(f"/api/v1/Bank/PayInvoiceById?InvoiceId={self.invoice.pk}&GateWayId={self.gateway.pk}")
        record = PayRecord.objects.get(source=PayRecord.Source.SITE)
        self.assertEqual(response.json()["result"]["data"], service.mellat_page_url(record))
        self.assertEqual(record.merchant_id, "5678")
        callback = self.client.post(f"/mellat/callback/{record.token}", self.fields(record))
        # The snapshot must still identify this as test money if settings change mid-flight.
        with override_settings(MELLAT_SANDBOX=False):
            finished = self.client.get(callback["Location"].replace(SITE, ""))
        self.assertIn("success=true", finished["Location"])
        self.invoice.refresh_from_db()
        payment = InvoicePayment.objects.get(invoice=self.invoice)
        self.assertTrue(self.invoice.is_test)
        self.assertEqual(self.invoice.state, Invoice.State.SUCCESSFUL)
        self.assertTrue(payment.is_success)
        self.assertEqual((payment.reference, payment.card_pan), ("987654321", "610433******5689"))

    def test_unconfigured_or_disabled_gateway_is_not_offered(self):
        with override_settings(MELLAT_PASSWORD=""):
            response = self.client.get("/api/v1/Bank/GetGateways")
            self.assertNotIn("mellat", str(response.json()))
        self.gateway.is_deleted = True
        self.gateway.save()
        response = self.client.get("/api/v1/Bank/GetGateways")
        self.assertNotIn("mellat", str(response.json()))

    def test_changed_cart_is_never_settled(self):
        self.client.get(f"/api/v1/Bank/PayInvoiceById?InvoiceId={self.invoice.pk}&GateWayId={self.gateway.pk}")
        record = PayRecord.objects.get(source=PayRecord.Source.SITE)
        callback = self.client.post(f"/mellat/callback/{record.token}", self.fields(record))
        Invoice.objects.filter(pk=self.invoice.pk).update(payable_amount=160000)
        finished = self.client.get(callback["Location"].replace(SITE, ""))
        self.assertIn("success=false", finished["Location"])
        self.assertNotIn("bpSettleRequest", self.methods)
