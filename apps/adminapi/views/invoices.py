"""
Invoice/* — the invoices page, read from Mong sales in Samian.

Like the dashboard, an invoice is a Samian sales receipt with Mong items, from
any branch. Only its Mong rows are kept (a receipt can hold other brands'
items too), so amounts are the sums of those rows; returned rows count
negative. The id is the receipt's Samian id and the invoice number its code.

Samian status 1 «تاييد شده» is the panel's "successful" (3) and 2 «معلق» its
"held" (2); there are no pre-invoices or cancelled ones, nor a shipping method
or online payment, until site orders are written to Samian. Editing and
cancelling come with that phase too (the panel only offers them for SnappPay
orders).

    GET  Invoice/GetFilteredInvoices?FromAmount=&ToAmount=&FromDate=&ToDate=&InvoiceState=&HasDiscount=&HasComment=
         &SearchText=&ShippingMethodIds=&pageNumber=&pageSize=
    GET  Invoice/GetInvoiceStatistics?invoiceState= | Invoice/InvoiceAmountRange | Invoice/InvoiceDetails/<id>
    GET  Invoice/RecentInvoicesForCustomer?customerId=&pageNumber=&pageSize= | Invoice/GetCorruptedInvoices
    POST Invoice/UpdateInvoice/<id> | Invoice/CancelInvoice/<id> | Invoice/ValidateCorruptedInvoices (refused)
"""
from __future__ import annotations

import math

from django.db.models import BigIntegerField, Case, DecimalField, F, Max, Min, Q, Sum, Value, When
from django.db.models.functions import Abs, Coalesce

from apps.samian.models import SamianColor, SamianProduct, SamianSalesRow, SamianSalesTransaction
from apps.storefront.envelope import jalali
from apps.website.models import CompanyInfo, Customer, Product, ProductComment, ProductSamianLink

from ..envelope import fail, ok
from ..paging import to_bool, to_int
from .auth import AdminView
from .comments import _date
from .dashboard import _aware, month_range, today_j

# Samian status -> the panel's invoice state
STATE_OF = {1: 3, 2: 2}
STATUS_OF = {v: k for k, v in STATE_OF.items()}
NOT_YET = "ویرایش و لغو فاکتور همراه با ثبت سفارش‌های سایت در سامیان راه‌اندازی می‌شود."


def _signed(field: str, kind=BigIntegerField):
    """Sum of a row field over the receipt's Mong rows; returned rows count negative (Samian already stores them so)."""
    value = F(f"rows__{field}")
    total = Sum(Case(When(rows__is_return=True, then=-Abs(value)), default=value, output_field=kind()))
    return Coalesce(total, Value(0), output_field=kind())


def _invoices():
    """Receipts with at least one Mong row, with their Mong totals (rial)."""
    return (
        SamianSalesTransaction.objects.filter(rows__isnull=False, status_id__in=STATE_OF)
        .annotate(
            amount=_signed("gross_amount"), reduction_amount=_signed("discount_amount"),
            vat_amount=_signed("vat_amount"), revenue=_signed("line_revenue"), units=_signed("quantity", DecimalField),
        )
        .select_related("samian_customer")
    )


def _commented_products() -> set[int]:
    """SamianProduct pks of site products that buyers commented on (as the old filter)."""
    products = ProductComment.objects.filter(is_deleted=False, is_buyer=True, is_admin_comment=False).values("product_id")
    samian_ids = ProductSamianLink.objects.filter(product_id__in=products).values("samian_product_id")
    return set(SamianProduct.objects.filter(samian_id__in=samian_ids).values_list("pk", flat=True))


def _filter(qs, q):
    if (state := to_int(q.get("InvoiceState") or q.get("invoiceState"))) is not None:
        qs = qs.filter(status_id=STATUS_OF.get(state, -1))
    if begin := _date(q.get("FromDate")):
        qs = qs.filter(transaction_date__gte=begin)
    if end := _date(q.get("ToDate"), end=True):
        qs = qs.filter(transaction_date__lte=end)
    if (low := to_int(q.get("FromAmount"))) is not None:
        qs = qs.filter(amount__gte=low)
    if (high := to_int(q.get("ToAmount"))) is not None:
        qs = qs.filter(amount__lte=high)
    if (discount := to_bool(q.get("HasDiscount"))) is not None:
        qs = qs.filter(reduction_amount__gt=0) if discount else qs.filter(reduction_amount__lte=0)
    if (commented := to_bool(q.get("HasComment"))) is not None:
        with_comment = SamianSalesRow.objects.filter(samian_product_id__in=_commented_products()).values("transaction_id")
        qs = qs.filter(pk__in=with_comment) if commented else qs.exclude(pk__in=with_comment)
    if [i for i in q.getlist("ShippingMethodIds") if i]:
        qs = qs.none()  # no Samian sale has a site shipping method yet
    if search := (q.get("SearchText") or "").strip():
        qs = qs.filter(
            Q(transaction_code__icontains=search) | Q(samian_id=to_int(search, -1))
            | Q(samian_customer__mobile__contains=search) | Q(samian_customer__first_name__icontains=search)
            | Q(samian_customer__last_name__icontains=search) | Q(samian_customer__display_name__icontains=search)
        )
    return qs


def _site_customers(txs) -> dict[int, Customer]:
    """SamianCustomer pk -> the site account linked to it."""
    ids = {t.samian_customer_id for t in txs if t.samian_customer_id}
    return {c.samian_customer_id: c for c in Customer.objects.filter(samian_customer_id__in=ids, is_deleted=False)}


def _header(t: SamianSalesTransaction, site: dict, commented_rows: dict) -> dict:
    sc, cu = t.samian_customer, site.get(t.samian_customer_id)
    first = (cu.first_name if cu else "") or (sc.first_name if sc else "")
    last = (cu.last_name if cu else "") or (sc.last_name if sc else "")
    if sc and not (first or last):
        first = sc.display_name
    payable = t.revenue + t.vat_amount
    return {
        "id": t.samian_id, "invoiceNumber": t.transaction_code or str(t.samian_id),
        "customerId": cu.id if cu else 0, "customerName": first, "customerLastName": last,
        "qty": float(t.units), "createDate": t.transaction_date.isoformat() if t.transaction_date else None,
        "createDatePersian": jalali(t.transaction_date, with_time=False),
        "branchId": t.warehouse_id, "branchTitle": t.warehouse or None,
        "invoiceState": STATE_OF[t.status_id], "invoiceType": STATE_OF[t.status_id],
        "shippingMethodId": 0, "shippingMethodName": "", "shippingMethodTypeId": 0, "shippingMethodTypeTitle": "",
        "deliveryAmount": 0, "customerAddressId": 0,
        "amount": t.amount, "amountAfterReduction": t.amount - t.reduction_amount, "reductionAmount": t.reduction_amount,
        "totalReductionAmounts": t.reduction_amount, "reduction": 0, "discount": t.reduction_amount,
        "hasDiscount": t.reduction_amount > 0, "deductionAmount": 0, "deductionType": "None",
        "fixedAmount": 0, "variableAmount": 0, "insuranceFee": 0,
        "tax": 0, "taxAmount": 0, "vat": 0, "vatAmount": t.vat_amount, "amountAfterVatAndTax": payable,
        "payableAmount": payable, "totalAmountPayable": payable, "finalAmount": payable,
        "giftCardId": None, "couponId": None, "description": "",
        "commentCounts": commented_rows.get(t.pk, 0), "hasComment": bool(commented_rows.get(t.pk)),
        "snappPayTransactionId": None, "snappPayToken": None,
    }


def _headers(txs: list) -> list[dict]:
    site = _site_customers(txs)
    commented = _commented_products()
    counts: dict[int, int] = {}
    for tid in SamianSalesRow.objects.filter(transaction_id__in=[t.pk for t in txs], samian_product_id__in=commented).values_list("transaction_id", flat=True):
        counts[tid] = counts.get(tid, 0) + 1
    return [_header(t, site, counts) for t in txs]


def _page(qs, q) -> dict:
    size, number = max(to_int(q.get("pageSize"), 10), 1), max(to_int(q.get("pageNumber"), 1), 1)
    total = qs.count()
    txs = list(qs.order_by("-transaction_date", "-samian_id")[(number - 1) * size: number * size])
    return {"totalCount": total, "totalPages": math.ceil(total / size), "pageNumber": number, "pageSize": size, "items": _headers(txs)}


class ListView(AdminView):
    def get(self, request):
        return ok({"result": _page(_filter(_invoices(), request.query_params), request.query_params)})


class CustomerInvoicesView(AdminView):
    def get(self, request):
        q = request.query_params
        customer = Customer.objects.filter(id=to_int(q.get("customerId")), is_deleted=False).first()
        if not customer:
            return fail("مشتری یافت نشد.", 404)
        qs = _invoices().filter(samian_customer_id=customer.samian_customer_id) if customer.samian_customer_id else _invoices().none()
        if to_int(q.get("couponId")) or to_int(q.get("giftCardId")):
            qs = qs.none()  # coupons and gift cards are not linked to Samian sales yet
        return ok({"result": _page(qs, q)})


class StatisticsView(AdminView):
    def get(self, request):
        state = to_int(request.query_params.get("invoiceState"))
        qs = _invoices()
        if state is not None:
            qs = qs.filter(status_id=STATUS_OF.get(state, -1))
        jy, jm, _ = today_j()
        with_comment = SamianSalesRow.objects.filter(samian_product_id__in=_commented_products()).values("transaction_id")
        return ok({"result": {
            "totalCount": qs.count(),
            "recentInvoicesCount": qs.filter(transaction_date__gte=_aware(month_range(jy, jm)[0])).count(),
            "commentInvoicesCount": qs.filter(pk__in=with_comment).count(),
            "discountInvoicesCount": qs.filter(reduction_amount__gt=0).count(),
        }})


class AmountRangeView(AdminView):
    def get(self, request):
        r = _invoices().aggregate(low=Min("amount"), high=Max("amount"))
        return ok({"result": {"minAmount": r["low"] or 0, "maxAmount": r["high"] or 0}})


def _address(text: str) -> dict:
    """Samian keeps the delivery address as "province-city-address"."""
    parts = (text or "").split("-", 2)
    province, city, rest = parts if len(parts) == 3 else ("", "", text or "")
    return {"provinceTitle": province.strip(), "cityTitle": city.strip(), "address": rest.strip()}


def _lines(t: SamianSalesTransaction) -> list[dict]:
    rows = list(t.rows.select_related("samian_barcode", "samian_product").order_by("samian_id"))
    colors = dict(SamianColor.objects.filter(
        samian_id__in={r.samian_barcode.colorinfo_id for r in rows if r.samian_barcode and r.samian_barcode.colorinfo_id}
    ).values_list("samian_id", "title"))
    product_of = dict(ProductSamianLink.objects.filter(
        samian_product_id__in={r.samian_product.samian_id for r in rows if r.samian_product}
    ).values_list("samian_product_id", "product_id"))
    slugs = dict(Product.objects.filter(id__in=product_of.values()).values_list("id", "slug"))
    out = []
    for r in rows:
        b = r.samian_barcode
        color = (colors.get(b.colorinfo_id) or b.color) if b else ""
        sign = -1 if r.is_return else 1
        qty, paid, vat = (sign * abs(v) for v in (float(r.quantity), r.line_revenue, r.vat_amount))
        price = abs(r.unit_price_before_discount)
        unit_paid = round(paid / qty) if qty else 0
        out.append({
            "id": r.samian_id, "variantFeatureValueId": r.barcodemain_id or 0, "featureValueDependencyId": 0,
            "barcode": r.barcode, "name": r.item_name + (" (مرجوعی)" if r.is_return else ""),
            "slug": slugs.get(product_of.get(r.samian_product.samian_id)) if r.samian_product else None,
            "price": price, "reduction": float(r.discount_percent), "discount": float(r.discount_percent),
            "tax": 0, "vat": 0, "qty": qty, "reductionEffect": 1 - float(r.discount_percent) / 100,
            "priceAfterReduction": unit_paid, "reductionPrice": price - unit_paid, "vatDecimal": 0, "taxDecimal": 0,
            "vatPrice": 0, "taxPrice": 0, "priceAfterVatAndTax": unit_paid,
            "totalPrice": round(price * qty), "totalPriceAfterReduction": paid, "totalReductionPrice": round(price * qty) - paid,
            "totalTaxPrice": 0, "totalVatPrice": vat, "totalpriceAfterVatAndTax": paid + vat,
            # The panel reads both entries unguarded: color, then size.
            "featureValues": [
                {"sortOrder": 0, "featureValueId": 0, "featureValueName": color or "-", "featureId": 1, "featureName": "رنگ"},
                {"sortOrder": 1, "featureValueId": 0, "featureValueName": (b.size if b else "") or "-", "featureId": 2, "featureName": "سایز"},
            ],
            "description": None,
        })
    return out


class DetailView(AdminView):
    def get(self, request, invoice_id: int):
        t = _invoices().filter(samian_id=invoice_id).first()
        if not t:
            return fail("فاکتور یافت نشد.", 404)
        header = _headers([t])[0]
        sc, info = t.samian_customer, CompanyInfo.objects.filter(is_deleted=False).first()
        return ok({"result": {
            "buyer": {"id": header["customerId"], "firstName": header["customerName"], "lastName": header["customerLastName"],
                      "mobile": sc.mobile if sc else ""},
            "seller": {"companyName": info.name if info else "", "address": info.address if info else "", "branchTitle": header["branchTitle"]},
            "address": {
                "id": 0, "customerId": header["customerId"], "isDefault": False, "title": "", "zipCode": "",
                "firstName": header["customerName"], "lastName": header["customerLastName"], "mobile": sc.mobile if sc else "",
                "isMyselfRecipient": True, "provinceId": 0, "cityId": 0, **_address(t.delivery_address),
            },
            "invoiceHeader": header,
            "invoiceDetails": _lines(t),
            "invoicePayments": [],
        }})


class CorruptedView(AdminView):
    """Site invoices that never reached the ERP; sales come from Samian now, so there are none."""

    def get(self, request):
        return ok({"result": {"totalCount": 0, "totalPages": 0, "pageNumber": 1, "pageSize": 10, "items": []}})


class NotYetView(AdminView):
    def post(self, request, invoice_id: int | None = None):
        return fail(NOT_YET, 400)
