"""
Dashboard/*, Report/*, Invoice/DailyCounts|InvoiceCountByHour, Products/TopSelling* — the admin home page.

"Invoices" here are successful online orders in Samian, as on the invoices page.
Best sellers count every confirmed Mong sale from every branch (Lebaza's too),
the same sales the site's best-seller sort uses.

    GET  Dashboard/Date | Dashboard/DashboardNotif | Dashboard/SynchronizationStatus | Dashboard/Search?query=
    POST Dashboard/SyncRun {job}    GET Dashboard/SyncRun?id=   (a sync job by hand, then its result)
    POST Dashboard/GrowthRate?month=&year=&steps=           (Persian month and year)
    GET  Report/GetDashboardLablesReports
    GET  Invoice/DailyCounts?months=8,7&years=1405,1405 | Invoice/InvoiceCountByHour
    GET  Products/TopSelling | Products/TopSellingGroupProduct
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.db.models import Q
from django.http import QueryDict
from django.utils import timezone

from apps.erp import jobs
from apps.erp.models import SyncRun
from apps.samian.models import SamianProduct, SamianSalesRow, SamianSalesTransaction, SamianSyncLog
from apps.storefront import catalog
from apps.storefront.envelope import _g2j, jalali
from apps.website.models import (
    Article, Category, Collection, Customer, FileFormat, FileMedia, Product, ProductComment, ProductSamianLink,
)

from .. import products as index
from ..envelope import fail, ok
from ..models import AdminUser
from ..paging import int_list, to_int
from .auth import AdminView

CONFIRMED = 1  # Samian transaction status «تاييد شده»; 2 «معلق» is a held, unfinished sale


# -----------------------------------------------------------------------------
# Persian calendar
# -----------------------------------------------------------------------------
def j2g(jy: int, jm: int, jd: int) -> date:
    """Gregorian date of a Persian date (searched around the estimate with _g2j)."""
    guess = date(jy + 621, 3, 21) + timedelta(days=(jm - 1) * 31 if jm <= 7 else 186 + (jm - 7) * 30) + timedelta(days=jd - 1)
    for delta in range(-3, 4):
        d = guess + timedelta(days=delta)
        if _g2j(d.year, d.month, d.day) == (jy, jm, jd):
            return d
    raise ValueError(f"invalid Persian date {jy}/{jm}/{jd}")


def month_range(jy: int, jm: int) -> tuple[date, date]:
    """[first day, first day of the next month) of a Persian month."""
    ny, nm = (jy + 1, 1) if jm == 12 else (jy, jm + 1)
    return j2g(jy, jm, 1), j2g(ny, nm, 1)


def today_j() -> tuple[int, int, int]:
    d = timezone.localdate()
    return _g2j(d.year, d.month, d.day)


def _aware(d: date) -> datetime:
    return timezone.make_aware(datetime.combine(d, time.min))


def _sales():
    """Invoices: successful online orders (the invoices page's state 3)."""
    from .invoices import SUCCESSFUL, _in_state
    return _in_state(SamianSalesTransaction.objects.filter(store_order_id__isnull=False), SUCCESSFUL)


def _in_month(qs, jy: int, jm: int):
    start, end = month_range(jy, jm)
    return qs.filter(transaction_date__gte=_aware(start), transaction_date__lt=_aware(end))


# -----------------------------------------------------------------------------
# Header and labels
# -----------------------------------------------------------------------------
class DateView(AdminView):
    """GET Dashboard/Date -> {"date"}: the server's local time; the panel's date pickers start from it."""

    def get(self, request):
        return ok({"date": timezone.localtime().replace(tzinfo=None).isoformat()})


class NotifView(AdminView):
    def get(self, request):
        today = timezone.localdate()
        start, end = _aware(today), _aware(today + timedelta(days=1))
        return ok({"result": {
            "articlesPublishedToday": Article.objects.filter(is_deleted=False, publish_date__gte=start, publish_date__lt=end).count(),
            "outOfStockProducts": sum(1 for r in index.admin_rows() if r.on_site and r.qty <= 0),
            "collectionCreatedTodayCount": Collection.objects.filter(is_deleted=False, end_date__gte=start, end_date__lt=end).count(),
        }})


class LabelsView(AdminView):
    def get(self, request):
        jy, jm, _ = today_j()
        month_start = _aware(month_range(jy, jm)[0])
        customers = Customer.objects.filter(is_deleted=False)
        return ok({"result": {
            "totalCustomers": customers.count(), "registeredThisMonth": customers.filter(created__gte=month_start).count(),
            "totalInvoices": _sales().count(), "invoicesThisMonth": _in_month(_sales(), jy, jm).count(),
        }})


class GrowthRateView(AdminView):
    """Average month-over-month growth of sales counts over `steps` months ending at the given one (percent)."""

    def post(self, request):
        q = request.query_params
        jy, jm, _ = today_j()
        year, month, steps = to_int(q.get("year"), jy), to_int(q.get("month"), jm), max(to_int(q.get("steps"), 1), 1)
        counts = []
        y, m = year, month
        for _ in range(steps + 1):
            counts.append(_in_month(_sales(), y, m).count())
            y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        counts.reverse()
        rates = [(b - a) * 100 / a for a, b in zip(counts, counts[1:]) if a]
        return ok({"result": {"averageGrowthRate": round(sum(rates) / len(rates), 2) if rates else 0}})

    get = post


# -----------------------------------------------------------------------------
# Charts
# -----------------------------------------------------------------------------
class DailyCountsView(AdminView):
    def get(self, request):
        months, years = int_list((request.query_params.get("months") or "").split(",")), int_list((request.query_params.get("years") or "").split(","))
        result = {}
        for y in dict.fromkeys(years):
            for m in dict.fromkeys(months):
                if not 1 <= m <= 12:
                    continue
                start, end = month_range(y, m)
                per_day = Counter(
                    timezone.localtime(t).date()
                    for t in _in_month(_sales(), y, m).values_list("transaction_date", flat=True)
                )
                result[f"{y}-{m}"] = [
                    {"day": i + 1, "count": per_day.get(start + timedelta(days=i), 0)} for i in range((end - start).days)
                ]
        return ok({"result": result})


PERIODS = (("صبح", "00:00 تا 12:00", 0, 12), ("ظهر", "12:00 تا 18:00", 12, 18), ("شب", "18:00 تا 23:59", 18, 24))


class CountByHourView(AdminView):
    """This Persian month's sales by time of day."""

    def get(self, request):
        jy, jm, _ = today_j()
        hours = [timezone.localtime(t).hour for t in _in_month(_sales(), jy, jm).values_list("transaction_date", flat=True)]
        return ok({"result": [
            {"period": name, "periodTime": label, "count": sum(1 for h in hours if lo <= h < hi)} for name, label, lo, hi in PERIODS
        ]})


def _sold_rows():
    """Confirmed Mong sales rows of the last BEST_SELLER_DAYS."""
    since = timezone.localdate() - timedelta(days=settings.BEST_SELLER_DAYS)
    return SamianSalesRow.objects.filter(report_date__gte=since, samian_product__isnull=False, transaction__status_id=CONFIRMED)


def _site_product_of() -> dict[int, int]:
    """SamianProduct pk -> site product id."""
    samian_pk = dict(SamianProduct.objects.values_list("samian_id", "pk"))
    return {samian_pk[sid]: pid for pid, sid in ProductSamianLink.objects.values_list("product_id", "samian_product_id") if sid in samian_pk}


def _net_sold() -> tuple[dict[int, float], dict[int, set]]:
    """site product id -> net units sold, and -> the transactions it was sold in."""
    product_of = _site_product_of()
    units: dict[int, float] = defaultdict(float)
    tx: dict[int, set] = defaultdict(set)
    for spk, is_return, qty, tid in _sold_rows().values_list("samian_product_id", "is_return", "quantity", "transaction_id"):
        pid = product_of.get(spk)
        if pid is None:
            continue
        units[pid] += -abs(float(qty)) if is_return else float(qty)  # returns are stored negative already
        if not is_return:
            tx[pid].add(tid)
    return units, tx


class TopSellingView(AdminView):
    """The single best-selling product (the dashboard card shows one), or null."""

    def get(self, request):
        units, _ = _net_sold()
        best = max(((pid, n) for pid, n in units.items() if n > 0), key=lambda kv: kv[1], default=None)
        if best is None:
            return ok({"result": None})
        pid, n = best
        bundle = catalog.ProductBundle.load([pid])
        title = Product.objects.filter(id=pid).values_list("title", flat=True).first() or ""
        return ok({"result": {
            "productId": pid, "title": title, "totalOrders": int(n), "mediaAttachments": bundle.main_images(pid),
        }})


class TopSellingGroupsView(AdminView):
    def get(self, request):
        units, tx = _net_sold()
        cat_of = dict(Product.objects.filter(id__in=units).values_list("id", "category_id"))
        stock: dict[int, float] = defaultdict(float)
        for r in index.admin_rows():
            stock[r.category_id] += r.qty
        sold: dict[int, float] = defaultdict(float)
        invoices: dict[int, set] = defaultdict(set)
        for pid, n in units.items():
            sold[cat_of.get(pid)] += n
            invoices[cat_of.get(pid)] |= tx[pid]
        cats = Category.objects.in_bulk([c for c in sold if c])
        parents = Category.objects.in_bulk({c.parent_id for c in cats.values() if c.parent_id})
        groups = sorted(
            (
                {
                    "categoryId": c.id, "categoryTitle": c.title, "parentCategoryId": c.parent_id,
                    "parentCategoryTitle": parents[c.parent_id].title if c.parent_id in parents else None,
                    "totalQty": int(sold[c.id]), "totalStockQty": int(stock.get(c.id, 0)), "showStatus": c.is_online_active,
                    "displayPriority": c.display_priority, "invoiceCount": len(invoices[c.id]),
                }
                for c in cats.values() if sold[c.id] > 0
            ),
            key=lambda g: -g["totalQty"],
        )
        total = len(set().union(*tx.values())) if tx else 0
        return ok({"result": {"productGroupSales": groups[:10], "totalOrder": total}})


# -----------------------------------------------------------------------------
# Sync status: the jobs in apps/erp/jobs.py, their last automatic run, and running one by hand
# -----------------------------------------------------------------------------
SYNC_STEPS = {  # Samian's own steps, shown too while the site runs on Samian: action -> (description, how often)
    SamianSyncLog.Action.SYNC_ALL: ("کالاها، قیمت و موجودی از سامیان", "00:15:00"),
    SamianSyncLog.Action.SYNC_SALES: ("فروش مانگ در همه‌ی شعب", "01:00:00"),
    SamianSyncLog.Action.SYNC_CUSTOMERS: ("مشتریان سایت در سامیان", "1.00:00:00"),
    SamianSyncLog.Action.SYNC_REFERENCE: ("برندها و انبارها", "1.00:00:00"),
    SamianSyncLog.Action.SYNC_PRODUCTS: ("کالاها", "1.00:00:00"),
    SamianSyncLog.Action.SYNC_PRICES_INVENTORY: ("قیمت و موجودی", "00:15:00"),
}


def sync_run(run) -> dict | None:
    if run is None:
        return None
    return {
        "id": run.id, "job": run.job, "trigger": run.trigger, "running": run.ok is None, "ok": run.ok,
        "startedAt": run.started_at.isoformat(), "startedAtText": jalali(run.started_at),
        "finishedAt": run.finished_at.isoformat() if run.finished_at else None,
        "seconds": jobs.seconds(run), "changes": run.changes, "error": run.error, "by": run.by,
    }


def _job_status(job) -> dict:
    auto = jobs.last(job.key, SyncRun.Trigger.AUTO)
    latest = jobs.last(job.key)
    late = auto is None or auto.started_at < timezone.now() - 2 * job.every - timedelta(minutes=5)
    done = bool(auto and auto.ok and not late)
    return {
        "operationKey": job.key, "operationName": job.title, "operationDescription": job.period,
        "status": "در حال اجرا" if latest and latest.ok is None else ("موفق" if done else "ناموفق یا عقب"),
        "percentage": 100 if done else 0, "totalItems": 0,
        "lastTransaction": (auto.finished_at or auto.started_at).isoformat() if auto else "",
        "periodStep": job.period, "operationDone": done,
        "canRun": True, "late": late, "lastAuto": sync_run(auto), "lastRun": sync_run(latest),
    }


def _samian_steps() -> list[dict]:
    items = []
    for action, (description, period) in SYNC_STEPS.items():
        log = SamianSyncLog.objects.filter(action=action).order_by("-started_at").first()
        if not log:
            continue
        done = log.status == SamianSyncLog.Status.SUCCESS
        items.append({
            "operationKey": action, "operationName": log.get_action_display(), "operationDescription": description,
            "status": log.get_status_display(), "percentage": 100 if done else 0, "totalItems": log.records_read,
            "lastTransaction": (log.finished_at or log.started_at).isoformat(), "periodStep": period, "operationDone": done,
            "canRun": False, "late": False, "lastAuto": None, "lastRun": None,
        })
    return items


def _average(items: list[dict]) -> int:
    return round(sum(i["percentage"] for i in items) / len(items)) if items else 100


class SyncStatusView(AdminView):
    def get(self, request):
        incoming = [_job_status(j) for j in jobs.JOBS.values() if j.direction == "in"]
        outgoing = [_job_status(j) for j in jobs.JOBS.values() if j.direction == "out"]
        if settings.ERP_CONNECTOR == "samian":
            incoming += _samian_steps()
        return ok({"result": {
            "totalIncomingPercentage": _average(incoming), "totalOutgoingPercentage": _average(outgoing),
            "incomingOperationDone": all(i["operationDone"] for i in incoming),
            "outgoingOperationDone": all(i["operationDone"] for i in outgoing),
            "incomingData": incoming, "outgoingData": outgoing,
        }})


class SyncRunView(AdminView):
    """POST {job}: runs a sync job now, in the background. GET ?id=: that run, to see when it is done."""

    def post(self, request):
        key = str(request.data.get("job") or "")
        if key not in jobs.JOBS:
            return fail("این همگام‌سازی وجود ندارد", 404)
        return ok({"result": sync_run(jobs.start(key, by=request.user.username))})

    def get(self, request):
        run = SyncRun.objects.filter(pk=to_int(request.query_params.get("id"))).first()
        if run is None:
            return fail("پیدا نشد", 404)
        return ok({"result": sync_run(run)})


# -----------------------------------------------------------------------------
# Header search
# -----------------------------------------------------------------------------
LIMIT = 20


class SearchView(AdminView):
    def get(self, request):
        text = (request.query_params.get("query") or "").strip()
        if not text:
            return ok({"result": {k: [] for k in (
                "customers", "invoices", "articles", "approvedComments", "pendingComments", "rejectedComments",
                "categories", "users", "fileMedias", "collections", "products", "outfits",
            )}})
        norm = catalog.norm(text)

        customers = Customer.objects.filter(is_deleted=False).filter(
            Q(first_name__icontains=text) | Q(last_name__icontains=text) | Q(cellphone__icontains=text) | Q(email__icontains=text)
        ).order_by("-id")[:LIMIT]
        comments = list(ProductComment.objects.filter(is_deleted=False).filter(
            Q(title__icontains=text) | Q(comment__icontains=text)).order_by("-id")[:3 * LIMIT])
        users = AdminUser.objects.filter(is_deleted=False).filter(
            Q(first_name__icontains=text) | Q(last_name__icontains=text) | Q(cellphone__icontains=text) | Q(username__icontains=text)
        ).select_related("role")[:LIMIT]
        rows = [r for r in index.admin_rows() if norm in r.title or norm in r.barcode][:LIMIT]
        tree = catalog.category_tree()
        files = [f for f in FileMedia.objects.filter(is_deleted=False).order_by("-id") if norm in catalog.norm(f"{f.file_name} {f.alternative}")][:LIMIT]

        def comment(c: ProductComment) -> dict:
            return {"id": c.id, "comment": c.comment, "score": float(c.score), "productId": c.product_id, "status": c.status,
                    "title": c.title, "typeId": 0, "type": "محصول", "createDate": jalali(c.created, with_time=False)}

        from .customers import _purchases
        from .gallery import _dto as _file_dto, _tags_of
        from .invoices import _filter as _invoice_filter, _headers as _invoice_headers, _invoices, _site, _site_filter, _site_header

        customers = list(customers)
        purchases = _purchases(customers)
        search = QueryDict(mutable=True)
        search["SearchText"] = text
        invoices = list(_invoice_filter(_invoices(), search).order_by("-transaction_date")[:LIMIT])
        site_invoices = list(_site_filter(_site(), search).order_by("-created")[:LIMIT])

        formats = {x.id: x for x in FileFormat.objects.filter(id__in={f.format_id for f in files})}
        file_tags = _tags_of([f.id for f in files])

        return ok({"result": {
            "customers": [
                {"customerId": c.id, "firstName": c.first_name, "lastName": c.last_name, "cellPhone": c.cellphone,
                 "registrationDate": jalali(c.created, with_time=False), "birthDate": jalali(c.birth_date, with_time=False),
                 "isActive": c.is_active, "invoiceCount": purchases.get(c.id, 0), "jobTitle": None}
                for c in customers
            ],
            "invoices": ([_site_header(inv) for inv in site_invoices] + _invoice_headers(invoices))[:LIMIT],
            "articles": [
                {"id": a.id, "title": a.title, "createDate": a.created.isoformat() if a.created else None,
                 "publishDate": jalali(a.publish_date, with_time=False),
                 "viewCount": a.view_count, "showOnPage": a.show_on_page, "authorName": "", "likeCount": 0, "commentCount": 0}
                for a in Article.objects.filter(is_deleted=False).filter(Q(title__icontains=text) | Q(description__icontains=text))[:LIMIT]
            ],
            "approvedComments": [comment(c) for c in comments if c.status == 1][:LIMIT],
            "pendingComments": [comment(c) for c in comments if c.status == 0][:LIMIT],
            "rejectedComments": [comment(c) for c in comments if c.status == 2][:LIMIT],
            "categories": [
                {"id": c.id, "title": c.title, "parentId": c.parent_id, "isOnlineActive": c.is_online_active}
                for c in tree.nodes.values() if norm in catalog.norm(c.title)
            ][:LIMIT],
            "users": [
                {"id": u.id, "firstName": u.first_name, "lastName": u.last_name, "sendInvoiceSms": u.send_invoice_sms,
                 "roleId": u.role_id, "roleTitle": u.role.title if u.role else None, "cellPhone": u.cellphone,
                 "userName": u.username, "email": u.email, "isActive": u.is_active}
                for u in users
            ],
            "fileMedias": [_file_dto(f, formats, file_tags) for f in files],
            "collections": [
                {"id": c.id, "title": c.title, "isActive": c.is_active, "inMainPage": c.in_main_page,
                 "beginningDate": jalali(c.beginning_date, with_time=False), "endDate": jalali(c.end_date, with_time=False)}
                for c in Collection.objects.filter(is_deleted=False, title__icontains=text)[:LIMIT]
            ],
            "products": [
                {"id": r.id, "name": r.name, "barcode": r.barcode, "price": r.price, "reduction": r.reduction,
                 "mediaCount": r.media_count, "qty": r.qty, "isSaleable": r.on_site,
                 "categoryName": tree.nodes[r.category_id].title if r.category_id in tree.nodes else "",
                 "parentCategoryName": "", "collectionName": "", "warehouses": [],
                 "hasLongDescription": r.has_long_description, "hasShortDescription": r.has_short_description}
                for r in rows
            ],
            "outfits": [],
        }})
