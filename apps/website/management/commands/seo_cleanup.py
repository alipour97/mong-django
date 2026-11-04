"""
Takes test and off-topic content off the site before the switch to mong.ir,
the database part of seo-plan/IMPLEMENTATION-ROADMAP.md 0.11:

  - category texts left over from testing (the root «زنانه» category's
    «چند نکته درباره انتخاب مونولوگ برای تست بازیگری sssss…»): emptied, so the
    page shows the guide written from the catalog instead;
  - test articles («تست مطلب», «FileMediatest», testmatla-hj…) and the old
    «لباس ترک عمده از کجا بخرم» (advice to shops on buying Turkish clothes
    wholesale, not for Mong's customers): marked deleted, as the admin's
    delete does; nothing is erased, so an article comes back by unticking
    is_deleted in /django-admin/.

It only shows what it would change unless --apply is given:

  python manage.py seo_cleanup
  python manage.py seo_cleanup --apply
"""
from __future__ import annotations

import re

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.html import strip_tags

from apps.storefront.catalog import clear_caches
from apps.website.models import Article, Category

# What the test texts look like: keyboard runs, the acting-audition sample text, lorem ipsum.
TEST_TEXT = re.compile(r"s{6,}|a{6,}|مونولوگ|تست بازیگری|lorem ipsum", re.IGNORECASE)

TEST_ARTICLE_TITLE = re.compile(r"^\s*(تست|test)|filemediatest", re.IGNORECASE)
TEST_ARTICLE_URLS = {"testmatlab", "testmatla-hj", "test-for-validations", "adasda", "asdasd"}
OFF_TOPIC_ARTICLE_URLS = {"cheap-turkey-dresses"}


class Command(BaseCommand):
    help = "متن‌های آزمایشی دسته‌ها و مقاله‌های آزمایشی یا نامربوط را از سایت برمی‌دارد (بدون --apply فقط نشان می‌دهد)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="تغییرها را واقعاً ذخیره کن")

    def handle(self, *args, apply=False, **options):
        with transaction.atomic():
            categories = self._categories(apply)
            articles = self._articles(apply)
        if apply and categories:
            clear_caches()
        verb = "changed" if apply else "would change (run again with --apply)"
        self.stdout.write(self.style.SUCCESS(f"{categories} categories and {articles} articles {verb}."))

    def _categories(self, apply: bool) -> int:
        changed = 0
        for cat in Category.objects.filter(is_deleted=False).order_by("id"):
            fields = [
                f for f in ("short_description_html", "long_description_html")
                if TEST_TEXT.search(strip_tags(getattr(cat, f) or ""))
            ]
            if not fields:
                continue
            changed += 1
            for f in fields:
                text = " ".join(strip_tags(getattr(cat, f)).split())[:80]
                self.stdout.write(f"category {cat.id} «{cat.title}» {f}: «{text}» -> empty")
                setattr(cat, f, "")
            if apply:
                cat.save(update_fields=fields)
        return changed

    def _articles(self, apply: bool) -> int:
        changed = 0
        for a in Article.objects.filter(is_deleted=False).order_by("id"):
            url = (a.uniq_url or "").strip().strip("/").lower()
            if url in OFF_TOPIC_ARTICLE_URLS:
                why = "off-topic"
            elif url in TEST_ARTICLE_URLS or TEST_ARTICLE_TITLE.search(a.title or ""):
                why = "test"
            else:
                continue
            changed += 1
            self.stdout.write(f"article {a.id} /blog/{a.uniq_url} «{a.title[:60]}» ({why}) -> deleted")
            if apply:
                a.is_deleted = True
                a.save(update_fields=["is_deleted"])
        return changed
