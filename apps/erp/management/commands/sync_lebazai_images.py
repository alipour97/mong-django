"""Management command: fetch new approved LEBAZAI images and AI copy (nightly)."""
from django.core.management.base import BaseCommand, CommandError

from apps.erp import jobs


class Command(BaseCommand):
    help = "دریافت عکس‌های تاییدشده و پروفایل هوش مصنوعی از LEBAZAI"

    def handle(self, *args, **opts):
        failed = [done.error for done in (jobs.run(key, log=self.stdout.write) for key in ("images", "profiles")) if not done.ok]
        if failed:
            raise CommandError("; ".join(failed))
