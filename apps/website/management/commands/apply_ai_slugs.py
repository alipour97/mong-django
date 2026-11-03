"""
Gives every product with a LEBAZAI AI title its address from that title
(apps/website/services/ai_slugs.py). New profiles get it on sync; this is for
the ones already stored. The old address keeps working with a 301.

  python manage.py apply_ai_slugs --dry-run
  python manage.py apply_ai_slugs
"""
from django.core.management.base import BaseCommand

from apps.website.models import ProductAIProfile
from apps.website.services.ai_slugs import ai_slug_for, apply_ai_slug


class Command(BaseCommand):
    help = "آدرس محصولات را از عنوان هوش مصنوعی (LEBAZAI) می‌سازد؛ آدرس قبلی با 301 به آدرس جدید می‌رود."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="فقط نشان بده چه آدرس‌هایی عوض می‌شوند")

    def handle(self, *args, dry_run=False, **options):
        profiles = ProductAIProfile.objects.exclude(title="").select_related("product").order_by("product_id")
        changed = 0
        for profile in profiles:
            p = profile.product
            slug = ai_slug_for(p, profile.title) if dry_run else apply_ai_slug(p, profile.title)
            if slug:
                changed += 1
                if dry_run or changed <= 5:
                    self.stdout.write(f"{p.barcode}: {p.slug if dry_run else '…'} -> {slug}")
        verb = "would change" if dry_run else "changed"
        self.stdout.write(self.style.SUCCESS(f"{changed} of {profiles.count()} product addresses {verb}."))
