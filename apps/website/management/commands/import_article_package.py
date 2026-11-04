"""
Imports blog article packages (article.zip: article.html and its photos; see
apps/adminapi/article_package/guide.md) from the server's terminal, the same
way the admin's «بارگذاری بسته» does.

  python manage.py import_article_package                 # every zip in content/blog/
  python manage.py import_article_package content/blog/crepe-fabric-guide.zip
  python manage.py import_article_package --draft ...     # keep new articles off the site

A package whose slug is already an article updates that article in place
(views, likes, comments and whether it is shown stay), so running it twice is
harmless. The author is the author of the most recent article unless --author
gives an admin user id.
"""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.adminapi import blog_package
from apps.website.models import Article

PACKAGES_DIR = Path(settings.BASE_DIR) / "content" / "blog"


class Command(BaseCommand):
    help = "بسته‌ی مقاله‌ی بلاگ (zip) را از ترمینال سرور وارد سایت می‌کند؛ بدون مسیر، همه‌ی zipهای content/blog/."

    def add_arguments(self, parser):
        parser.add_argument("packages", nargs="*", help="مسیر zip؛ خالی یعنی همه‌ی content/blog/*.zip")
        parser.add_argument("--draft", action="store_true", help="مقاله‌ی تازه پیش‌نویس بماند")
        parser.add_argument("--author", type=int, default=None, help="شناسه‌ی کاربر ادمین نویسنده")

    def handle(self, *args, packages, draft, author, **options):
        paths = [Path(p) for p in packages] or sorted(PACKAGES_DIR.glob("*.zip"))
        if not paths:
            raise CommandError(f"no packages given and none in {PACKAGES_DIR}")
        if author is None:
            author = Article.objects.exclude(author_id=None).order_by("-id").values_list("author_id", flat=True).first()
        failed = 0
        for path in paths:
            if not path.exists():
                raise CommandError(f"{path} not found")
            with path.open("rb") as f:
                try:
                    r = blog_package.import_package(
                        f, author_id=author, domain=settings.SITE_HOST, publish=False if draft else None,
                    )
                except blog_package.PackageError as exc:
                    failed += 1
                    self.stderr.write(self.style.ERROR(f"{path.name}: {exc}"))
                    for problem in exc.problems:
                        self.stderr.write(f"  - {problem}")
                    continue
            a = r.article
            state = "shown" if a.show_on_page else "draft"
            verb = "created" if r.created else "updated"
            self.stdout.write(self.style.SUCCESS(
                f"{path.name}: {verb} /blog/{a.uniq_url} ({state}), {r.photos} photos, {r.products} product cards"
            ))
            for warning in r.warnings:
                self.stdout.write(f"  ! {warning}")
        if failed:
            raise SystemExit(1)
