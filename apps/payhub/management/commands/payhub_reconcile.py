from django.core.management.base import BaseCommand

from apps.payhub import service


class Command(BaseCommand):
    help = "Asks SnappPay about unclear payments and refunds what was never confirmed (run from cron)."

    def handle(self, *args, **options):
        self.stdout.write(f"payhub: {service.reconcile()} payments looked at")
