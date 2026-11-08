"""
Store the main categories' search copy (apps/website/category_copy.py) on Category:
seo_title, seo_description and long_description_html.

    manage.py write_category_copy            # show what would change
    manage.py write_category_copy --apply    # write it
    manage.py write_category_copy --apply --force   # also replace copy the admin already wrote

Without --force a field the admin has already filled is left alone, so running it
again never undoes an edit made in the Django admin.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.website.category_copy import COPY
from apps.website.models import Category
from apps.website.slugs import slug_key

FIELDS = {"seo_title": "seo_title", "seo_description": "seo_description", "html": "long_description_html"}


class Command(BaseCommand):
    help = "Write the SEO title, meta description and «درباره …» text of the main categories."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="write the changes (default: only show them)")
        parser.add_argument("--force", action="store_true", help="replace copy already written in the admin")

    @transaction.atomic
    def handle(self, *args, apply=False, force=False, **opts):
        written = 0
        for slug, copy in COPY.items():
            cat = Category.objects.filter(is_deleted=False, slug_key=slug_key(slug)).first()
            if not cat:
                self.stdout.write(self.style.WARNING(f"not found: {slug}"))
                continue
            changed = []
            for key, field in FIELDS.items():
                new = copy[key].strip()
                old = (getattr(cat, field) or "").strip()
                if old == new or (old and not force):
                    continue
                setattr(cat, field, new)
                changed.append(field)
            if changed:
                written += 1
                if apply:
                    cat.save(update_fields=changed)
            self.stdout.write(f"{slug}: {', '.join(changed) or 'unchanged'}")
        if apply and written:
            from apps.storefront.catalog import clear_caches

            clear_caches()
        verb = "wrote" if apply else "would write"
        self.stdout.write(self.style.SUCCESS(f"{verb} {written} categories" + ("" if apply else " (run with --apply)")))
