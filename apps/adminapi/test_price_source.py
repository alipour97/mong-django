from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.adminapi.models import AdminUser
from apps.erp.dadehfa import _current_price_list_id
from apps.website.models import SiteSetting
from unittest import mock


@override_settings(ERP_CONNECTOR="dadehfa")
class PriceSourceTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(AdminUser.objects.create(username="prices", cellphone="09120000000"))
        self.url = "/api/admin/v1/Setting/PriceSource"

    def test_default_and_persistent_selection(self):
        response = self.client.get("/api/admin/v1/Setting/GetSetting")
        self.assertEqual(response.data["result"]["priceSource"], "list")
        response = self.client.post(self.url, {"source": "main"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(SiteSetting.objects.get().dadehfa_price_source, "main")
        self.assertEqual(self.client.get("/api/admin/v1/Setting/GetSetting").data["result"]["priceSource"], "main")
        with mock.patch("apps.erp.dadehfa.fetch_all") as fetch:
            self.assertIsNone(_current_price_list_id())
            fetch.assert_not_called()

    def test_invalid_input_keeps_the_selected_source(self):
        SiteSetting.objects.create(dadehfa_price_source="main")
        for data in ({}, {"source": "unknown"}, {"source": False}):
            with self.subTest(data=data):
                self.assertEqual(self.client.post(self.url, data, format="json").status_code, 400)
        self.assertEqual(SiteSetting.objects.get().dadehfa_price_source, "main")

    def test_anonymous_cannot_change_price_source(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(self.url, {"source": "main"}).status_code, 401)
        self.assertFalse(SiteSetting.objects.exists())

    @override_settings(ERP_CONNECTOR="samian")
    def test_other_connector_cannot_change_price_source(self):
        self.assertFalse(self.client.get("/api/admin/v1/Setting/GetSetting").data["result"]["priceSourceAvailable"])
        self.assertEqual(self.client.post(self.url, {"source": "main"}).status_code, 400)
