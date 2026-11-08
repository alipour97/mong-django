"""
Article/* — the blog, as the old Article controller.

The thumbnail is a gallery file (fileMediaId): it is stored on the article and
as its MediaAttachment (table Articles), like the old API did.

    GET  Article/All?Search=&AuthorId=&CreateDateFrom=&CreateDateTo=&pageNumber=&pageSize=
    GET  Article/<id>        GET Article/SoftDelete/<id>        GET Article/CheckUniqUrl?uniqUrl=
    POST Article {article: {title, content, showOnPage, authorId, publishDate, articleDescription, articleUniqUrl, fileMediaId}, categoryIds, tagIds}
    POST Article/<id> (same body)
    GET  Article/Categories | Article/Tags        POST Article/categories "title" | Article/tags "name"
    GET  Article/SoftDeleteCategory?categoryId= | Article/SoftDeleteTag?tagId=
    POST Article/Import (multipart "file": an article package zip, "publish") -> {result: {id, ...}}; the same address updates that article
    GET  Article/<id>/Preview                    the article as the site shows it, published or not
    GET  Article/Package/guide | Article/Package/sample   how to write a package, and a sample zip

The content is stored through website/article_html.clean(), from the editor and from a package alike.
"""
from __future__ import annotations

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.response import Response

from apps.storefront import blog as site_blog
from apps.storefront.envelope import jalali
from apps.website import article_html
from apps.website.models import (
    Article, ArticleBlogCategory, ArticleTag, ArticleTagRelation, BlogCategory, FileMedia, MediaAttachment,
)

from ..envelope import fail, ok
from ..models import AdminUser
from ..paging import int_list, paginated, to_int
from .auth import AdminView
from .comments import _date
from .gallery import _url

TABLE = MediaAttachment.Table.ARTICLES
NOT_FOUND = "بلاگ یافت نشد"


def jalali_time(dt) -> str | None:
    """1404/05/06 - 12:30:00, the format the panel parses (jYYYY/jMM/jDD - HH:mm:ss)."""
    if dt is None:
        return None
    local = timezone.localtime(dt)
    return f"{jalali(local, with_time=False)} - {local:%H:%M:%S}"


def _articles(request=None):
    """Live articles; a blog writer sees and changes only their own."""
    qs = Article.objects.filter(is_deleted=False)
    if request is not None and request.user.is_writer:
        qs = qs.filter(author_id=request.user.id)
    return qs


class BlogView(AdminView):
    writer_ok = True


def _authors(ids) -> dict[int, str]:
    return {u.id: f"{u.first_name} {u.last_name}" for u in AdminUser.objects.filter(id__in=[i for i in ids if i])}


class ListView(BlogView):
    def get(self, request):
        q = request.query_params
        qs = _articles(request)
        if begin := _date(q.get("CreateDateFrom")):
            qs = qs.filter(created__gte=begin)
        if end := _date(q.get("CreateDateTo"), end=True):
            qs = qs.filter(created__lte=end)
        if (author := to_int(q.get("AuthorId"))) is not None:
            qs = qs.filter(author_id=author)
        if search := (q.get("Search") or q.get("search") or "").strip():
            qs = qs.filter(Q(title__icontains=search) | Q(content__icontains=search) | Q(description__icontains=search))
        qs = qs.annotate(
            n_likes=Count("likes", filter=Q(likes__liked=True, likes__is_deleted=False), distinct=True),
            n_comments=Count("comments", filter=Q(comments__status=1, comments__is_deleted=False), distinct=True),
        ).order_by("-created", "-id")
        rows = list(qs)
        authors = _authors({a.author_id for a in rows})

        def item(a: Article) -> dict:
            return {
                # createDate is converted to Jalali by the panel (moment), so it is sent as ISO.
                "id": a.id, "title": a.title, "createDate": a.created.isoformat() if a.created else None,
                "publishDate": jalali(a.publish_date, with_time=False),
                "viewCount": a.view_count, "showOnPage": a.show_on_page, "authorName": authors.get(a.author_id, " "),
                "likeCount": a.n_likes, "commentCount": a.n_comments, "comment": a.n_comments,
            }

        return ok({"result": paginated(rows, to_int(q.get("pageNumber"), 1), to_int(q.get("pageSize"), 10), item)})


class DetailView(BlogView):
    def get(self, request, article_id: int):
        a = _articles(request).filter(id=article_id).first()
        if not a:
            return fail(NOT_FOUND, 404)
        att = MediaAttachment.objects.filter(table=TABLE, record_id=a.id, is_deleted=False).order_by("-id").first()
        return ok({"result": {
            "id": a.id, "title": a.title, "articleUniqUrl": a.uniq_url, "content": a.content,
            "publishDate": jalali_time(a.publish_date), "viewCount": a.view_count,
            "authorName": _authors([a.author_id]).get(a.author_id, " "), "authorId": a.author_id,
            "tags": [{"id": t.id, "name": t.name} for t in a.tags.filter(is_deleted=False, article_links__is_deleted=False).distinct()],
            "categories": [
                {"id": c.id, "title": c.title}
                for c in a.categories.filter(is_deleted=False, article_links__is_deleted=False).distinct()
            ],
            "showOnPage": a.show_on_page, "description": a.description, "articleThumbnail": _url(a.thumbnail) if a.thumbnail else "",
            "fileMediaId": to_int(att.map_id) if att else None, "mediaId": att.id if att else None,
            "alternative": att.alternative if att else "", "tooltipTitle": att.tooltip_title if att else "",
        }})

    def post(self, request, article_id: int):
        a = _articles(request).filter(id=article_id).first()
        if not a:
            return fail(NOT_FOUND, 404)
        result = _save(request, a)
        return result if isinstance(result, Response) and result.status_code >= 400 else Response({"article": a.title})


def _set_links(model, field: str, article: Article, ids: list[int]) -> None:
    links = model.objects.filter(article=article)
    links.exclude(**{f"{field}__in": ids}).update(is_deleted=True)
    links.filter(**{f"{field}__in": ids}).update(is_deleted=False)
    have = set(links.values_list(field, flat=True))
    model.objects.bulk_create(model(article=article, **{field: i}, created=timezone.now()) for i in ids if i not in have)


def _set_thumbnail(a: Article, file_media: FileMedia) -> None:
    MediaAttachment.objects.filter(table=TABLE, record_id=a.id).delete()
    MediaAttachment.objects.create(
        table=TABLE, record_id=a.id, media_url=file_media.url, map_id=str(file_media.id),
        alternative=file_media.alternative, tooltip_title=file_media.tooltip_title, created=timezone.now(),
    )
    a.thumbnail = file_media.url
    if not file_media.used:
        FileMedia.objects.filter(id=file_media.id).update(used=True)


def _author(value) -> int | None:
    uid = to_int(value)
    return uid if uid and AdminUser.objects.filter(id=uid, is_deleted=False).exists() else None


def _save(request, a: Article | None):
    d = request.data if isinstance(request.data, dict) else {}
    art = d.get("article") or {}
    title, uniq = (art.get("title") or "").strip(), (art.get("articleUniqUrl") or "").strip().strip("/")
    if not title or not uniq:
        return fail("عنوان و آدرس یکتا الزامی است", 400)
    if Article.objects.filter(uniq_url__iexact=uniq).exclude(id=a.id if a else None).exists():
        return fail(f"مقاله‌ای با شناسه آدرس '{uniq}' از قبل وجود دارد.", 400)
    media_id = to_int(art.get("fileMediaId"))
    file_media = FileMedia.objects.filter(id=media_id, is_deleted=False).first() if media_id else None
    if a is None and file_media is None:
        return fail("خطا در ثبت تصویر شاخص.", 400)
    cat_ids = list(BlogCategory.objects.filter(id__in=int_list(d.get("categoryIds")), is_deleted=False).values_list("id", flat=True))
    tag_ids = list(ArticleTag.objects.filter(id__in=int_list(d.get("tagIds")), is_deleted=False).values_list("id", flat=True))
    with transaction.atomic():
        is_new = a is None
        a = a or Article(created=timezone.now(), view_count=0, author_id=request.user.id)
        # An admin may name another author (a writer's article posted for them); a writer always writes as themself.
        if not request.user.is_writer and (author := _author(art.get("authorId"))):
            a.author_id = author
        a.title, a.uniq_url = title, uniq
        a.content, a.description = article_html.clean(art.get("content") or ""), art.get("articleDescription") or ""
        a.show_on_page = bool(art.get("showOnPage"))
        a.publish_date = _date(art.get("publishDate")) or (timezone.now() if is_new else a.publish_date)
        a.last_modified = timezone.now()
        a.save()
        if file_media and file_media.url != a.thumbnail:
            _set_thumbnail(a, file_media)
            a.save(update_fields=["thumbnail"])
        _set_links(ArticleBlogCategory, "category_id", a, cat_ids)
        _set_links(ArticleTagRelation, "tag_id", a, tag_ids)
    return ok({"result": a.title})


class CreateView(BlogView):
    def post(self, request):
        return _save(request, None)


class DeleteView(BlogView):
    def get(self, request, article_id: int):
        n = _articles(request).filter(id=article_id).update(is_deleted=True, last_modified=timezone.now())
        return ok({"result": True}) if n else fail("article not found.", 404)


class CheckUrlView(BlogView):
    def get(self, request):
        uniq = (request.query_params.get("uniqUrl") or "").strip().strip("/")
        return ok({"result": bool(uniq) and not Article.objects.filter(uniq_url__iexact=uniq).exists()})


def _text(request) -> str:
    data = request.data
    return (data if isinstance(data, str) else "").strip()


class CategoriesView(BlogView):
    def get(self, request):
        return ok({"result": [
            {"id": c.id, "title": c.title, "inMainPage": c.in_main_page} for c in BlogCategory.objects.filter(is_deleted=False)
        ]})

    def post(self, request):
        title = _text(request)
        if not title:
            return fail("عنوان دسته الزامی است", 400)
        c = BlogCategory.objects.create(title=title, created=timezone.now())
        return ok({"result": {"id": c.id, "title": c.title, "inMainPage": c.in_main_page, "parentId": c.parent_id}})


class TagsView(BlogView):
    def get(self, request):
        return ok({"result": [{"id": t.id, "name": t.name} for t in ArticleTag.objects.filter(is_deleted=False)]})

    def post(self, request):
        name = _text(request)
        if not name:
            return fail("نام تگ الزامی است", 400)
        tag = next((t for t in ArticleTag.objects.filter(is_deleted=False) if t.name.strip().lower() == name.lower()), None)
        tag = tag or ArticleTag.objects.create(name=name, created=timezone.now())
        return Response({"id": tag.id, "name": tag.name}, status=201)


class DeleteCategoryView(AdminView):
    def get(self, request):
        n = BlogCategory.objects.filter(id=to_int(request.query_params.get("categoryId")), is_deleted=False).update(is_deleted=True)
        return ok({"result": True}) if n else fail("category not found.", 404)


class DeleteTagView(AdminView):
    def get(self, request):
        n = ArticleTag.objects.filter(id=to_int(request.query_params.get("tagId")), is_deleted=False).update(is_deleted=True)
        return ok({"res": True}) if n else fail("tag not found.", 404)


class ImportView(BlogView):
    def post(self, request):
        from .. import blog_package

        uploaded = request.FILES.get("file")
        if not uploaded:
            return fail("فایل زیپ مقاله ارسال نشده است", 400)
        if uploaded.size > blog_package.MAX_ZIP_BYTES:
            return fail("حجم زیپ بیش از ۶۰ مگابایت است", 400)
        publish = str(request.data.get("publish", "")).lower()
        try:
            r = blog_package.import_package(
                uploaded, author_id=request.user.id, domain=request.get_host(),
                only_author=request.user.id if request.user.is_writer else None,
                publish=None if publish == "" else publish in ("1", "true", "yes"),
            )
        except blog_package.PackageError as exc:
            return fail(str(exc), 400, {"problems": exc.problems})
        a = r.article
        return ok({"result": {
            "id": a.id, "title": a.title, "articleUniqUrl": a.uniq_url, "showOnPage": a.show_on_page,
            "created": r.created, "photos": r.photos, "products": r.products, "warnings": r.warnings,
        }})


class PreviewView(BlogView):
    def get(self, request, article_id: int):
        a = _articles(request).filter(id=article_id).first()
        if not a:
            return fail(NOT_FOUND, 404)
        return ok({"result": site_blog.page_data(a)})


class PackageFileView(BlogView):
    """The guide to give an AI (or a writer) and a sample package (adminapi/article_package/)."""

    def get(self, request, kind: str):
        import io
        import zipfile
        from pathlib import Path

        from django.http import HttpResponse

        from django.conf import settings

        docs = Path(__file__).resolve().parent.parent / "article_package"
        if kind == "guide":
            # {site}: where the AI reads product pages, new.mong.ir now and mong.ir after the switch.
            guide = (docs / "guide.md").read_text(encoding="utf-8").replace("{site}", settings.SITE_URL)
            response = HttpResponse(guide.encode(), content_type="text/markdown; charset=utf-8")
            response["Content-Disposition"] = 'attachment; filename="mong-blog-article-guide.md"'
            return response
        if kind != "sample":
            return fail(NOT_FOUND, 404)
        out = io.BytesIO()
        folder = docs / "sample"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(folder.rglob("*")):
                if f.is_file():
                    zf.write(f, f.relative_to(folder).as_posix())
        response = HttpResponse(out.getvalue(), content_type="application/zip")
        response["Content-Disposition"] = 'attachment; filename="mong-blog-sample-article.zip"'
        return response
