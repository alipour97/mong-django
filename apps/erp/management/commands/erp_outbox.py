"""Management command: hand paid orders to the sales software and note the ones it has taken."""
from django.core.management.base import BaseCommand

from apps.erp import outbox


class Command(BaseCommand):
    help = "ارسال فاکتورهای پرداخت‌شده به نرم‌افزار فروش"

    def handle(self, *args, **opts):
        outbox.run(self.stdout.write)
