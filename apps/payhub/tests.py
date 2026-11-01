"""
The hub against fake gateways: nothing here leaves the machine. Runs the
contract of Mong.Pay as the old site calls it, the SnappPay document and its
error list, and the new site's checkout.
"""
import json
from datetime import timedelta
from io import StringIO
from unittest import mock

import requests
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.adminapi.models import AdminUser
from apps.storefront import payments
from apps.website.models import BankGateway, BankInfo, Customer, Invoice, InvoiceLine, InvoicePayment

from . import service, snapppay
from .models import PayRecord

S = PayRecord.State
HUB = "https://payhub.mong.ir"
BACK = "https://api.mong.ir/api/v1/Bank/PaymentVerification?transactionId=7"
MERCHANT = "11111111-2222-3333-4444-555555555555"
TOKEN = "snapp-payment-token"


class Resp:
    def __init__(self, status: int, body):
        self.status_code, self.body = status, body
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.content = self.text.encode()
        self.headers = {"Content-Type": "application/json"}

    def json(self):
        if isinstance(self.body, str):
            raise ValueError
        return self.body


def good(**response) -> Resp:
    return Resp(200, {"successful": True, "response": response})


def bad(http: int, code: int, status: str | None = None) -> Resp:
    data = {"transaction-status": status} if status else None
    return Resp(http, {"successful": False, "errorData": {"errorCode": code, "message": f"e{code}", "data": data}})


class FakeSnapp:
    """Answers by the end of the path; the last answer of a list repeats. An exception is a timeout."""

    def __init__(self):
        self.routes = {"token": [good(paymentToken=TOKEN, paymentPageUrl="https://snapp/page")]}
        self.calls = []

    def set(self, name: str, *answers):
        self.routes[name] = list(answers)

    def count(self, name: str) -> int:
        return len([c for c in self.calls if c[0] == name])

    def body(self, name: str) -> dict:
        return [c for c in self.calls if c[0] == name][-1][1]

    def __call__(self, method, url, headers=None, timeout=None, **kwargs):
        name = url.rsplit("/", 1)[1]
        if name == "token" and "oauth" in url:
            return Resp(200, {"access_token": "jwt", "expires_in": 3600})
        self.calls.append((name, kwargs.get("json")))
        answers = self.routes.get(name) or [good(transactionId="1")]
        answer = answers.pop(0) if len(answers) > 1 else answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


@override_settings(SNAPPAY_BASE_URL="https://snapp.test", SNAPPAY_CLIENT_ID="c", SNAPPAY_CLIENT_SECRET="s", SNAPPAY_USERNAME="u",
                   SNAPPAY_PASSWORD="p", SNAPPAY_TRANSACTION_ID_START=50000000, SNAPPAY_COMMISSION_TYPE=100, PAYHUB_PUBLIC_URL=HUB,
                   PAYHUB_ACCEPT_KEY="hub-key", PAYHUB_ALLOWED_API_IPS=["10.0.0.5"], PAYHUB_ALLOWED_CALLBACK_HOSTS=["api.mong.ir"],
                   PAYHUB_OLD_HUB_URL="", ZARINPAL_SANDBOX=False, ZARINPAL_STARTPAY_BASE_URL="https://pay.mong.ir/pg/StartPay",
                   ZARINPAL_MERCHANT_ID=MERCHANT, SITE_URL="https://samian.mong.ir", PUBLIC_BASE_URL="https://samian.mong.ir")
class HubCase(TestCase):
    def setUp(self):
        self.snapp = FakeSnapp()
        for target, value in (("apps.payhub.snapppay.requests.request", self.snapp),
                              ("apps.payhub.service.time.sleep", lambda _: None)):
            mock.patch(target, value).start()
        self.zarin = mock.Mock()
        mock.patch("apps.payhub.zarinpal.requests.post", self.zarin).start()
        self.addCleanup(mock.patch.stopall)
        self.client = APIClient()

    def post(self, path: str, data=None, **extra):
        return self.client.post(path, data or {}, format="json", **extra)

    def generate(self, gateway="snapppay", amount=1000000, **extra) -> dict:
        reply = self.post("/GenerateToken", {"payAmount": amount, "successCallBack": BACK + "&success=true",
                                             "failedCallBack": BACK + "&success=false", "gateway": gateway + " ",
                                             "cellPhone": "09121234567", "customerKey": "42", "companyId": 3, **extra})
        self.assertEqual(reply.status_code, 200)
        return reply.json()

    def started(self, amount=1000000) -> PayRecord:
        """A SnappPay payment with the customer on SnappPay's page."""
        token = self.generate(amount=amount)["token"]
        reply = self.post(f"/GetPaymentToken/{token}/7/{amount}", {"amount": amount, "discountAmount": 0, "externalSourceAmount": 0,
                                                                   "mobile": "09121234567", "cartList": [{"cartId": 7}]})
        self.assertEqual(reply.status_code, 200)
        return PayRecord.objects.get(token=token)

    def callback(self, record: PayRecord, state="OK"):
        return self.client.post(f"/api/SnappPay/CallBack/{record.pk}/{record.token}",
                                {"transactionId": record.gateway_transaction_id, "state": state, "amount": record.amount}, format="multipart")

    def returned(self) -> PayRecord:
        record = self.started()
        self.callback(record)
        record.refresh_from_db()
        self.assertEqual(record.state, S.RETURNED)
        return record

    def confirm(self, record: PayRecord, transaction_id="7", amount=None):
        return self.post(f"/PaymentVerification/{record.token}",
                         {"transactionId": transaction_id, "amount": record.amount if amount is None else amount}).json()

    def age(self, record: PayRecord, minutes: int):
        PayRecord.objects.filter(pk=record.pk).update(updated=timezone.now() - timedelta(minutes=minutes))


class ContractTests(HubCase):
    """What the old site reads, field by field."""

    def test_generate_token_answers_like_mong_pay(self):
        data = self.generate()
        self.assertEqual(set(data), {"id", "token", "status", "message"})
        self.assertEqual((data["status"], data["message"]), ("success", None))
        self.assertRegex(data["token"], "^[a-f0-9]{32}$")

    def test_generate_token_refusals(self):
        self.assertEqual(self.generate(amount=0)["status"], "error")
        self.assertEqual(self.generate(gateway="saman")["status"], "error")
        self.assertEqual(self.generate(successCallBack="https://evil.example/x")["status"], "error")

    def test_server_routes_answer_only_known_callers(self):
        foreign = {"HTTP_X_REAL_IP": "8.8.8.8"}
        self.assertEqual(self.post("/GenerateToken", {}, **foreign).status_code, 403)
        self.assertEqual(self.post("/GenerateToken", {}, HTTP_X_REAL_IP="10.0.0.5").status_code, 200)
        self.assertEqual(self.post("/GenerateToken", {}, HTTP_X_REAL_IP="8.8.8.8", HTTP_X_MONG_HUB_KEY="hub-key").status_code, 200)
        self.assertEqual(self.post("/GenerateToken", {}, HTTP_X_REAL_IP="8.8.8.8", HTTP_X_MONG_HUB_KEY="wrong").status_code, 403)

    def test_routes_ignore_case_and_trailing_slash(self):
        self.assertEqual(self.post("/generatetoken/", {}).status_code, 200)

    def test_get_payment_token_sends_our_return_url_and_a_fresh_id(self):
        record = self.started()
        body = self.snapp.body("token")
        self.assertEqual(body["returnURL"], f"{HUB}/api/SnappPay/CallBack/{record.pk}/{record.token}")
        self.assertEqual(body["transactionId"], str(50000000 + record.pk))
        self.assertEqual(body["mobile"], "+989121234567")
        self.assertEqual(body["cartList"], [{"cartId": 7}])

    def test_get_payment_token_answers_the_same_when_asked_twice(self):
        record = self.started()
        reply = self.post(f"/GetPaymentToken/{record.token}/7/1000000", {"amount": 1000000})
        self.assertEqual(reply.json(), {"paymentToken": TOKEN, "paymentPageUrl": "https://snapp/page",
                                        "transactionId": record.gateway_transaction_id})
        self.assertEqual(self.snapp.count("token"), 1)

    def test_get_payment_token_refuses_another_amount(self):
        token = self.generate()["token"]
        reply = self.post(f"/GetPaymentToken/{token}/7/5", {"amount": 5})
        self.assertEqual((reply.status_code, reply.json()), (400, {"paymentToken": None, "paymentPageUrl": None}))

    def test_snapppay_failure_on_token(self):
        self.snapp.set("token", bad(403, 1051))
        token = self.generate()["token"]
        self.assertEqual(self.post(f"/GetPaymentToken/{token}/7/1000000", {"amount": 1000000}).status_code, 400)
        self.assertEqual(PayRecord.objects.get(token=token).state, S.FAILED)

    def test_hub_token_guards_the_snapppay_routes(self):
        self.assertEqual(self.post("/api/SnappPay/EligibleWithAuth?amount=5").status_code, 401)
        access = self.post("/api/SnappPay/GetTokenByCompany/3").json()["access_token"]
        self.snapp.set("eligible", good(eligible=True, title_message="t", description="d"))
        reply = self.post("/api/SnappPay/EligibleWithAuth?amount=5", HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(reply.json()["response"]["title_message"], "t")

    def test_panel_routes_pass_snapppay_answers_through(self):
        access = self.post("/api/SnappPay/GetTokenByCompany/3").json()["access_token"]
        self.snapp.set("cancel", bad(400, 1011, "verify"))
        reply = self.post("/api/SnappPay/PaymentCancel", {"paymentToken": "x"}, HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual((reply.status_code, reply.json()["errorData"]["errorCode"]), (400, 1011))

    def test_check_token(self):
        record = self.started()
        self.assertEqual(self.client.get(f"/CheckToken/{record.token}").json()["transactionId"], "7")
        self.assertEqual(self.client.get(f"/CheckToken/{'a' * 32}").status_code, 404)

    def test_unknown_token_goes_to_the_old_hub_while_moving(self):
        self.assertEqual(self.post(f"/PaymentVerification/{'a' * 32}", {})
                         .json(), {"status": "not_found", "companyId": None, "customerId": None, "amount": None})
        with override_settings(PAYHUB_OLD_HUB_URL="https://zarinpal.mong.ir"):
            with mock.patch("apps.payhub.views.requests.request", return_value=Resp(200, {"status": "ok"})) as call:
                reply = self.post(f"/PaymentVerification/{'a' * 32}", {"amount": 5})
        self.assertEqual(reply.json(), {"status": "ok"})
        self.assertEqual(call.call_args.args[1], f"https://zarinpal.mong.ir/PaymentVerification/{'a' * 32}")


class SnappFlowTests(HubCase):
    def test_a_whole_purchase(self):
        record = self.started()
        reply = self.callback(record)
        self.assertEqual(reply.status_code, 302)
        self.assertIn("success=true", reply["Location"])
        self.assertIn(f"trackingToken={record.token}", reply["Location"])
        self.assertIn(f"snappTrackingToken={TOKEN}", reply["Location"])
        self.assertIn(f"paymentTransactionId={50000000 + record.pk}", reply["Location"])
        self.assertEqual(self.confirm(record), {"status": "ok", "companyId": 3, "customerId": 42, "amount": 1000000})
        self.assertEqual(self.confirm(record)["status"], "duplicate")
        self.assertEqual((self.snapp.count("verify"), self.snapp.count("settle")), (1, 1))

    def test_verify_runs_once_however_often_the_return_url_is_called(self):
        record = self.started()
        self.callback(record)
        self.callback(record)
        self.assertEqual(self.snapp.count("verify"), 1)

    def test_a_second_request_during_verify_is_told_to_wait(self):
        record = self.started()
        PayRecord.objects.filter(pk=record.pk).update(state=S.VERIFYING)
        reply = self.callback(record)
        self.assertEqual(reply.status_code, 200)
        self.assertIn('http-equiv="refresh"', reply.content.decode())
        self.assertEqual(self.snapp.count("verify"), 0)

    def test_wrong_transaction_id_is_refused(self):
        record = self.started()
        reply = self.client.post(f"/api/SnappPay/CallBack/{record.pk}/{record.token}", {"transactionId": "1", "state": "OK"}, format="multipart")
        self.assertEqual(reply.status_code, 400)
        self.assertEqual(self.snapp.count("verify"), 0)

    def test_failed_state_reverts_and_goes_to_the_failed_address(self):
        record = self.started()
        reply = self.callback(record, "FAILED")
        self.assertIn("success=false", reply["Location"])
        self.assertEqual((self.snapp.count("revert"), self.snapp.count("verify")), (1, 0))
        record.refresh_from_db()
        self.assertEqual(record.state, S.FAILED)

    def verify_ends_in(self, state):
        record = self.started()
        self.callback(record)
        record.refresh_from_db()
        self.assertEqual(record.state, state)

    def test_verify_timeout_then_status_verify(self):
        self.snapp.set("verify", requests.Timeout())
        self.snapp.set("status", good(status="VERIFY"))
        self.verify_ends_in(S.RETURNED)

    def test_verify_timeout_then_status_pending_verifies_again(self):
        self.snapp.set("verify", requests.Timeout(), good(transactionId="1"))
        self.snapp.set("status", good(status="PENDING"))
        self.verify_ends_in(S.RETURNED)
        self.assertEqual(self.snapp.count("verify"), 2)

    def test_verify_timeout_then_other_status_fails(self):
        self.snapp.set("verify", requests.Timeout())
        self.snapp.set("status", good(status="REVERT"))
        self.verify_ends_in(S.FAILED)

    def test_verify_and_status_both_silent_is_unknown(self):
        self.snapp.set("verify", requests.Timeout())
        self.snapp.set("status", requests.Timeout())
        self.verify_ends_in(S.UNKNOWN)

    def test_verify_1053_is_retried(self):
        self.snapp.set("verify", bad(429, 1053), good(transactionId="1"))
        self.verify_ends_in(S.RETURNED)

    def test_verify_1000_is_retried_then_asks_the_status(self):
        self.snapp.set("verify", bad(500, 1000))
        self.snapp.set("status", good(status="VERIFY"))
        self.verify_ends_in(S.RETURNED)
        self.assertEqual(self.snapp.count("verify"), 2)

    def test_verify_1011_follows_transaction_status(self):
        for status, state in (("verify", S.RETURNED), ("settle", S.RETURNED), ("revert", S.FAILED), (None, S.FAILED)):
            with self.subTest(status=status):
                self.snapp.set("verify", bad(400, 1011, status))
                self.verify_ends_in(state)

    def test_verify_manual_codes_go_to_a_person(self):
        for code in (1048, 100, 1007):
            with self.subTest(code=code):
                self.snapp.set("verify", bad(400, code))
                self.verify_ends_in(S.REVIEW)

    def test_access_denied_page_is_an_answer_too(self):
        self.snapp.set("verify", Resp(403, "<h1>Access Denied</h1>"))
        self.snapp.set("status", Resp(403, "<h1>Access Denied</h1>"))
        self.verify_ends_in(S.UNKNOWN)

    def settle_ends(self, *settle, status=None, verdict="ok", state=S.CONSUMED):
        record = self.returned()
        self.snapp.set("settle", *settle)
        if status:
            self.snapp.set("status", status)
        self.assertEqual(self.confirm(record)["status"], verdict)
        record.refresh_from_db()
        self.assertEqual(record.state, state)

    def test_settle_no_answer_status_settle(self):
        self.settle_ends(requests.Timeout(), status=good(status="SETTLE"))

    def test_settle_false_status_verify_settles_again(self):
        self.settle_ends(bad(500, 1000), good(transactionId="1"), status=good(status="VERIFY"))
        self.assertEqual(self.snapp.count("settle"), 2)

    def test_settle_still_failing_on_verify_is_left_to_snapppay(self):
        self.settle_ends(bad(500, 1000), status=good(status="VERIFY"))

    def test_settle_1011_settled_is_final(self):
        self.settle_ends(bad(400, 1011, "settle"))

    def test_settle_1011_reverted_fails(self):
        self.settle_ends(bad(400, 1011, "revert"), verdict="failed", state=S.REVERTED)

    def test_settle_1011_without_status_fails(self):
        self.settle_ends(bad(400, 1011), verdict="failed", state=S.FAILED)

    def test_settle_silent_and_status_silent_waits_for_reconcile(self):
        self.settle_ends(requests.Timeout(), status=requests.Timeout(), verdict="failed", state=S.RETURNED)

    def test_confirm_needs_the_same_invoice_and_amount(self):
        record = self.returned()
        self.assertEqual(self.confirm(record, transaction_id="8")["status"], "mismatch")
        self.assertEqual(self.confirm(record, amount=5)["status"], "mismatch")
        self.assertEqual(self.snapp.count("settle"), 0)

    def test_confirm_before_paying(self):
        self.assertEqual(self.confirm(self.started())["status"], "not_paid")


class ReconcileTests(HubCase):
    def test_command_runs(self):
        call_command("payhub_reconcile", stdout=StringIO())

    def test_a_recent_payment_is_left_alone(self):
        record = self.returned()
        service.reconcile()
        record.refresh_from_db()
        self.assertEqual((record.state, self.snapp.count("revert")), (S.RETURNED, 0))

    def test_verified_but_never_confirmed_is_refunded(self):
        record = self.returned()
        self.age(record, 21)
        self.snapp.set("status", good(status="VERIFY"))
        service.reconcile()
        record.refresh_from_db()
        self.assertEqual((record.state, self.snapp.count("revert")), (S.REVERTED, 1))

    def test_settled_without_an_order_goes_to_a_person(self):
        record = self.returned()
        self.age(record, 21)
        self.snapp.set("status", good(status="SETTLE"))
        service.reconcile()
        record.refresh_from_db()
        self.assertEqual((record.state, self.snapp.count("revert")), (S.REVIEW, 0))

    def test_unknown_waits_40_minutes(self):
        self.snapp.set("verify", requests.Timeout())
        self.snapp.set("status", requests.Timeout())
        record = self.started()
        self.callback(record)
        self.snapp.set("status", good(status="REVERT"))
        self.age(record, 39)
        service.reconcile()
        record.refresh_from_db()
        self.assertEqual(record.state, S.UNKNOWN)
        self.age(record, 41)
        service.reconcile()
        record.refresh_from_db()
        self.assertEqual(record.state, S.REVERTED)

    def test_status_silent_again_reverts_and_stops_trying(self):
        self.snapp.set("verify", requests.Timeout())
        self.snapp.set("status", requests.Timeout())
        self.snapp.set("revert", requests.Timeout())
        record = self.started()
        self.callback(record)
        for _ in range(service.MAX_RESOLVE_TRIES):
            self.age(record, 41)
            service.reconcile()
        record.refresh_from_db()
        self.assertEqual(record.state, S.REVIEW)

    def test_step_cut_short_by_a_dead_process(self):
        record = self.started()
        PayRecord.objects.filter(pk=record.pk).update(state=S.VERIFYING)
        self.age(record, 6)
        service.reconcile()
        record.refresh_from_db()
        self.assertEqual(record.state, S.UNKNOWN)

    def test_customer_who_never_came_back(self):
        record = self.started()
        self.age(record, 121)
        service.reconcile()
        record.refresh_from_db()
        self.assertEqual(record.state, S.FAILED)
        self.assertIn("success=false", self.callback(record)["Location"])
        self.assertEqual(self.snapp.count("verify"), 0)


class AfterSaleTests(HubCase):
    def test_cancel_settles_a_verified_payment_first(self):
        self.snapp.set("cancel", bad(400, 1011, "verify"), good(transactionId="1"))
        self.assertEqual(service.cancel(TOKEN), (True, ""))
        self.assertEqual(self.snapp.count("settle"), 1)

    def test_cancel_of_a_cancelled_payment_is_done(self):
        self.snapp.set("cancel", bad(400, 1011, "cancel"))
        self.assertTrue(service.cancel(TOKEN)[0])

    def test_cancel_is_not_retried_on_a_server_error(self):
        self.snapp.set("cancel", bad(500, 1000))
        self.assertEqual(service.cancel(TOKEN), (False, "e1000"))
        self.assertEqual(self.snapp.count("cancel"), 1)

    def test_update_shows_snapppay_message(self):
        self.snapp.set("update", bad(409, 1042))
        order = {"amount": 1, "discountAmount": 0, "externalSourceAmount": 0, "cartList": []}
        self.assertEqual(service.update(TOKEN, order), (False, "e1042"))
        self.assertEqual(self.snapp.body("update")["paymentToken"], TOKEN)


class ZarinpalTests(HubCase):
    def set_zarinpal(self, *answers):
        self.zarin.side_effect = list(answers)

    def started_zarinpal(self) -> PayRecord:
        token = self.generate("zarinpal", gatewayCode=MERCHANT + "   ")["token"]
        self.set_zarinpal(Resp(200, {"data": {"code": 100, "authority": "A0001"}, "errors": []}))
        reply = self.client.get(f"/GoToPayPage/{token}/7/1000000")
        self.assertEqual((reply.status_code, reply["Location"]), (302, "https://pay.mong.ir/pg/StartPay/A0001"))
        return PayRecord.objects.get(token=token)

    def back(self, record: PayRecord, status="OK"):
        return self.client.get(f"/zarinpal/callback/{record.token}?Authority=A0001&Status={status}")

    def test_a_whole_purchase(self):
        record = self.started_zarinpal()
        body = self.zarin.call_args.kwargs["json"]
        self.assertEqual(body["callback_url"], f"{HUB}/zarinpal/callback/{record.token}")
        self.assertEqual((body["merchant_id"], body["metadata"]["auto_verify"]), (MERCHANT, False))
        reply = self.back(record)
        self.assertIn(f"trackingToken={record.token}", reply["Location"])
        self.assertIn("paymentTransactionId=A0001", reply["Location"])
        self.set_zarinpal(Resp(200, {"data": {"code": 100, "ref_id": 201, "card_pan": "5022"}, "errors": []}))
        self.assertEqual(self.confirm(record)["status"], "ok")
        record.refresh_from_db()
        self.assertEqual((record.ref_id, record.card_pan, record.state), ("201", "5022", S.CONSUMED))
        self.assertEqual(self.confirm(record)["status"], "duplicate")

    def test_double_click_uses_the_same_session(self):
        record = self.started_zarinpal()
        self.assertEqual(self.client.get(f"/GoToPayPage/{record.token}/7/1000000").status_code, 302)
        self.assertEqual(self.zarin.call_count, 1)

    def test_used_link_and_wrong_amount(self):
        record = self.started_zarinpal()
        self.assertEqual(self.client.get(f"/GoToPayPage/{record.token}/7/5").status_code, 400)
        self.back(record)
        self.assertEqual(self.client.get(f"/GoToPayPage/{record.token}/7/1000000").status_code, 409)

    def test_customer_cancelled(self):
        record = self.started_zarinpal()
        self.assertIn("success=false", self.back(record, "NOK")["Location"])
        self.assertEqual(self.confirm(record)["status"], "not_paid")

    def test_wrong_authority(self):
        record = self.started_zarinpal()
        self.assertEqual(self.client.get(f"/zarinpal/callback/{record.token}?Authority=B&Status=OK").status_code, 400)

    def test_verified_before_is_ok(self):
        record = self.started_zarinpal()
        self.back(record)
        self.set_zarinpal(Resp(200, {"data": {"code": 101, "ref_id": 201}, "errors": []}))
        self.assertEqual(self.confirm(record)["status"], "ok")

    def test_unreachable_can_be_confirmed_again(self):
        record = self.started_zarinpal()
        self.back(record)
        self.set_zarinpal(requests.Timeout(), Resp(200, {"data": {"code": 100, "ref_id": 201}, "errors": []}))
        self.assertEqual(self.confirm(record)["status"], "failed")
        record.refresh_from_db()
        self.assertEqual(record.state, S.RETURNED)
        self.assertEqual(self.confirm(record)["status"], "ok")

    def test_refused_is_final(self):
        record = self.started_zarinpal()
        self.back(record)
        self.set_zarinpal(Resp(200, {"data": [], "errors": {"code": -51, "message": "x"}}))
        self.assertEqual(self.confirm(record)["status"], "failed")
        record.refresh_from_db()
        self.assertEqual(record.state, S.FAILED)

    def test_request_refused_goes_to_the_failed_address(self):
        token = self.generate("zarinpal")["token"]
        self.set_zarinpal(Resp(200, {"data": [], "errors": {"code": -9, "message": "x"}}))
        self.assertIn("success=false", self.client.get(f"/GoToPayPage/{token}/7/1000000")["Location"])

    @override_settings(ZARINPAL_SANDBOX=True)
    def test_sandbox_never_uses_the_branded_page(self):
        token = self.generate("zarinpal")["token"]
        self.set_zarinpal(Resp(200, {"data": {"code": 100, "authority": "A1"}, "errors": []}))
        self.assertEqual(self.client.get(f"/GoToPayPage/{token}/7/1000000")["Location"], "https://sandbox.zarinpal.com/pg/StartPay/A1")

    def test_stale_return_is_never_verified(self):
        record = self.started_zarinpal()
        self.back(record)
        self.age(record, 21)
        service.reconcile()
        record.refresh_from_db()
        self.assertEqual(record.state, S.FAILED)


class SiteCase(HubCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.customer = Customer.objects.create(cellphone="09121234567")
        self.invoice = Invoice.objects.create(customer=self.customer, amount=1250000, reduction_amount=50000, delivery_amount=100000,
                                              payable_amount=1300000)
        InvoiceLine.objects.create(invoice=self.invoice, product_id=1, variant_id=11, name="پیراهن", qty=2, price=650000,
                                   price_after_reduction=600000)
        snapp = BankInfo.objects.create(key="snapppay", name="اسنپ‌پی")
        zarin = BankInfo.objects.create(key="zarinpal", name="زرین‌پال")
        self.snapp_gateway = BankGateway.objects.create(bank=snapp)
        self.zarin_gateway = BankGateway.objects.create(bank=zarin, merchant=MERCHANT)
        self.client.force_authenticate(self.customer)
        self.stock_patch = mock.patch("apps.storefront.payments._out_of_stock", return_value=False)
        self.stock = self.stock_patch.start()
        self.addCleanup(mock.patch.stopall)

    def pay(self, gateway, invoice=None):
        return self.client.get(f"/api/v1/Bank/PayInvoiceById?InvoiceId={(invoice or self.invoice).id}&GateWayId={gateway.id}").json()

    def record(self) -> PayRecord:
        return PayRecord.objects.order_by("-id").first()

    def finish_at_site(self, url: str) -> str:
        return self.client.get(url.replace("https://samian.mong.ir", ""))["Location"]


class SiteCheckoutTests(SiteCase):
    def test_snapppay_purchase(self):
        self.assertEqual(self.pay(self.snapp_gateway)["result"]["data"], "https://snapp/page")
        order = self.snapp.body("token")
        cart = order["cartList"][0]
        self.assertEqual((order["amount"], order["discountAmount"], order["externalSourceAmount"]), (1300000, 0, 0))
        self.assertEqual((cart["totalAmount"], cart["shippingAmount"], cart["isShipmentIncluded"]), (1300000, 100000, False))
        self.assertEqual(cart["cartItems"][0], {"amount": 600000, "category": "پوشاک", "count": 2, "id": 11, "name": "پیراهن",
                                                "commissionType": 100})
        record = self.record()
        confirmation = self.finish_at_site(self.callback(record)["Location"])
        self.assertIn("success=true", confirmation)
        self.invoice.refresh_from_db()
        payment = InvoicePayment.objects.get(invoice=self.invoice)
        self.assertEqual((self.invoice.state, payment.is_success, payment.reference), (Invoice.State.SUCCESSFUL, True, record.gateway_transaction_id))
        self.assertEqual(self.snapp.count("settle"), 1)

    def test_coming_back_twice_changes_nothing(self):
        self.pay(self.snapp_gateway)
        url = self.callback(self.record())["Location"]
        self.finish_at_site(url)
        self.assertIn("success=true", self.finish_at_site(url))
        self.assertEqual(self.snapp.count("settle"), 1)

    def test_cart_changed_after_starting_is_reverted_before_verify(self):
        self.pay(self.snapp_gateway)
        Invoice.objects.filter(pk=self.invoice.pk).update(payable_amount=900000)
        confirmation = self.finish_at_site(self.callback(self.record())["Location"])
        self.assertIn("success=false", confirmation)
        self.assertEqual((self.snapp.count("verify"), self.snapp.count("revert")), (0, 1))
        self.assertEqual(self.record().state, S.REVERTED)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.state, Invoice.State.PRE_INVOICE)

    def test_out_of_stock_is_reverted_before_verify(self):
        self.pay(self.snapp_gateway)
        self.stock.return_value = True
        self.finish_at_site(self.callback(self.record())["Location"])
        self.assertEqual((self.snapp.count("verify"), self.snapp.count("revert")), (0, 1))

    def test_second_tab_after_the_cart_was_paid_is_reverted(self):
        self.snapp.set("token", good(paymentToken="tab-1", paymentPageUrl="https://snapp/1"),
                       good(paymentToken="tab-2", paymentPageUrl="https://snapp/2"))
        self.pay(self.snapp_gateway)
        first = self.record()
        self.pay(self.snapp_gateway)
        second = self.record()
        self.assertNotEqual(first.gateway_transaction_id, second.gateway_transaction_id)
        self.finish_at_site(self.callback(first)["Location"])
        self.assertIn("success=false", self.finish_at_site(self.callback(second)["Location"]))
        self.assertEqual((self.snapp.count("settle"), self.snapp.count("revert")), (1, 1))

    def test_failed_at_snapppay_leaves_the_pre_invoice(self):
        self.pay(self.snapp_gateway)
        self.assertIn("success=false", self.finish_at_site(self.callback(self.record(), "FAILED")["Location"]))
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.state, Invoice.State.PRE_INVOICE)
        self.assertFalse(InvoicePayment.objects.get(invoice=self.invoice).is_success)

    def test_settle_failure_does_not_mark_a_paid_order_failed_for_good(self):
        self.pay(self.snapp_gateway)
        self.snapp.set("settle", requests.Timeout(), good(transactionId="1"))
        self.snapp.set("status", requests.Timeout())
        url = self.callback(self.record())["Location"]
        self.assertIn("success=false", self.finish_at_site(url))
        self.assertIn("success=true", self.finish_at_site(url))

    def test_token_cannot_be_guessed(self):
        self.pay(self.snapp_gateway)
        self.assertIn("success=false", self.client.get("/api/v1/Bank/PaymentVerification?success=true&trackingToken=x")["Location"])

    def test_zarinpal_purchase(self):
        self.zarin.side_effect = [Resp(200, {"data": {"code": 100, "authority": "A0002"}, "errors": []}),
                                  Resp(200, {"data": {"code": 100, "ref_id": 777, "card_pan": "5022"}, "errors": []})]
        self.assertEqual(self.pay(self.zarin_gateway)["result"]["data"], "https://pay.mong.ir/pg/StartPay/A0002")
        self.assertEqual(self.zarin.call_args.kwargs["json"]["amount"], 1300000)
        back = self.client.get(f"/zarinpal/callback/{self.record().token}?Authority=A0002&Status=OK")["Location"]
        confirmation = self.finish_at_site(back)
        self.assertIn("success=true", confirmation)
        self.assertIn("TrackingToken=777", confirmation)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.state, Invoice.State.SUCCESSFUL)
        self.assertEqual(InvoicePayment.objects.get(invoice=self.invoice).card_pan, "5022")

    def test_zarinpal_cart_changed_is_never_verified(self):
        self.zarin.side_effect = [Resp(200, {"data": {"code": 100, "authority": "A0002"}, "errors": []})]
        self.pay(self.zarin_gateway)
        Invoice.objects.filter(pk=self.invoice.pk).update(payable_amount=900000)
        back = self.client.get(f"/zarinpal/callback/{self.record().token}?Authority=A0002&Status=OK")["Location"]
        self.assertIn("success=false", self.finish_at_site(back))
        self.assertEqual(self.zarin.call_count, 1)

    def test_snapppay_refusal_reaches_the_customer_kindly(self):
        self.snapp.set("token", bad(403, 1051))
        reply = self.client.get(f"/api/v1/Bank/PayInvoiceById?InvoiceId={self.invoice.id}&GateWayId={self.snapp_gateway.id}")
        self.assertEqual(reply.status_code, 502)
        self.assertFalse(InvoicePayment.objects.filter(invoice=self.invoice).exists())

    def test_gateways_list_both(self):
        keys = [g["gatewayKey"] for g in self.client.get("/api/v1/Bank/GetGateways").json()["result"]["data"]]
        self.assertEqual(sorted(keys), ["snapppay", "zarinpal"])

    def test_snapppay_stays_off_without_its_address(self):
        with override_settings(SNAPPAY_BASE_URL=""):
            keys = [g["gatewayKey"] for g in self.client.get("/api/v1/Bank/GetGateways").json()["result"]["data"]]
        self.assertEqual(keys, ["zarinpal"])


class SiteEligibleTests(SiteCase):
    def test_checkout_asks_every_time_and_shows_it_unchanged(self):
        self.snapp.set("eligible", good(eligible=True, title_message="عنوان", description="توضیح"))
        for _ in range(2):
            data = self.client.get("/api/v1/Bank/SnappPayEligible?Amount=5000").json()["result"]["data"]
        self.assertEqual(data, {"eligible": True, "title_message": "عنوان", "description": "توضیح"})
        self.assertEqual(self.snapp.count("eligible"), 2)

    def test_no_answer_hides_the_method(self):
        self.snapp.set("eligible", requests.Timeout())
        self.assertFalse(self.client.get("/api/v1/Bank/SnappPayEligible?Amount=5000").json()["result"]["data"]["eligible"])

    def test_product_page_needs_no_sign_in_and_shares_answers(self):
        self.client.force_authenticate(None)
        self.snapp.set("eligible", good(eligible=True, title_message="عنوان", description="توضیح"))
        for _ in range(3):
            data = self.client.get("/api/v1/Bank/SnappPayOffer?Amount=5000").json()["result"]["data"]
        self.assertTrue(data["eligible"])
        self.assertEqual(self.snapp.count("eligible"), 1)
        self.client.get("/api/v1/Bank/SnappPayOffer?Amount=6000")
        self.assertEqual(self.snapp.count("eligible"), 2)

    def test_product_page_with_a_bad_amount_asks_nobody(self):
        self.client.force_authenticate(None)
        self.assertFalse(self.client.get("/api/v1/Bank/SnappPayOffer?Amount=x").json()["result"]["data"]["eligible"])
        self.assertEqual(self.snapp.count("eligible"), 0)


class StockTests(SiteCase):
    def test_counts_only_online_warehouses(self):
        from apps.erp.connector import Connector
        from apps.erp.models import ErpProduct, ErpStock, ErpVariant

        self.stock_patch.stop()
        mock.patch("apps.erp.store.get_connector", return_value=Connector()).start()
        line = self.invoice.lines.get()
        ErpProduct.objects.create(product_id=line.product_id, erp_id=1, synced_at=timezone.now())
        variant = ErpVariant.objects.create(id=line.variant_id, product_id=line.product_id)
        ErpStock.objects.create(variant=variant, warehouse_id=1, qty=1)
        ErpStock.objects.create(variant=variant, warehouse_id=9, qty=5)
        with mock.patch("apps.erp.store.online_warehouse_ids", return_value=[1]):
            self.assertTrue(payments._out_of_stock(self.invoice))
        with mock.patch("apps.erp.store.online_warehouse_ids", return_value=[1, 9]):
            self.assertFalse(payments._out_of_stock(self.invoice))


class PanelTests(SiteCase):
    def setUp(self):
        super().setUp()
        self.pay(self.snapp_gateway)
        self.finish_at_site(self.callback(self.record())["Location"])
        self.invoice.refresh_from_db()
        self.line = self.invoice.lines.get()
        self.admin = AdminUser.objects.create(username="a", cellphone="09000000000")
        self.client.force_authenticate(self.admin)

    def test_header_offers_the_buttons(self):
        reply = self.client.get(f"/api/admin/v1/Invoice/InvoiceDetails/{self.invoice.id}").json()
        header = reply["data"]["result"]["invoiceHeader"]
        self.assertEqual(header["snappPayToken"], TOKEN)
        self.assertEqual(header["snappPayTransactionId"], self.record().gateway_transaction_id)

    def test_cancel(self):
        reply = self.post(f"/api/admin/v1/Invoice/CancelInvoice/{self.invoice.id}").json()
        self.assertTrue(reply["data"]["result"]["successful"])
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.state, Invoice.State.CANCELLED)

    def test_cancel_refused_shows_why(self):
        self.snapp.set("cancel", bad(500, 1000))
        reply = self.post(f"/api/admin/v1/Invoice/CancelInvoice/{self.invoice.id}")
        self.assertEqual((reply.status_code, reply.json()["data"]["errorMessage"]), (400, ["e1000"]))
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.state, Invoice.State.SUCCESSFUL)

    def test_update_lowers_the_order(self):
        reply = self.post(f"/api/admin/v1/Invoice/UpdateInvoice/{self.invoice.id}", {"invoiceDetails": [{"id": self.line.id, "qty": 1}]}).json()
        self.assertTrue(reply["data"]["result"]["successful"])
        sent = self.snapp.body("update")
        self.assertEqual((sent["amount"], sent["paymentToken"], sent["cartList"][0]["cartItems"][0]["count"]), (700000, TOKEN, 1))
        self.invoice.refresh_from_db()
        self.assertEqual((self.invoice.payable_amount, self.invoice.amount), (700000, 650000))
        self.assertEqual(self.invoice.lines.get().qty, 1)

    def test_update_cannot_raise_a_quantity(self):
        reply = self.post(f"/api/admin/v1/Invoice/UpdateInvoice/{self.invoice.id}", {"invoiceDetails": [{"id": self.line.id, "qty": 3}]})
        self.assertEqual(reply.status_code, 400)
        self.assertEqual(self.snapp.count("update"), 0)

    def test_order_paid_by_zarinpal_is_refused(self):
        InvoicePayment.objects.filter(invoice=self.invoice).update(gateway="zarinpal")
        self.assertEqual(self.post(f"/api/admin/v1/Invoice/CancelInvoice/{self.invoice.id}").status_code, 400)
        self.assertEqual(self.snapp.count("cancel"), 0)


class MobileFormatTests(TestCase):
    def test_every_form_becomes_plus_98(self):
        for mobile in ("09121234567", "9121234567", "989121234567", "00989121234567", "+989121234567"):
            self.assertEqual(snapppay.format_mobile(mobile), "+989121234567")

    def test_bad_numbers(self):
        for mobile in ("", None, "0212223344", "0912"):
            self.assertIsNone(snapppay.format_mobile(mobile))
