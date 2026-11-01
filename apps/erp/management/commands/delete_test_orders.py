"""Management command: remove the orders paid in a gateway's test mode, before the site goes live."""
from django.core.management.base import BaseCommand

from apps.website.models import Invoice


class Command(BaseCommand):
    help = "حذف سفارش‌هایی که در حالت تست درگاه پرداخت شده‌اند"

    def handle(self, *args, **opts):
        count = Invoice.objects.filter(is_test=True).count()
        Invoice.objects.filter(is_test=True).delete()
        self.stdout.write(f"{count} test orders removed")
