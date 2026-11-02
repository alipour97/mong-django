"""Management command: fetch new approved LEBAZAI images and AI copy (nightly)."""
import requests
from django.core.management.base import BaseCommand, CommandError

from apps.erp import lebazai
from apps.erp.connector import SourceError
from apps.storefront import catalog


class Command(BaseCommand):
    help = "دریافت عکس‌های تاییدشده و پروفایل هوش مصنوعی از LEBAZAI"

    def handle(self, *args, **opts):
        try:
            lebazai.sync_images(self.stdout.write)
            lebazai.sync_profiles(self.stdout.write)
        except (requests.RequestException, SourceError) as exc:
            raise CommandError(str(exc)) from exc
        catalog.clear_caches()
