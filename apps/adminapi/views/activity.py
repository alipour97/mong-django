"""Admin-only views of the activity recorded by the storefront."""
from django.db.models import Count, Exists, F, Max, OuterRef, Q, Subquery, Value

from apps.storefront.journey import status_time
from apps.website.models import Invoice, StoreActivity, StoreVisitor

from ..envelope import fail, ok
from ..paging import one_page, to_int
from .auth import AdminView


def _page(request, rows, serialize):
    number = max(to_int(request.query_params.get("pageNumber"), 1), 1)
    size = 20
    total = rows.count()
    items = [serialize(row) for row in rows[(number - 1) * size:number * size]]
    return ok({"result": one_page(items, total, number, size)})


def _event(row):
    kind, detail = row["kind"], row["detail"]
    product_event = kind in (StoreActivity.Kind.PRODUCT_VIEW, StoreActivity.Kind.CART_ADD)
    label = detail if kind == StoreActivity.Kind.STATUS else dict(StoreActivity.Kind.choices).get(kind, detail)
    return {
        "id": f"{kind}:{row['id']}",
        "at": row["occurred_at"].isoformat(),
        "label": str(label),
        "detail": detail if product_event else "",
    }


EVENT_FIELDS = ("id", "kind", "detail", "occurred_at")


def _invoice_events(invoice):
    other = Invoice.objects.filter(customer_id=invoice.customer_id).exclude(pk=invoice.pk)
    previous = other.filter(created__lt=invoice.created).order_by("-created", "-id").first()
    following = other.filter(created__gt=invoice.created).order_by("created", "id").first()

    identified_browsers = StoreVisitor.objects.filter(customer_id=invoice.customer_id)
    related = StoreActivity.objects.filter(
        Q(customer_id=invoice.customer_id) | Q(
            customer__isnull=True,
            visitor_id__in=identified_browsers.values("id"),
            occurred_at__lte=F("visitor__identified_at"),
        ),
        invoice__isnull=True,
    )
    if previous:
        start = status_time(previous) or previous.created
        related = related.filter(occurred_at__gt=min(start, invoice.created))
    if following:
        related = related.filter(occurred_at__lt=following.created)
    if invoice.state != Invoice.State.PRE_INVOICE and (end := status_time(invoice)):
        related = related.filter(occurred_at__lte=end)

    events = StoreActivity.objects.filter(Q(invoice=invoice) | Q(pk__in=Subquery(related.values("pk"))))
    opened = Invoice.objects.filter(pk=invoice.pk).order_by().annotate(
        event_kind=Value("invoice_opened"), detail=Value("ایجاد سبد سفارش"), occurred_at=F("created"),
    ).values("id", "event_kind", "detail", "occurred_at")
    paid = Invoice.objects.filter(pk=invoice.pk, paid_at__isnull=False).order_by().annotate(
        event_kind=Value("invoice_paid"), detail=Value("تأیید پرداخت"), occurred_at=F("paid_at"),
    ).values("id", "event_kind", "detail", "occurred_at")
    return events.values(*EVENT_FIELDS).union(opened, paid, all=True).order_by("occurred_at", "id", "kind")


class InvoiceActivityView(AdminView):
    def get(self, request, invoice_id):
        invoice = Invoice.objects.filter(pk=invoice_id, is_deleted=False).first()
        if not invoice:
            return fail("فاکتور یافت نشد.", 404)
        return _page(request, _invoice_events(invoice), _event)


class GuestVisitorsView(AdminView):
    def get(self, request):
        views = StoreActivity.objects.filter(kind=StoreActivity.Kind.PRODUCT_VIEW, customer__isnull=True)
        visitors = StoreVisitor.objects.filter(identified_at__isnull=True).filter(Exists(views.filter(visitor_id=OuterRef("pk"))))
        if search := (request.query_params.get("product") or "").strip()[:100]:
            visitors = visitors.filter(Exists(views.filter(visitor_id=OuterRef("pk"), detail__icontains=search)))
        product_views = Q(activities__kind=StoreActivity.Kind.PRODUCT_VIEW, activities__customer__isnull=True)
        rows = visitors.annotate(
            view_count=Count("activities", filter=product_views),
            last_view_at=Max("activities__occurred_at", filter=product_views),
        ).order_by("-last_view_at", "-id")
        return _page(request, rows, lambda row: {
            "id": row.pk, "viewCount": row.view_count, "lastViewAt": row.last_view_at.isoformat(),
        })


class GuestActivityView(AdminView):
    def get(self, request, visitor_id):
        visitor = StoreVisitor.objects.filter(pk=visitor_id, identified_at__isnull=True).first()
        if not visitor:
            return fail("بازدیدکننده دیگر در فهرست مهمان‌ها نیست.", 404)
        events = visitor.activities.filter(customer__isnull=True, visitor__identified_at__isnull=True)
        return _page(request, events.values(*EVENT_FIELDS).order_by("occurred_at", "id"), _event)
