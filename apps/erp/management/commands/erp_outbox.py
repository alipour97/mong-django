"""Management command: hand paid orders to the sales software and note the ones it has taken."""
from django.core.management.base import BaseCommand, CommandError

from apps.erp import jobs


class Command(BaseCommand):
    help = "ارسال فاکتورهای پرداخت‌شده به نرم‌افزار فروش"

    def handle(self, *args, **opts):
        done = jobs.run("outbox", log=self.stdout.write)
        if not done.ok:
            raise CommandError(done.error)
