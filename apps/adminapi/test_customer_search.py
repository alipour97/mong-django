from django.test import TestCase
from rest_framework.test import APIClient

from apps.adminapi.models import AdminUser
from apps.website.models import Customer


class CustomerSearchTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(AdminUser.objects.create(username="customer-search", cellphone="09120000000"))
        self.first = Customer.objects.create(first_name="علی", last_name="رضایی", cellphone="09120000001")
        self.second = Customer.objects.create(first_name="علی", last_name="رضایی", cellphone="09120000002")
        self.url = "/api/admin/v1/Customer/GetCustomers"

    def ids(self, params):
        response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200)
        return {item["customerId"] for item in response.json()["data"]["result"]["items"]}

    def test_full_name_search(self):
        self.assertEqual(self.ids({"SearchText": "علی   رضایی"}), {self.first.id, self.second.id})

    def test_customer_id_selects_only_the_invoice_customer(self):
        self.assertEqual(self.ids({"CustomerId": self.first.id}), {self.first.id})
        self.assertEqual(self.ids({"CustomerId": 99999999}), set())
