"""
Management command: keep product and category slugs valid and findable.

- Every row gets slug_key (the lookup form, see apps/website/slugs.py).
- Invalid or empty slugs (invisible marks, characters not allowed in an
  address) are rebuilt from their own text, so the old address still finds the
  page through slug_key; from the title when nothing is left. A rebuilt slug
  gets "-2", "-3" if another row already has that key.

Valid slugs are never changed, since search engines know them. Two valid
slugs can share a key (e.g. «ژيله» and «ژیله»): the exact address still opens
its own page, and storefront lookups decide the rest (views._product_by_slug).
Safe to run any time; runs nightly after the catalog sync.

    python manage.py fix_slugs            # apply
    python manage.py fix_slugs --dry-run  # only report
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.website import slugs
from apps.website.models import Category, Product, ProductSamianLink


class Command(BaseCommand):
    help = "اصلاح و یکتاسازی اسلاگ محصولات و دسته‌ها"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="فقط گزارش، بدون تغییر")

    def handle(self, *args, **options):
        dry = options["dry_run"]
        in_samian = set(ProductSamianLink.objects.values_list("product_id", flat=True))
        with transaction.atomic():
            for model, preferred in ((Category, set()), (Product, in_samian)):
                self._fix(model, preferred, dry)
            if dry:
                transaction.set_rollback(True)

    def _fix(self, model, preferred: set[int], dry: bool):
        rows = list(model.objects.only("id", "title", "slug", "slug_key", "is_deleted"))
        rows.sort(key=lambda r: (r.is_deleted, r.id not in preferred, r.id))
        valid = {r.id for r in rows if slugs.is_valid(r.slug) and slugs.slug_key(r.slug)}
        taken = {slugs.slug_key(r.slug) for r in rows if r.id in valid}
        shared = len(valid) - len(taken)
        rebuilt, changed = [], []
        for r in rows:
            old = r.slug
            if r.id not in valid:
                r.slug = slugs.make_slug(old, taken, fallback=r.title) if slugs.slug_key(old) \
                    else slugs.make_slug(r.title, taken, fallback=str(r.id))
                taken.add(slugs.slug_key(r.slug))
                rebuilt.append((r.id, old, r.slug))
            if r.slug_key != slugs.slug_key(r.slug):
                r.slug_key = slugs.slug_key(r.slug)
                changed.append(r)
        if not dry:
            model.objects.bulk_update(changed, ["slug", "slug_key"], batch_size=2000)

        self.stdout.write(f"{model.__name__}: {len(rows)} ردیف، {len(rebuilt)} اسلاگ نامعتبر بازسازی شد، "
                          f"{shared} اسلاگ معتبر با املای دیگرِ یک اسلاگ دیگر یکی‌اند (دست نخوردند)")
        for pid, old, new in rebuilt[:10]:
            self.stdout.write(f"  {pid}: {old!r} -> {new}")
        if len(rebuilt) > 10:
            self.stdout.write(f"  ... و {len(rebuilt) - 10} مورد دیگر")
