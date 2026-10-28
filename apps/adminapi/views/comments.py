"""
ProductComment/* — reviewing product comments, as the old ProductComment controller.

Statuses: 0 pending, 1 approved, 2 rejected, 3 viewed. The site shows approved
comments only (is_active follows the status).

type 0 is a product comment, type 1 an article comment; the lists show both.

    GET  ProductComment/RecentComments?count=          pending ones, newest first
    GET  ProductComment/GetFilteredComments?status=&FromDate=&ToDate=&FromChngStatusDate=&ToChngStatusDate=&SearchText=&pageNumber=&pageSize=
    GET  ProductComment/GetCommentStatusCounts
    GET  ProductComment/GetCommentDetailWithMedia/<id>?type=0
    POST ProductComment/UpdateStatus/<id>?type=0&status=&CommentDes=
"""
from __future__ import annotations

from collections import Counter

from django.db.models import Count, Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from apps.samian.models import SamianSalesTransaction
from apps.storefront import catalog
from apps.storefront.envelope import jalali
from apps.website.models import ArticleComment, Customer, ProductComment

from ..envelope import fail, ok
from ..models import AdminUser
from ..paging import paginated, sort_rows, to_int
from .auth import AdminView
from .gallery import _url

PENDING, APPROVED, REJECTED, VIEWED = 0, 1, 2, 3
STATUS_TITLES = {PENDING: "در انتظار تایید", APPROVED: "تایید شده", REJECTED: "رد شده", VIEWED: "مشاهده شده"}
NOT_FOUND = "نظر یافت نشد"


def _date(value, end: bool = False):
    """A date filter from the panel (ISO date or datetime); a bare end date covers the whole day."""
    if not value:
        return None
    dt = parse_datetime(str(value))
    if dt is None:
        d = parse_date(str(value)[:10])
        if d is None:
            return None
        dt = timezone.datetime.combine(d, timezone.datetime.max.time() if end else timezone.datetime.min.time())
    return timezone.make_aware(dt) if timezone.is_naive(dt) else dt


def _status_dates(c: ProductComment) -> dict:
    changed = jalali(c.last_modified, with_time=False)
    return {
        "rejectedDate": changed if c.status == REJECTED else None,
        "confirmedDate": changed if c.status == APPROVED else None,
        "viewedDate": changed if c.status == VIEWED else None,
    }


def _admin_names(ids) -> dict[int, str]:
    return {u.id: f"{u.first_name} {u.last_name}".strip() for u in AdminUser.objects.filter(id__in=[i for i in ids if i])}


class RecentView(AdminView):
    def get(self, request):
        count = min(max(to_int(request.query_params.get("count"), 20), 1), 100)
        comments = list(
            ProductComment.objects.filter(is_deleted=False, status=PENDING).select_related("product").order_by("-created", "-id")[:count]
        )
        customers = Customer.objects.in_bulk([c.commenter_id for c in comments if c.commenter_id])
        purchases = dict(
            SamianSalesTransaction.objects.filter(samian_customer_id__in=[x.samian_customer_id for x in customers.values() if x.samian_customer_id])
            .values_list("samian_customer_id").annotate(n=Count("pk"))
        )
        items = []
        for c in comments:
            cu = customers.get(c.commenter_id)
            item = {
                "commentId": c.id, "comment": c.comment, "score": float(c.score), "productId": c.product_id,
                "productTitle": c.product.title, "userId": None, "firstName": None, "lastName": None, "cellPhone": None,
                "registrationDate": jalali(c.created, with_time=False), "isActive": False, "invoiceCount": 0,
            }
            if cu:
                item.update({
                    "userId": cu.id, "firstName": cu.first_name, "lastName": cu.last_name, "cellPhone": cu.cellphone,
                    "registrationDate": jalali(cu.created, with_time=False), "isActive": cu.is_active,
                    "invoiceCount": purchases.get(cu.samian_customer_id, 0),
                })
            items.append(item)
        return ok({"result": items})


MODELS = {0: ProductComment, 1: ArticleComment}


def _model(request):
    return MODELS.get(to_int(request.query_params.get("type"), 0))


class FilteredView(AdminView):
    def get(self, request):
        q = request.query_params
        status = to_int(q.get("status") if q.get("status") not in (None, "") else q.get("Status"))
        bounds = {
            "created__gte": _date(q.get("FromDate")), "created__lte": _date(q.get("ToDate"), end=True),
            "last_modified__gte": _date(q.get("FromChngStatusDate")),
            "last_modified__lte": _date(q.get("ToChngStatusDate"), end=True),
        }
        search = (q.get("SearchText") or "").strip()
        comments = []
        for model in MODELS.values():
            qs = model.objects.filter(is_deleted=False, **{k: v for k, v in bounds.items() if v})
            if status is not None:
                qs = qs.filter(status=status)
            if search:
                qs = qs.filter(Q(title__icontains=search) | Q(comment__icontains=search))
            comments += list(qs)
        comments.sort(key=lambda c: (c.created or timezone.now(), c.id), reverse=True)
        comments = sort_rows(comments, q, {
            "score": lambda c: float(c.score or 0), "createDate": lambda c: c.created,
            "confirmedDate": lambda c: c.last_modified if c.status == APPROVED else None,
            "rejectedDate": lambda c: c.last_modified if c.status == REJECTED else None,
        })
        customers = Customer.objects.in_bulk([c.commenter_id for c in comments if c.commenter_id])
        admins = _admin_names({c.verified_by_user_id for c in comments})

        def item(c) -> dict:
            cu = customers.get(c.commenter_id)
            article = isinstance(c, ArticleComment)
            return {
                "id": c.id, "comment": c.comment, "score": float(c.score), "commenterId": c.commenter_id,
                "isBuyer": c.is_buyer, "productId": None if article else c.product_id,
                "invoiceId": None if article else c.invoice_id, "articleCommentId": c.article_id if article else None,
                "type": "مقاله" if article else ("فاکتور" if c.invoice_id else "محصول"), "typeId": 1 if article else 0,
                "status": c.status, "title": c.title,
                "createDate": jalali(c.created, with_time=False), **_status_dates(c),
                "firstName": cu.first_name if cu else None, "lastName": cu.last_name if cu else None,
                "customerId": cu.id if cu else None, "viewedBy": admins.get(c.verified_by_user_id, ""),
            }

        page = paginated(comments, to_int(q.get("pageNumber"), 1), to_int(q.get("pageSize"), 20), item)
        return ok({"result": page})


class StatusCountsView(AdminView):
    def get(self, request):
        counts = Counter()
        for model in MODELS.values():
            counts.update(dict(model.objects.filter(is_deleted=False).values_list("status").annotate(n=Count("id"))))
        return ok({"result": {title: counts.get(s, 0) for s, title in STATUS_TITLES.items()}})


class DetailView(AdminView):
    def get(self, request, comment_id: int):
        model = _model(request)
        if model is ArticleComment:
            return self._article(comment_id)
        if model is None:
            return fail(NOT_FOUND, 404)
        c = ProductComment.objects.filter(id=comment_id, is_deleted=False).select_related("product").first()
        if not c:
            return fail(NOT_FOUND, 404)
        # The commented color was a Dadehfa color; the product's first Samian photo stands in for it.
        bundle = catalog.ProductBundle.load([c.product_id])
        images = bundle.main_images(c.product_id)
        verifier = _admin_names([c.verified_by_user_id]).get(c.verified_by_user_id)
        return ok({"result": {
            "title": c.title, "comment": c.comment, "score": float(c.score),
            "imageUrl": images[0]["mediaUrl"] if images else None, "barcode": c.product.barcode,
            "productTitle": c.product.title, "commenterId": c.commenter_id, "isBuyer": c.is_buyer,
            "verifiedByUser": verifier, **_status_dates(c),
            "commentStatusDescription": c.status_description, "invoiceId": c.invoice_id,
        }})


    def _article(self, comment_id: int):
        c = ArticleComment.objects.filter(id=comment_id, is_deleted=False).select_related("article").first()
        if not c:
            return fail(NOT_FOUND, 404)
        return ok({"result": {
            "title": c.title, "comment": c.comment, "score": float(c.score),
            "imageUrl": _url(c.article.thumbnail) if c.article.thumbnail else None, "barcode": None,
            "productTitle": c.article.title, "commenterId": c.commenter_id, "isBuyer": c.is_buyer,
            "verifiedByUser": _admin_names([c.verified_by_user_id]).get(c.verified_by_user_id), **_status_dates(c),
            "commentStatusDescription": c.status_description, "invoiceId": None,
        }})


class UpdateStatusView(AdminView):
    def post(self, request, comment_id: int):
        q = request.query_params
        status = to_int(q.get("status"))
        if status not in STATUS_TITLES:
            return fail("وضعیت نامعتبر است", 400)
        model = _model(request)
        if model is None:
            return ok({"result": False})
        c = model.objects.filter(id=comment_id, is_deleted=False).first()
        if not c:
            return ok({"result": False})
        c.status = status
        c.is_active = status == APPROVED
        c.verified_by_user_id = request.user.id
        c.status_description = q.get("CommentDes") or ""
        c.last_modified = timezone.now()
        c.save(update_fields=["status", "is_active", "verified_by_user_id", "status_description", "last_modified"])
        catalog.clear_caches()  # listing scores count approved comments
        return ok({"result": True})
