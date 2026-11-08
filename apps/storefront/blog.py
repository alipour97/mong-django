"""
Article/* on the site: the blog, as api.mong.ir served it.

An article is on the site while show_on_page is on, its publish date has
passed and it has not expired. The page counts a view with Article/View/<id>
(GetArticleByUniqUrl counts one too unless asked with count=0, which the
server-rendered page does). Comments and likes are in interactions.py.

The article's HTML is stored clean (website/article_html.py) and prepared here
for the page: heading ids and the table of contents, the FAQ, responsive photos,
and product cards with today's price in place of the product placeholders.
"""
from __future__ import annotations

import math
import re
from html import escape
from urllib.parse import unquote

from django.db.models import F, Q
from django.utils import timezone

from apps.adminapi.models import AdminUser
from apps.website import article_html
from apps.website import images as site_images
from apps.website.models import Article, ArticleComment, BlogCategory, Customer, MediaAttachment, Product, ProductVariant

from . import catalog
from rest_framework.response import Response

from .envelope import MSG_FETCHED_ONE, jalali, not_found, ok
from .views import PublicView, _product_by_slug

_to_int = lambda v, d: int(v) if str(v or "").lstrip("-").isdigit() else d  # noqa: E731


def visible():
    now = timezone.now()
    return (
        Article.objects.filter(is_deleted=False, show_on_page=True, publish_date__lte=now)
        .filter(Q(expiration_date__isnull=True) | Q(expiration_date__gte=now))
    )


def _media(url: str) -> str:
    return catalog.absolute_url(site_images.site_media_url(url)) if url else url


def _find_article(qs, uniq: str) -> Article | None:
    if not uniq:
        return None
    a = qs.filter(uniq_url__iexact=uniq).first()
    if a:
        return a
    import re
    if m := re.match(r"^(\d+)[A-Za-z]-(.+)$", uniq):
        art_id, slug = int(m.group(1)), m.group(2)
        a = qs.filter(Q(uniq_url__iexact=slug) | Q(id=art_id)).first()
        if a:
            return a
    elif uniq.isdigit():
        return qs.filter(id=int(uniq)).first()
    return None


def _authors(articles) -> dict[int, str]:
    ids = {a.author_id for a in articles if a.author_id}
    return {u.id: f"{u.first_name} {u.last_name}".strip() for u in AdminUser.objects.filter(id__in=ids)}


def author_profile(user: AdminUser | None) -> dict | None:
    """The person shown as a post's author, with their own page; None without a name."""
    if not user or not user.full_name:
        return None
    from apps.adminapi.views.auth import author_photo

    return {
        "id": user.id, "name": user.full_name, "jobTitle": user.job_title, "bio": user.bio,
        "photo": author_photo(user), "url": f"/blog/author/{user.id}",
    }


def author_person(profile: dict) -> dict:
    """schema.org Person for a post's author (E-E-A-T: a real writer with a page)."""
    person = {"type": "Person", "name": profile["name"], "url": profile["url"]}
    if profile["jobTitle"]:
        person["jobTitle"] = profile["jobTitle"]
    if profile["photo"]:
        person["image"] = profile["photo"]
    if profile["bio"]:
        person["description"] = _clip(profile["bio"], 300)
    person["worksFor"] = {"type": "Organization", "name": catalog.MONG_BRAND["title"], "url": "/"}
    return person


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


# -----------------------------------------------------------------------------
# Products in articles
# -----------------------------------------------------------------------------
_PRODUCT_PATH = re.compile(r"/(?:products-item/([^/?#]+)|p/(\d+))")
_BARCODE_MIN = 8  # product ids have up to 6 digits, barcodes 10 or more


def resolve_product(ref: str) -> Product | None:
    """A product named in an article: its address or short link, id, barcode, or exact name."""
    ref = (ref or "").strip()
    if not ref:
        return None
    qs = catalog.on_sale(Product.objects.filter(is_deleted=False))
    if m := _PRODUCT_PATH.search(ref):
        return qs.filter(pk=int(m.group(2))).first() if m.group(2) else _product_by_slug(unquote(m.group(1)))
    digits = ref.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
    if digits.isdigit():
        if len(digits) < _BARCODE_MIN:
            return qs.filter(pk=int(digits)).first()
        found = qs.filter(barcode=digits).first()
        if not found:
            variant = ProductVariant.objects.filter(barcode=digits, is_deleted=False).first()
            found = qs.filter(pk=variant.product_id).first() if variant else None
        return found
    found = _product_by_slug(ref)
    if found:
        return found
    key = catalog.norm(ref)
    return next((p for p in qs.only("id", "title").order_by("id") if catalog.norm(p.title) == key), None)


def _fa(n: int) -> str:
    return f"{int(n):,}".translate(str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹٬"))


CARD_IMAGE_WIDTHS = (384, 640)


def _card(bundle: catalog.ProductBundle, pid: int, single: bool) -> str:
    p = bundle.products[pid]
    pr = bundle.pricing(pid)
    ai = bundle.ai_profiles.get(pid)
    name = catalog.display_name(p.title)
    about = catalog.display_name(ai.title) if ai and ai.title else ""
    images = [i for i in bundle.main_images(pid) if not i["isVideo"]]
    if images:
        url = images[0]["mediaUrl"]
        srcset = ", ".join(f"{url}?w={w} {w}w" for w in CARD_IMAGE_WIDTHS)
        sizes = "(max-width: 640px) 40vw, 240px" if single else "(max-width: 640px) 50vw, 250px"
        img = (f'<img src="{escape(url)}?w=384" srcset="{escape(srcset)}" sizes="{sizes}" alt="{escape(about or name)}" '
               f'width="600" height="800" loading="lazy" decoding="async">')
    else:
        img = '<img src="/general-images/cart-place-holder.webp" alt="" width="600" height="800" loading="lazy">'
    in_stock = bundle.in_stock(pid)
    price = f'<span class="blog-product__now">{_fa(pr.after // 10)} <small>تومان</small></span>'
    if pr.after < pr.base:
        off = round(100 * (pr.base - pr.after) / pr.base) if pr.base else 0
        price = (f'<del>{_fa(pr.base // 10)}</del>{price}'
                 + (f'<span class="blog-product__off">٪{_fa(off)}</span>' if off else ""))
    if not in_stock:
        price = '<span class="blog-product__soldout">ناموجود</span>'
    return (
        f'<a class="blog-product" href="/products-item/{escape(p.slug)}">'
        f'<span class="blog-product__img">{img}</span>'
        f'<span class="blog-product__body">'
        f'<span class="blog-product__name">{escape(name)}</span>'
        + (f'<span class="blog-product__about">{escape(about)}</span>' if about and single else "")
        + f'<span class="blog-product__price">{price}</span>'
        f'<span class="blog-product__cta">{"مشاهده و خرید" if in_stock else "مشاهده محصول"}</span>'
        f'</span></a>'
    )


def render_products(refs: list[str], single: bool) -> str:
    ids: list[int] = []
    for ref in refs:
        p = resolve_product(ref)
        if p and p.id not in ids:
            ids.append(p.id)
    if not ids:
        return ""
    bundle = catalog.ProductBundle.load(ids)
    cards = [_card(bundle, pid, single) for pid in ids if pid in bundle.products]
    if not cards:
        return ""
    kind = "blog-products blog-products--single" if single and len(cards) == 1 else "blog-products"
    return f'<div class="{kind}">{"".join(cards)}</div>'


def prepared(a: Article) -> article_html.Prepared:
    return article_html.prepare(a.content, render_products)


def page_data(a: Article) -> dict:
    """The article as the page shows it (also the admin's preview)."""
    authors = _authors([a])
    body = prepared(a)
    return {
        **_summary(a, authors),
        "author": author_profile(AdminUser.objects.filter(id=a.author_id).first()) if a.author_id else None,
        "articleContent": body.html,
        "toc": body.toc,
        "faq": body.faq,
        "readingMinutes": max(1, round(body.words / 200)),
        "publishDateIso": a.publish_date.isoformat() if a.publish_date else None,
        "modifiedDateIso": (a.last_modified or a.publish_date).isoformat() if (a.last_modified or a.publish_date) else None,
        "expirationDate": a.expiration_date.isoformat() if a.expiration_date else None,
        "likeCount": a.likes.filter(is_deleted=False, liked=True).count(),
        "commentCount": a.comments.filter(is_deleted=False, status=1).count(),
        "isLike": None,
        "user": None,
        "tags": [{"id": t.id, "name": t.name} for t in a.tags.filter(is_deleted=False, article_links__is_deleted=False).distinct()],
        "articleCategories": [
            {"id": c.id, "name": c.title}
            for c in a.categories.filter(is_deleted=False, article_links__is_deleted=False).distinct()
        ],
        "mediaAttachments": [],
    }


class ByUniqUrlView(PublicView):
    def get(self, request):
        q = request.query_params
        a = _find_article(visible(), (q.get("uniqUrl") or "").strip().strip("/"))
        if not a:
            return ok(None, message="اطلاعات مورد نظر یافت نشد.")
        if q.get("count") != "0":
            Article.objects.filter(id=a.id).update(view_count=F("view_count") + 1)
            a.view_count += 1
        return ok(page_data(a), message=MSG_FETCHED_ONE)


class ViewCountView(PublicView):
    """POST Article/View/<id>: the page counts its view from the browser, so cached pages still count."""

    def post(self, request, article_id: int):
        n = visible().filter(id=article_id).update(view_count=F("view_count") + 1)
        return ok(bool(n))


class CategoriesView(PublicView):
    def get(self, request):
        cats = BlogCategory.objects.filter(is_deleted=False).order_by("id")
        return ok([{"id": c.id, "title": c.title} for c in cats])


class ListMetaView(PublicView):
    """GET Article/ListMeta?categoryId=: the blog page's heading and search snippet."""

    def get(self, request):
        cat = BlogCategory.objects.filter(id=_to_int(request.query_params.get("categoryId"), 0), is_deleted=False).first()
        if cat:
            return ok({
                "heading": f"مقالات {cat.title}",
                "intro": "",
                # The site appends " | مانگ" to every title.
                "seoTitle": _clip(f"مقالات {cat.title} در بلاگ", SEO_TITLE_MAX),
                "description": _clip(f"مقاله‌های {cat.title} در بلاگ مانگ: راهنمای استایل، ست کردن لباس و نکته‌های خرید لباس زنانه.",
                                     SEO_DESCRIPTION_MAX),
            })
        return ok({
            "heading": "بلاگ مانگ",
            "intro": "راهنمای استایل، ست کردن لباس و نکته‌های خرید مانتو، شلوار و لباس زنانه",
            "seoTitle": "بلاگ: راهنمای استایل و خرید لباس زنانه",
            "description": "راهنمای استایل، ست کردن لباس، انتخاب سایز و نکته‌های خرید مانتو، شلوار و لباس زنانه در بلاگ مانگ.",
        })


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
        current = _find_article(Article.objects.filter(is_deleted=False), (q.get("uniqUrl") or "").strip().strip("/"))
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
        a = _find_article(visible(), uniq)
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
    articles = list(visible().order_by("-publish_date"))
    items = [item(a.uniq_url, a.last_modified or a.publish_date) for a in articles]
    latest: dict[int, object] = {}
    for a in articles:  # newest first: the first one seen is the author's latest
        if a.author_id and a.author_id not in latest:
            latest[a.author_id] = a.last_modified or a.publish_date
    shown = AdminUser.objects.filter(id__in=latest, is_deleted=False).exclude(first_name="", last_name="")
    items += [item(f"author/{u.id}", latest[u.id]) for u in shown if u.full_name]
    return items


class AuthorView(PublicView):
    """Article/Author/<id>: a blog author's page, their bio and their posts. 404 without a visible post."""

    def get(self, request, author_id: int):
        user = AdminUser.objects.filter(id=author_id, is_deleted=False).first()
        profile = author_profile(user)
        articles = list(visible().filter(author_id=author_id).order_by("-publish_date")) if profile else []
        if not articles:
            return Response(None, status=404)
        authors = {user.id: profile["name"]}
        return ok({
            **profile,
            "seoTitle": _clip(f"{profile['name']}، نویسنده‌ی بلاگ مانگ", SEO_TITLE_MAX),
            "description": _clip(profile["bio"] or f"مقاله‌های {profile['name']} در بلاگ مانگ", SEO_DESCRIPTION_MAX),
            "person": {"context": "https://schema.org", **author_person(profile)},
            "articles": [_summary(a, authors) for a in articles],
        })


# -----------------------------------------------------------------------------
# SearchEngine/blog/<slug>/meta and /breadcrumbs
# -----------------------------------------------------------------------------
SEO_TITLE_MAX = 60
SEO_DESCRIPTION_MAX = 160


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ،,.-|:؛")


def find_visible(slug: str) -> Article | None:
    return _find_article(visible(), unquote(slug or "").strip().strip("/"))


def seo_meta(a: Article) -> dict:
    """BlogPosting JSON-LD; seoTitle and canonical are for the page's metadata only."""
    url = f"/blog/{a.uniq_url}"
    tags = [t.name for t in a.tags.filter(is_deleted=False, article_links__is_deleted=False).distinct()]
    category = a.categories.filter(is_deleted=False, article_links__is_deleted=False).first()
    modified = a.last_modified or a.publish_date
    profile = author_profile(AdminUser.objects.filter(id=a.author_id).first()) if a.author_id else None
    return {
        "context": "https://schema.org",
        "type": "BlogPosting",
        "headline": _clip(a.title, 110),
        "seoTitle": _clip(a.title, SEO_TITLE_MAX),
        "description": _clip(a.description or article_html.plain_text(a.content), SEO_DESCRIPTION_MAX),
        "canonical": url,
        "url": url,
        "image": _media(a.thumbnail) or None,
        "datePublished": a.publish_date.isoformat() if a.publish_date else None,
        "dateModified": modified.isoformat() if modified else None,
        "author": author_person(profile) if profile else {"type": "Organization", "name": catalog.MONG_BRAND["title"], "url": "/"},
        "publisher": {"type": "Organization", "name": catalog.MONG_BRAND["title"], "url": "/"},
        "inLanguage": "fa-IR",
        "keywords": ", ".join(tags),
        "articleSection": category.title if category else None,
        "wordCount": len(article_html.plain_text(a.content).split()),
    }


def breadcrumbs(a: Article | None) -> list[dict]:
    # Google reads a crumb's address from "item"; "url" is what the page's own breadcrumb uses.
    items = [{"position": 1, "name": "خانه", "url": "/", "item": "/"}, {"position": 2, "name": "بلاگ", "url": "/blog", "item": "/blog"}]
    if a:
        url = f"/blog/{a.uniq_url}"
        items.append({"position": 3, "name": a.title, "url": url, "item": url})
    return items
