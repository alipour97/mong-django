"""
Article/* on the site: the blog, as api.mong.ir served it.

An article is on the site while show_on_page is on, its publish date has
passed and it has not expired. Opening an article counts a view. Comments
and likes are in interactions.py.
"""
from __future__ import annotations

import math

from django.db.models import F, Q
from django.utils import timezone

from apps.adminapi.models import AdminUser
from apps.website import images as site_images
from apps.website.models import Article, ArticleComment, BlogCategory, Customer, MediaAttachment

from . import catalog
from .envelope import MSG_FETCHED_ONE, jalali, not_found, ok
from .views import PublicView

_to_int = lambda v, d: int(v) if str(v or "").lstrip("-").isdigit() else d  # noqa: E731


def visible():
    now = timezone.now()
    return (
        Article.objects.filter(is_deleted=False, show_on_page=True, publish_date__lte=now)
        .filter(Q(expiration_date__isnull=True) | Q(expiration_date__gte=now))
    )


def _media(url: str) -> str:
    return catalog.absolute_url(site_images.site_media_url(url)) if url else url


def _authors(articles) -> dict[int, str]:
    ids = {a.author_id for a in articles if a.author_id}
    return {u.id: f"{u.first_name} {u.last_name}".strip() for u in AdminUser.objects.filter(id__in=ids)}


def _summary(a: Article, authors: dict | None = None) -> dict:
    return {
        "id": a.id, "articleTitle": a.title, "articleDescription": a.description, "articleUniqUrl": a.uniq_url,
        "showOnPage": a.show_on_page, "articleThumbnail": _media(a.thumbnail), "viewCount": a.view_count,
        "authorId": a.author_id, "authorName": (authors or {}).get(a.author_id, ""),
        "publishDate": jalali(a.publish_date, with_time=False),
    }


class RecentView(PublicView):
    def get(self, request):
        limit = max(1, min(_to_int(request.query_params.get("limit"), 10), 50))
        articles = list(visible().order_by("-created", "-id")[:limit])
        authors = _authors(articles)
        return ok([_summary(a, authors) for a in articles])


class ByUniqUrlView(PublicView):
    def get(self, request):
        uniq = (request.query_params.get("uniqUrl") or "").strip().strip("/")
        a = visible().filter(uniq_url__iexact=uniq).first()
        if not a:
            return ok(None, message="اطلاعات مورد نظر یافت نشد.")
        Article.objects.filter(id=a.id).update(view_count=F("view_count") + 1)
        a.view_count += 1
        authors = _authors([a])
        data = {
            **_summary(a, authors),
            "articleContent": site_images.rewrite_media_in_text(a.content),
            "expirationDate": a.expiration_date.isoformat() if a.expiration_date else None,
            "likeCount": a.likes.filter(is_deleted=False, liked=True).count(),
            "isLike": None,
            "user": None,
            "tags": [{"id": t.id, "name": t.name} for t in a.tags.filter(is_deleted=False, article_links__is_deleted=False).distinct()],
            "articleCategories": [
                {"id": c.id, "name": c.title}
                for c in a.categories.filter(is_deleted=False, article_links__is_deleted=False).distinct()
            ],
            "mediaAttachments": [],
        }
        return ok(data, message=MSG_FETCHED_ONE)


class CategoriesView(PublicView):
    def get(self, request):
        cats = BlogCategory.objects.filter(is_deleted=False).order_by("id")
        return ok([{"id": c.id, "title": c.title} for c in cats])


class ByCategoryView(PublicView):
    def get(self, request):
        q = request.query_params
        qs = visible()
        if cat := _to_int(q.get("categoryId"), 0):
            qs = qs.filter(category_links__category_id=cat, category_links__is_deleted=False).distinct()
        rows = list(qs.order_by("-publish_date", "-id"))
        size, number = max(_to_int(q.get("pageSize"), 10), 1), max(_to_int(q.get("pageNumber"), 1), 1)
        page = rows[(number - 1) * size: number * size]
        authors = _authors(page)
        media: dict[int, list] = {}
        for att in MediaAttachment.objects.filter(table=MediaAttachment.Table.ARTICLES, record_id__in=[a.id for a in page], is_deleted=False):
            media.setdefault(att.record_id, []).append(catalog.media_dict(att))
        data = [{**_summary(a, authors), "mediaAttachments": media.get(a.id, [])} for a in page]
        return ok(data, total_pages=math.ceil(len(rows) / size))


class SuggestedView(PublicView):
    """Articles sharing a category or tag with the given one, then the newest; never the article itself."""

    def get(self, request):
        q = request.query_params
        limit = max(1, min(_to_int(q.get("limit"), 4), 20))
        current = Article.objects.filter(uniq_url__iexact=(q.get("uniqUrl") or "").strip().strip("/"), is_deleted=False).first()
        if not current:
            return not_found(message="Article not found.")
        cats = current.category_links.filter(is_deleted=False).values("category_id")
        tags = current.tag_links.filter(is_deleted=False).values("tag_id")
        others = visible().exclude(id=current.id)
        related = list(
            others.filter(
                Q(category_links__category_id__in=cats, category_links__is_deleted=False)
                | Q(tag_links__tag_id__in=tags, tag_links__is_deleted=False)
            ).distinct().order_by("-publish_date", "-id")[:limit]
        )
        if len(related) < limit:
            related += list(others.exclude(id__in=[a.id for a in related]).order_by("-publish_date", "-id")[: limit - len(related)])
        authors = _authors(related)
        return ok([_summary(a, authors) for a in related])


class CommentsView(PublicView):
    def get(self, request):
        uniq = (request.query_params.get("uniqUrl") or "").strip().strip("/")
        a = visible().filter(uniq_url__iexact=uniq).first()
        comments = list(a.comments.filter(is_deleted=False, status=1).order_by("-created", "-id")) if a else []
        if not comments:
            return ok([], message="کامنتی وجود ندارد.")
        customers = Customer.objects.in_bulk([c.commenter_id for c in comments if c.commenter_id])

        def name(c: ArticleComment) -> str:
            cu = customers.get(c.commenter_id)
            if c.is_anonymous or not cu:
                return "کاربر مهمان"
            return f"{cu.first_name} {cu.last_name}".strip() or "کاربر"

        return ok([
            {
                "id": c.id, "comment": c.comment, "title": c.title, "persianDate": jalali(c.created, with_time=False),
                "likeCount": 0, "dislikeCount": 0, "isAdminComment": c.is_admin_comment, "isActive": True,
                "commenterName": name(c),
            }
            for c in comments
        ])


def sitemap_items(item) -> list[dict]:
    return [item(a.uniq_url, a.last_modified or a.publish_date) for a in visible().order_by("-publish_date")]
