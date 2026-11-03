"""Management command: every branch's sales for the best-seller sort, and the old site's new orders (hourly)."""
from django.core.management.base import BaseCommand, CommandError

from apps.erp import jobs


class Command(BaseCommand):
    help = "همگام‌سازی داده‌های فروش (پرفروش‌ترین‌ها و سفارش‌های تازهٔ سایت قدیم)"

    def handle(self, *args, **opts):
        done = jobs.run("sales", log=self.stdout.write)
        if not done.ok:
            raise CommandError(done.error)
