"""
Management command: move PostgreSQL id counters past the rows already in each
table (see apps/website/sequences.py). Run after importing rows with their own
ids. Safe to run any time.

    python manage.py fix_sequences
"""
from __future__ import annotations

from django.apps import apps
from django.core.management.base import BaseCommand

from apps.website.sequences import move_past_ids


class Command(BaseCommand):
    help = "جلو بردن شمارنده‌ی id جدول‌ها از بزرگ‌ترین id موجود"

    def handle(self, *args, **options):
        moved = move_past_ids(apps.get_models())
        for line in moved:
            self.stdout.write(line)
        self.stdout.write(self.style.SUCCESS(f"{len(moved)} شمارنده جلو رفت."))
