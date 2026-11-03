"""Management command: remove the orders paid in a gateway's test mode, before the site goes live."""
from django.core.management.base import BaseCommand

from apps.website.admin import delete_invoices
from apps.website.models import Invoice


class Command(BaseCommand):
    help = "حذف سفارش‌هایی که در حالت تست درگاه پرداخت شده‌اند"

    def handle(self, *args, **opts):
        invoices = Invoice.objects.filter(is_test=True)
        count = invoices.count()
        left = delete_invoices(invoices)
        self.stdout.write(f"{count} test orders removed")
        if left:
            self.stdout.write(f"still in Dadehfa, to void by hand: {', '.join(map(str, left))}")
