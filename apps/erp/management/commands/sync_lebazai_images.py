"""Management command: fetch new approved LEBAZAI images and AI copy (nightly); sync_erp shows the images on its next run."""
import requests
from django.core.management.base import BaseCommand, CommandError

from apps.erp import lebazai
from apps.erp.connector import SourceError


class Command(BaseCommand):
    help = "دریافت عکس‌های تاییدشده و پروفایل هوش مصنوعی از LEBAZAI"

    def handle(self, *args, **opts):
        try:
            lebazai.sync_images(self.stdout.write)
            lebazai.sync_profiles(self.stdout.write)
        except (requests.RequestException, SourceError) as exc:
            raise CommandError(str(exc)) from exc
