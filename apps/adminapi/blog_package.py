"""
An article package: a zip with article.html and the photos it uses.

    article.zip
      article.html            (or the zip's only .html file)
      images/cover.jpg
      images/...

article.html is an ordinary HTML page; its <head> carries the article's settings:

    <title>                       the title (the page's H1); else the body's first <h1>
    <meta name="description">     the summary under the title and in Google
    <meta name="slug">            the address /blog/<slug>; else made from the title
    <meta name="cover">           the cover photo, a path in the zip; else the first photo
    <meta name="cover-alt">       its alt text; else the title
    <meta name="categories">      names, comma separated; missing ones are created
    <meta name="tags">            the same
    <meta name="status">          draft keeps it off the site; publish (default) shows it
    <meta name="publish-date">    2026-11-10, 2026-11-10T09:00 or 1405/08/19; default now

The <body> is the article. Photos are <img src="images/..."> paths in the zip:
each becomes a gallery file built into the site's WebP sizes, and its src the
/img/u/<id> path. Products are <div data-product="..."> / <div data-products="..., ...">
named by address, id, barcode or name (storefront/blog.resolve_product); they are
stored by id. The body then goes through website/article_html.clean().

How to write a package (for a person or an AI): article_package/guide.md, with a sample in
article_package/sample/; the admin downloads both (Article/Package/guide, /sample).
"""
from __future__ import annotations

import posixpath
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from apps.storefront.blog import resolve_product
from apps.storefront.catalog import norm
from apps.website import article_html, images, slugs
from apps.website.models import Article, ArticleBlogCategory, ArticleTag, ArticleTagRelation, BlogCategory

from . import uploads

MAX_ZIP_BYTES = 60 * 1024 * 1024
MAX_UNPACKED_BYTES = 200 * 1024 * 1024
MAX_FILES = 150
MAX_IMAGE_BYTES = 15 * 1024 * 1024
IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".webp"}
TITLE_MAX = 200
DESCRIPTION_MAX = 500


class PackageError(ValueError):
    """The package cannot be imported; the message is for the admin, in Persian."""

    def __init__(self, message: str, problems: list[str] | None = None):
        super().__init__(message)
        self.problems = problems or []


class SlugTaken(PackageError):
    def __init__(self, article: Article):
        super().__init__(f"مقاله‌ای با آدرس «{article.uniq_url}» از قبل هست: «{article.title}».")
        self.article = article


@dataclass
class Package:
    title: str
    description: str
    slug: str
    body: str
    cover: str
    cover_alt: str
    categories: list[str]
    tags: list[str]
    draft: bool
    publish_date: timezone.datetime | None
    files: dict[str, bytes] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)  # reported together with the body's


def _meta(soup: BeautifulSoup, name: str) -> str:
    tag = soup.find("meta", attrs={"name": name})
    return " ".join((tag.get("content") or "").split()) if tag else ""


def _names(value: str) -> list[str]:
    return list(dict.fromkeys(n.strip() for n in re.split(r"[,،]", value or "") if n.strip()))


def _publish_date(value: str):
    if not value:
        return None
    digits = value.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")).strip()
    if m := re.fullmatch(r"(1[34]\d\d)[/-](\d{1,2})[/-](\d{1,2})(?:[ T](\d{1,2}):(\d{2}))?", digits):
        from .views.dashboard import j2g

        d = j2g(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        dt = timezone.datetime(d.year, d.month, d.day, int(m.group(4) or 9), int(m.group(5) or 0))
    else:
        dt = parse_datetime(digits.replace(" ", "T"))
        if dt is None and (d := parse_date(digits[:10])):
            dt = timezone.datetime(d.year, d.month, d.day, 9, 0)
    if dt is None:
        raise PackageError(f"تاریخ انتشار «{value}» خوانده نشد. نمونه: 2026-11-10 یا 1405/08/19")
    return timezone.make_aware(dt) if timezone.is_naive(dt) else dt


def _read_zip(data) -> tuple[str, dict[str, bytes]]:
    """(path of the html file, {path: bytes} of the other files)."""
    try:
        zf = zipfile.ZipFile(data)
    except zipfile.BadZipFile as exc:
        raise PackageError("فایل زیپ معتبر نیست.") from exc
    entries = [i for i in zf.infolist() if not i.is_dir() and not posixpath.basename(i.filename).startswith(".")
               and "__MACOSX/" not in i.filename]
    if len(entries) > MAX_FILES:
        raise PackageError(f"زیپ بیش از {MAX_FILES} فایل دارد.")
    if sum(i.file_size for i in entries) > MAX_UNPACKED_BYTES:
        raise PackageError("حجم فایل‌های داخل زیپ بیش از اندازه است.")
    files: dict[str, bytes] = {}
    for info in entries:
        name = posixpath.normpath(info.filename.replace("\\", "/")).lstrip("/")
        if name.startswith(".."):
            raise PackageError(f"مسیر نامعتبر در زیپ: {info.filename}")
        files[name] = zf.read(info)
    pages = [n for n in files if n.lower().endswith((".html", ".htm"))]
    named = [n for n in pages if posixpath.basename(n).lower() in ("article.html", "index.html")]
    if len(named) == 1:
        page = named[0]
    elif len(pages) == 1:
        page = pages[0]
    else:
        raise PackageError("زیپ باید یک فایل article.html داشته باشد." if not pages else
                           "زیپ چند فایل HTML دارد؛ مقاله باید article.html باشد.")
    return page, files


def read(data) -> Package:
    page, files = _read_zip(data)
    try:
        html = files.pop(page).decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PackageError("article.html باید با کدگذاری UTF-8 ذخیره شده باشد.") from exc
    soup = BeautifulSoup(html, "html.parser")
    body = soup.body or soup
    title = " ".join((soup.title.get_text() if soup.title else "").split())
    h1 = body.find("h1")
    if h1:
        title = title or " ".join(h1.get_text(" ").split())
        h1.decompose()  # the page writes the title as its H1
    base = posixpath.dirname(page)
    pkg = Package(
        title=title, description=_meta(soup, "description"), slug=_meta(soup, "slug"),
        body=body.decode_contents(), cover=_meta(soup, "cover"), cover_alt=_meta(soup, "cover-alt"),
        categories=_names(_meta(soup, "categories")), tags=_names(_meta(soup, "tags")),
        draft=_meta(soup, "status").lower() == "draft", publish_date=_publish_date(_meta(soup, "publish-date")),
        files={posixpath.normpath(posixpath.relpath(k, base) if base else k): v for k, v in files.items()},
    )
    problems = pkg.problems
    if not pkg.title:
        problems.append("عنوان مقاله (<title> یا <h1>) خالی است.")
    elif len(pkg.title) > TITLE_MAX:
        problems.append(f"عنوان بیش از {TITLE_MAX} نویسه است.")
    if not pkg.description:
        problems.append('توضیح کوتاه (<meta name="description">) خالی است.')
    elif len(pkg.description) > DESCRIPTION_MAX:
        problems.append(f"توضیح کوتاه بیش از {DESCRIPTION_MAX} نویسه است.")
    if not pkg.categories:
        problems.append('دسته‌بندی (<meta name="categories">) خالی است.')
    return pkg


def _local(src: str) -> str | None:
    """A photo's path in the zip, or None for a URL."""
    src = (src or "").strip()
    if not src or re.match(r"(?i)^(https?:|data:|/)", src):
        return None
    return posixpath.normpath(src.split("?")[0].split("#")[0]).lstrip("./") or None


class _Photos:
    """Each photo of the zip stored once in the gallery."""

    def __init__(self, pkg: Package, domain: str):
        self.pkg, self.domain, self.stored = pkg, domain, {}

    def get(self, path: str, alt: str):
        if path in self.stored:
            return self.stored[path]
        data = self.pkg.files.get(path)
        if data is None:
            raise PackageError(f"عکس «{path}» در زیپ نیست.")
        if posixpath.splitext(path)[1].lower() not in IMAGE_TYPES:
            raise PackageError(f"«{path}»: فقط عکس jpg، png یا webp پذیرفته می‌شود.")
        if len(data) > MAX_IMAGE_BYTES:
            raise PackageError(f"«{path}» بزرگ‌تر از ۱۵ مگابایت است.")
        try:
            media = uploads.save_media(SimpleUploadedFile(posixpath.basename(path), data), self.domain, alt[:500])
        except uploads.UploadError as exc:
            raise PackageError(f"«{path}»: {exc}") from exc
        self.stored[path] = media
        return media


def _body(pkg: Package, photos: _Photos) -> tuple[str, list[str]]:
    """The body with zip photos replaced by gallery paths and products by ids; and the problems."""
    soup = BeautifulSoup(pkg.body, "html.parser")
    problems: list[str] = []
    for img in soup.find_all("img"):
        alt = " ".join((img.get("alt") or "").split())
        if not alt:
            caption = img.find_parent("figure") and img.find_parent("figure").find("figcaption")
            alt = caption.get_text(" ", strip=True) if caption else ""
            img["alt"] = alt
            pkg.warnings.append(f"عکس «{img.get('src')}» متن alt نداشت" + ("؛ از زیرنویس گرفته شد." if alt else "."))
        path = _local(img.get("src"))
        if path is None:
            if (img.get("src") or "").startswith("data:"):
                problems.append("عکس‌ها باید فایل داخل زیپ باشند، نه data:")
            continue
        try:
            media = photos.get(path, alt)
        except PackageError as exc:
            problems.append(str(exc))
            continue
        img["src"] = media.url
        if media.width and media.height:
            img["width"], img["height"] = str(media.width), str(media.height)
    for div in soup.find_all("div"):
        for attr in ("data-product", "data-products"):
            if not div.has_attr(attr):
                continue
            ids = []
            for ref in article_html.split_refs(div[attr]):
                p = resolve_product(ref)
                if p is None:
                    problems.append(f"محصول «{ref}» پیدا نشد یا فروش آن فعال نیست.")
                elif p.id not in ids:
                    ids.append(p.id)
            div[attr] = ", ".join(str(i) for i in ids)
            if attr == "data-product" and len(ids) > 1:
                problems.append(f"data-product فقط یک محصول می‌گیرد: «{div[attr]}»؛ برای چند محصول data-products.")
    return article_html.clean(str(soup)), problems


def _slug(pkg: Package) -> str:
    slug = slugs.ai_slug_base(pkg.slug or pkg.title)
    if not slug:
        raise PackageError("آدرس مقاله (slug) نامعتبر است.")
    return slug


def _key(name: str) -> str:
    return " ".join(norm(name).split())


def _named(model, field: str, names: list[str]) -> list[int]:
    """Ids of the rows with these names, creating the missing ones."""
    rows = {_key(getattr(r, field)): r.id for r in model.objects.filter(is_deleted=False)}
    ids = []
    for name in names:
        rid = rows.get(_key(name))
        if rid is None:
            rid = rows[_key(name)] = model.objects.create(**{field: name}, created=timezone.now()).id
        ids.append(rid)
    return ids


@dataclass
class Result:
    article: Article
    created: bool
    photos: int
    products: int
    warnings: list[str]


def import_package(data, *, author_id: int | None, domain: str, replace: bool = False, publish: bool | None = None) -> Result:
    """
    Store the package as an article. An article with the same address is updated
    in place (keeping its views, likes and comments) only when replace is set;
    otherwise SlugTaken. publish overrides the package's status.
    """
    from .views.blog import _set_links, _set_thumbnail

    pkg = read(data)
    slug = _slug(pkg) if pkg.title or pkg.slug else ""
    existing = Article.objects.filter(uniq_url__iexact=slug).first() if slug else None
    if existing and existing.is_deleted:
        raise PackageError(f"آدرس «{slug}» مال مقاله‌ی حذف‌شده‌ای است؛ slug دیگری بدهید.")
    if existing and not replace and not pkg.problems:
        raise SlugTaken(existing)
    with transaction.atomic():
        photos = _Photos(pkg, domain)
        body, problems = _body(pkg, photos)
        problems = pkg.problems + problems
        cover_path = _local(pkg.cover) if pkg.cover else next(iter(photos.stored), None)
        if not pkg.cover and cover_path:
            pkg.warnings.append(f"عکس کاور مشخص نشده بود؛ «{cover_path}» کاور شد.")
        cover = None
        if not cover_path:
            problems.append('عکس کاور (<meta name="cover">) لازم است.')
        else:
            try:
                cover = photos.get(cover_path, pkg.cover_alt or pkg.title)
            except PackageError as exc:
                problems.append(str(exc))
        if problems:
            _forget(photos)
            raise PackageError("مقاله وارد نشد.", list(dict.fromkeys(problems)))
        if pkg.cover_alt and cover.alternative != pkg.cover_alt:
            cover.alternative = pkg.cover_alt[:500]
            cover.save(update_fields=["alternative"])
        now = timezone.now()
        a = existing or Article(created=now, view_count=0, author_id=author_id)
        a.title, a.uniq_url, a.description, a.content = pkg.title, slug, pkg.description, body
        a.show_on_page = (not pkg.draft) if publish is None else publish
        a.publish_date = pkg.publish_date or (a.publish_date if existing else now)
        a.last_modified = now
        a.is_deleted = False
        a.save()
        _set_thumbnail(a, cover)
        a.save(update_fields=["thumbnail"])
        _set_links(ArticleBlogCategory, "category_id", a, _named(BlogCategory, "title", pkg.categories))
        _set_links(ArticleTagRelation, "tag_id", a, _named(ArticleTag, "name", pkg.tags))
    products = len(article_html.product_refs(body))
    return Result(a, existing is None, len(photos.stored), products, pkg.warnings)


def _forget(photos: _Photos) -> None:
    """The files of an import that was rolled back: its gallery rows are gone, so are they."""
    for media in photos.stored.values():
        key = media.url[len(settings.PUBLIC_IMG_PATH) + 1:]
        if media.url.startswith(f"{settings.PUBLIC_IMG_PATH}/u/"):
            shutil.rmtree(images.img_root() / key, ignore_errors=True)
            for original in (Path(settings.MEDIA_ROOT) / "uploads").glob(f"*/*/{key[2:]}.*"):
                original.unlink(missing_ok=True)
