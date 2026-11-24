from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.website.models import Customer, CustomerOtp


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


class CustomerLoginDigitsTests(TestCase):
    @patch("apps.storefront.account.smsir.send_otp", return_value=True)
    def test_mobile_formats_share_the_same_account_and_otp(self, send_otp):
        client = APIClient()
        Customer.objects.create(cellphone="09123456789")
        url = "/api/v1/Authentication/CustomerAthenticateInfo"
        for mobile in ("۰۹۱۲۳۴۵۶۷۸۹", "۹۱۲۳۴۵۶۷۸۹", "+۹۸۹۱۲۳۴۵۶۷۸۹", "٠٩١٢٣٤٥٦٧٨٩"):
            with self.subTest(mobile=mobile):
                response = client.post(url, {"cellPhone": mobile}, format="json")
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.data["result"]["data"]["userIsExist"])
        response = client.post("/api/v1/Authentication/SendOtpCode", {"cellPhone": "+۹۸۹۱۲۳۴۵۶۷۸۹"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(send_otp.call_args.args[0], "09123456789")
        code = send_otp.call_args.args[1].translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
        response = client.post("/api/v1/Authentication/CustomerAuthenticate",
                               {"cellPhone": "۹۱۲۳۴۵۶۷۸۹", "password": code, "isOtp": True}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_fixed_password_accepts_persian_digits_and_preserves_exact_password(self):
        customer = Customer.objects.create(cellphone="09123456789")
        customer.set_password("pass1234")
        customer.save()
        client = APIClient()
        url = "/api/v1/Authentication/CustomerAuthenticate"
        response = client.post(url, {"cellPhone": "۰۹۱۲۳۴۵۶۷۸۹", "password": "pass۱۲۳۴", "isOtp": False}, format="json")
        self.assertEqual(response.status_code, 200)
        customer.set_password("pass۱۲۳۴")
        customer.save()
        response = client.post(url, {"cellPhone": "۰۹۱۲۳۴۵۶۷۸۹", "password": "pass۱۲۳۴", "isOtp": False}, format="json")
        self.assertEqual(response.status_code, 200)
