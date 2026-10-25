"""
Unit and Integration Tests for apps.samian package.
"""
import json
from django.test import TestCase, override_settings
from apps.samian import (
    SamianClient,
    SamianSettings,
    get_samian_client,
    get_samian_settings,
    CatalogService,
    InventoryService,
    MediaService,
    OrderService,
    SamianAPIError,
    SamianAuthError,
    SamianUploadError,
    SamianTokenManager,
    extract_records,
    extract_total_count,
    samian_filters,
)
from apps.samian.auth import soft_auth_failure


class SamianConfigTests(TestCase):
    def test_default_base_url_is_dev_port_8087(self):
        cfg = get_samian_settings()
        self.assertIn("8087", cfg.base_url)
        self.assertNotIn("8086", cfg.base_url)

    def test_safety_guard_blocks_production_port_8086(self):
        with self.assertRaises(ValueError) as ctx:
            SamianSettings(base_url="http://78.109.198.8:8086", allow_production_server=False)
        self.assertIn("SAFETY GUARD TRIGGERED", str(ctx.exception))


class SamianHelperTests(TestCase):
    def test_extract_records_dict_items(self):
        payload = {"data": {"items": [{"id": 1}, {"id": 2}]}}
        self.assertEqual(extract_records(payload), [{"id": 1}, {"id": 2}])

    def test_extract_records_bare_list(self):
        payload = [{"id": 10}]
        self.assertEqual(extract_records(payload), [{"id": 10}])

    def test_extract_records_data_list(self):
        payload = {"data": [{"id": 20}]}
        self.assertEqual(extract_records(payload), [{"id": 20}])

    def test_extract_total_count(self):
        payload = {"data": {"items": [], "totalCount": 42000}}
        self.assertEqual(extract_total_count(payload), 42000)

    def test_samian_filters_builder(self):
        filt = samian_filters(("warehouse_id", "=", 1), ("isactive", "=", True))
        parsed = json.loads(filt)
        self.assertEqual(parsed, [["warehouse_id", "=", 1], "and", ["isactive", "=", True]])


class SamianAuthTests(TestCase):
    def test_soft_auth_failure_detection(self):
        class MockResponse:
            status_code = 200
            content = b'{"status": false, "code": 401, "developerMessage": "InvalidUser", "data": null}'
            def json(self):
                return json.loads(self.content.decode("utf-8"))

        self.assertTrue(soft_auth_failure(MockResponse()))

    def test_token_caching_and_clearing(self):
        scope = "test_server:8087"
        SamianTokenManager.set_token("sample_token_123", scope=scope)
        self.assertEqual(SamianTokenManager.get_token(scope), "sample_token_123")
        SamianTokenManager.clear_token(scope)
        self.assertIsNone(SamianTokenManager.get_token(scope))


class SamianMediaServiceTests(TestCase):
    def test_parse_gallery_from_string(self):
        raw = '[{"filePath": "p/1.jpg", "realFileName": "1.jpg", "size": 1024}]'
        parsed = MediaService.parse_gallery(raw)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["filePath"], "p/1.jpg")

    def test_parse_gallery_empty(self):
        self.assertEqual(MediaService.parse_gallery(None), [])
        self.assertEqual(MediaService.parse_gallery(""), [])
        self.assertEqual(MediaService.parse_gallery("invalid-json"), [])


class SamianLiveIntegrationTests(TestCase):
    """
    Live tests against the actual dev server http://78.109.198.8:8087
    """
    def setUp(self):
        self.client = get_samian_client()

    def test_live_login_and_token(self):
        token = self.client.login()
        self.assertTrue(token)
        self.assertGreater(len(token), 50)

    def test_live_catalog_page(self):
        catalog = CatalogService(client=self.client)
        products = catalog.get_products_page(skip=0, take_count=2)
        self.assertEqual(len(products), 2)
        self.assertIn("id", products[0])

    def test_live_colors_page(self):
        catalog = CatalogService(client=self.client)
        colors = catalog.get_colors_page(skip=0, take_count=2)
        self.assertEqual(len(colors), 2)
        self.assertIn("id", colors[0])

    def test_live_stock_page(self):
        inventory = InventoryService(client=self.client)
        stocks = inventory.get_stock_page(skip=0, take_count=2)
        self.assertEqual(len(stocks), 2)
        self.assertIn("barcodemain_id", stocks[0])
