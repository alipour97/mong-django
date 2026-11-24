from unittest.mock import Mock, patch

import requests
from django.contrib import admin
from django.test import TestCase, override_settings

from apps import smsir
from apps.adminapi.models import SmsLog


class SmsLogTests(TestCase):
    @override_settings(SMSIR_API_KEY="key", SMSIR_OTP_TEMPLATE_ID=123, SMSIR_OTP_PARAM="Code")
    @patch("apps.smsir.requests.post")
    def test_accepted_otp_is_logged_without_code(self, post):
        post.return_value = Mock(ok=True, status_code=200, content=b'{}')
        post.return_value.json.return_value = {"status": 1}
        self.assertTrue(smsir.send_otp("+989121234567", "9876"))
        log = SmsLog.objects.get()
        self.assertEqual((log.mobile, log.template_id, log.accepted, log.http_status, log.result),
                         ("09121234567", 123, True, 200, "accepted"))
        self.assertNotIn("9876", str(log.__dict__))

    @override_settings(SMSIR_API_KEY="key")
    @patch("apps.smsir.requests.post")
    def test_rejection_and_request_failure_are_logged(self, post):
        post.return_value = Mock(ok=False, status_code=400, content=b'{}')
        post.return_value.json.return_value = {"status": 0}
        self.assertFalse(smsir.send_verify("0912", 1, {}))
        post.side_effect = requests.Timeout()
        self.assertFalse(smsir.send_verify("0912", 1, {}))
        self.assertEqual(set(SmsLog.objects.values_list("result", "http_status")),
                         {("rejected", 400), ("request_or_response_error", None)})

    @override_settings(SMSIR_API_KEY="")
    def test_missing_key_is_logged_and_admin_is_read_only(self):
        self.assertFalse(smsir.send_verify("0912", 1, {}))
        self.assertEqual(SmsLog.objects.get().result, "missing_api_key")
        model_admin = admin.site._registry[SmsLog]
        self.assertFalse(model_admin.has_add_permission(None))
        self.assertFalse(model_admin.has_change_permission(None))
        self.assertFalse(model_admin.has_delete_permission(None))
