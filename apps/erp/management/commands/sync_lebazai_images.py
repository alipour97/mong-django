"""Management command: fetch new approved LEBAZAI images (nightly); sync_erp shows them on its next run."""
import requests
from django.core.management.base import BaseCommand, CommandError

from apps.erp import lebazai
from apps.erp.connector import SourceError


class Command(BaseCommand):
    help = "دریافت عکس‌های تاییدشده از LEBAZAI"

    def handle(self, *args, **opts):
        try:
            lebazai.sync_images(self.stdout.write)
        except (requests.RequestException, SourceError) as exc:
            raise CommandError(str(exc)) from exc
