"""
Management command: build the site's categories and products from Samian.

Categories are Samian departments (codingdepartment): level 1 (e.g. زنانه),
level 2 (روپوش) and level 3 (كاپشن). Only departments that hold Mong products,
and their parents, become categories. A department is matched once to the
existing category with the same path of titles, so its id, slug, images and
descriptions stay; a department with no category yet gets a new one, switched
off on the site until it is turned on in the admin. Category titles follow
Samian.

Every Mong product in Samian gets a site product: linked ones take their
title and category from Samian; a new Samian product gets a site product with
a slug made from its name (apps/website/slugs.py). Slugs, descriptions,
tags and the other site-only fields are never overwritten.

Runs nightly after the catalog sync.

    python manage.py sync_site_catalog
    python manage.py sync_site_catalog --dry-run
"""
from __future__ import annotations

from collections import defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.samian.models import SamianDepartment, SamianProduct
from apps.storefront.catalog import clear_caches, listing_rows, norm
from apps.website import slugs
from apps.website.models import Category, Product, ProductSamianLink


def _path(d: SamianDepartment) -> tuple[str, ...]:
    parts = (d.department1, d.department2, d.department3)[: d.level + 1]
    return tuple(norm(p) for p in parts)


class Command(BaseCommand):
    help = "ساخت دسته‌ها و محصولات سایت از دپارتمان‌ها و کالاهای سامیان"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="فقط گزارش، بدون تغییر")

    def handle(self, *args, **opts):
        with transaction.atomic():
            category_by_dept = self._categories()
            self._products(category_by_dept)
            if opts["dry_run"]:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("dry-run: چیزی ذخیره نشد"))
        if not opts["dry_run"]:
            clear_caches()

    # ------------------------------------------------------------------ categories
    def _categories(self) -> dict[int, Category]:
        used = set(SamianProduct.objects.exclude(samian_department=None).values_list("samian_department_id", flat=True))
        depts = list(SamianDepartment.objects.all())
        by_path: dict[tuple, SamianDepartment] = {}
        for d in sorted(depts, key=lambda d: d.samian_id):
            by_path.setdefault(_path(d), d)
        # Departments with products, and every department above them.
        wanted: dict[tuple, SamianDepartment] = {}
        for d in depts:
            if d.pk in used:
                p = _path(d)
                for n in range(1, len(p) + 1):
                    if p[:n] in by_path:
                        wanted[p[:n]] = by_path[p[:n]]

        cats = list(Category.objects.all())
        by_id = {c.id: c for c in cats}

        def cat_path(c: Category) -> tuple:
            chain, seen = [], set()
            while c and c.id not in seen:
                seen.add(c.id)
                chain.append(norm(c.title))
                c = by_id.get(c.parent_id)
            return tuple(reversed(chain))

        linked = {c.samian_department_id: c for c in cats if c.samian_department_id}
        # Live, on-site, oldest first: the category that keeps a department's id.
        candidates: dict[tuple, Category] = {}
        for c in sorted(cats, key=lambda c: (c.is_deleted, not c.is_online_active, c.id)):
            candidates.setdefault(cat_path(c), c)

        taken = set(Category.objects.values_list("slug_key", flat=True))
        result: dict[int, Category] = {}
        created, matched, renamed = [], 0, 0
        for path in sorted(wanted, key=len):
            d = wanted[path]
            title = (d.department1, d.department2, d.department3)[d.level].strip()
            parent = result.get(wanted[path[:-1]].samian_id) if len(path) > 1 else None
            c = linked.get(d.samian_id) or candidates.get(path)
            if c is None:
                base = title if slugs.slug_key(title) not in taken or parent is None else f"{parent.title} {title}"
                c = Category(
                    title=title, parent=parent, slug=slugs.make_slug(base, taken), group_level=d.level,
                    is_online_active=False, created=timezone.now(), samian_department_id=d.samian_id,
                )
                c.save()
                taken.add(c.slug_key)
                created.append(c)
            else:
                matched += not c.samian_department_id
                changed = []
                if c.samian_department_id != d.samian_id:
                    Category.objects.filter(samian_department_id=d.samian_id).exclude(pk=c.pk).update(samian_department_id=None)
                    c.samian_department_id = d.samian_id
                    changed.append("samian_department_id")
                if c.title != title:
                    c.title = title
                    renamed += 1
                    changed.append("title")
                if parent and c.parent_id != parent.id:
                    c.parent = parent
                    changed.append("parent")
                if c.is_deleted:
                    c.is_deleted = False
                    changed.append("is_deleted")
                if changed:
                    c.save(update_fields=changed)
            result[d.samian_id] = c

        self.stdout.write(f"دسته‌ها: {len(result)} دپارتمان دارای کالا، {matched} به دسته‌ی موجود وصل شد، "
                          f"{len(created)} دسته‌ی جدید (خاموش)، {renamed} عنوان از سامیان")
        for c in created[:15]:
            self.stdout.write(f"  جدید: {c.id} {c.parent.title + ' › ' if c.parent else ''}{c.title} [{c.slug}]")
        return result

    # ------------------------------------------------------------------ products
    def _products(self, category_by_dept: dict[int, Category]) -> None:
        mong_brand = settings.STOREFRONT_BRAND_IDS[0] if settings.STOREFRONT_BRAND_IDS else None
        links = dict(ProductSamianLink.objects.values_list("samian_product_id", "product_id"))
        dept_samian_id = dict(SamianDepartment.objects.values_list("pk", "samian_id"))
        sps = list(SamianProduct.objects.all())
        products = Product.objects.in_bulk([links[sp.samian_id] for sp in sps if sp.samian_id in links])

        listed_before = {p.id: p.category_id for p in products.values() if not p.is_deleted}
        on_site = {r.id for r in listing_rows()}
        hidden = []  # on the site now, moved to a category that is off
        codes = defaultdict(int)
        for code in Product.objects.values_list("barcode", flat=True):
            codes[code] += 1
        recategorized, retitled, updates, skipped = defaultdict(int), 0, [], []
        taken = set(Product.objects.values_list("slug_key", flat=True))
        new_products, new_links = [], []
        for sp in sps:
            cat = category_by_dept.get(dept_samian_id.get(sp.samian_department_id))
            pid = links.get(sp.samian_id)
            if pid and pid in products:
                p = products[pid]
                changed = False
                if cat and p.category_id != cat.id:
                    recategorized[(listed_before.get(p.id), cat.id)] += 1
                    if p.id in on_site and not cat.is_online_active:
                        hidden.append((p, cat))
                    p.category_id = cat.id
                    changed = True
                # Rule: If Samian is empty, do NOT overwrite existing values. Only fill empty values from Samian.
                name = " ".join(sp.name.split())
                if not p.title and name:
                    p.title = name
                    retitled += 1
                    changed = True
                elif name and not getattr(p, "has_manual_slug", False) and not hasattr(p, "ai_profile") and " ".join(p.title.split()) != name:
                    p.title = name
                    retitled += 1
                    changed = True

                desc = (sp.description or "").strip()
                if not p.description and desc:
                    p.description = desc
                    changed = True

                season = (sp.season or "").strip()
                if not p.product_season_title and season:
                    p.product_season_title = season
                    changed = True

                style = (sp.style or "").strip()
                if not p.product_style_title and style:
                    p.product_style_title = style
                    changed = True

                if changed:
                    updates.append(p)
            elif not sp.subcode.isdigit() or codes.get(sp.subcode):
                # Code missing ("نامعتبر") or shared with site products link_samian_products could
                # not tell apart: linked by hand in the admin, never duplicated here.
                skipped.append(sp)
            elif sp.name:
                name = " ".join(sp.name.split())
                p = Product(
                    title=name, slug=slugs.make_slug(name, taken, fallback=sp.subcode), category=cat,
                    brand_id=mong_brand, barcode=sp.subcode, is_active=sp.is_active, is_saleable=sp.is_saleable,
                    created=sp.create_date or timezone.now(), last_modified=timezone.now(),
                    description=(sp.description or "").strip(),
                    product_season_title=(sp.season or "").strip(),
                    product_style_title=(sp.style or "").strip(),
                )
                p.slug_key = slugs.slug_key(p.slug)
                taken.add(p.slug_key)
                new_products.append((p, sp))

        Product.objects.bulk_update(
            updates,
            ["category", "title", "description", "product_season_title", "product_style_title"],
            batch_size=2000,
        )
        for p, sp in new_products:
            p.save()
            new_links.append(ProductSamianLink(product=p, samian_product_id=sp.samian_id, method=ProductSamianLink.Method.AUTO))
        ProductSamianLink.objects.bulk_create(new_links)

        moved = sum(recategorized.values())
        self.stdout.write(f"محصولات: {len(sps)} کالای سامیان، {len(new_products)} محصول جدید ساخته شد، "
                          f"دسته‌ی {moved} محصول و عنوان {retitled} محصول از سامیان به‌روز شد، "
                          f"{len(skipped)} کالا بدون کد معتبر یا با کد تکراری کنار گذاشته شد")
        for p, cat in hidden:
            self.stdout.write(self.style.WARNING(
                f"  از سایت خارج می‌شود: {p.id} {p.title} → {cat.parent.title if cat.parent else ''} › {cat.title} (خاموش)"))
        titles = dict(Category.objects.values_list("id", "title"))
        for (old, new), n in sorted(recategorized.items(), key=lambda kv: -kv[1])[:15]:
            self.stdout.write(f"  {n:>5} محصول: {titles.get(old, '—')} ({old}) → {titles.get(new)} ({new})")
        for p, _ in new_products[:10]:
            self.stdout.write(f"  جدید: {p.id} {p.title} [{p.slug}] دسته: {p.category.title if p.category else '—'}")
