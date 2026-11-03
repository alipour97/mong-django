"""Management command: fetch new approved LEBAZAI images and AI copy (nightly)."""
from django.core.management.base import BaseCommand, CommandError

from apps.erp import jobs


class Command(BaseCommand):
    help = "دریافت عکس‌های تاییدشده و پروفایل هوش مصنوعی از LEBAZAI"

    def handle(self, *args, **opts):
        done = jobs.run("lebazai", log=self.stdout.write)
        if not done.ok:
            raise CommandError(done.error)
