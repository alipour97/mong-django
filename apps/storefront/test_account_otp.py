from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.website.models import CustomerOtp


class CustomerOtpResendTests(TestCase):
    @patch("apps.storefront.account.smsir.send_otp", return_value=True)
    def test_resend_after_two_minutes_replaces_code(self, send_otp):
        client = APIClient()
        url = "/api/v1/Authentication/SendOtpCode"
        payload = {"cellPhone": "09120001111"}
        first = client.post(url, payload, format="json")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data["result"]["data"]["seconds"], 120)
        old = CustomerOtp.objects.get(cellphone=payload["cellPhone"])
        self.assertEqual(client.post(url, payload, format="json").status_code, 409)
        CustomerOtp.objects.filter(pk=old.pk).update(created=timezone.now() - timedelta(seconds=121))
        second = client.post(url, payload, format="json")
        self.assertEqual(second.status_code, 200)
        old.refresh_from_db()
        self.assertTrue(old.used)
        self.assertEqual(CustomerOtp.objects.filter(cellphone=payload["cellPhone"], used=False).count(), 1)
        self.assertEqual(send_otp.call_count, 2)

    @patch("apps.storefront.account.smsir.send_otp", side_effect=[True, False])
    def test_failed_resend_preserves_previous_code(self, send_otp):
        client = APIClient()
        payload = {"cellPhone": "09120001111"}
        url = "/api/v1/Authentication/SendOtpCode"
        client.post(url, payload, format="json")
        old = CustomerOtp.objects.get(cellphone=payload["cellPhone"])
        CustomerOtp.objects.filter(pk=old.pk).update(created=timezone.now() - timedelta(seconds=121))
        self.assertEqual(client.post(url, payload, format="json").status_code, 500)
        old.refresh_from_db()
        self.assertFalse(old.used)
