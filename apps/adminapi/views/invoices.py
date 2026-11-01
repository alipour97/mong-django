"""
Invoice/* — the invoices page: online orders in Samian.

An online order is a Samian sales receipt posted by a web store (it carries
storeorderid, a shipment type and delivery details); store sales are not
invoices here. Only its Mong rows are kept (a receipt can hold other brands'
items too), so amounts are the sums of those rows plus shipping; returned rows
count negative. The id is the receipt's Samian id and the invoice number its
code. Telling Mong's web orders from Lebaza's is still open (asked of Samian).

The panel's state comes from the order's web status: awaiting payment is a
pre-invoice (1), cancelled (or a voided/deleted receipt) is cancelled (4), and
paid, processing, ready, sent and delivered are successful (3). Online payment
rows come with the order phase. Editing and cancelling are offered for orders
paid with SnappPay (the panel asks the admin to confirm, as SnappPay requires:
both are final), and they go to SnappPay through apps.payhub.

Orders placed on the new site that have not reached Samian yet (website
Invoice without samian_transaction_id) are listed too, with their own id and
the invoice number given when paid; once sent, the Samian receipt takes their place. An id is
looked up among those site orders first.

    GET  Invoice/GetFilteredInvoices?FromAmount=&ToAmount=&FromDate=&ToDate=&InvoiceState=&HasDiscount=&HasComment=
         &SearchText=&ShippingMethodIds=&pageNumber=&pageSize=
    GET  Invoice/GetInvoiceStatistics?invoiceState= | Invoice/InvoiceAmountRange | Invoice/InvoiceDetails/<id>
    GET  Invoice/RecentInvoicesForCustomer?customerId=&pageNumber=&pageSize= | Invoice/GetCorruptedInvoices
    POST Invoice/UpdateInvoice/<id> | Invoice/CancelInvoice/<id> (SnappPay site orders)
    POST Invoice/ValidateCorruptedInvoices (refused)
"""
from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import BigIntegerField, Case, DecimalField, F, Max, Min, Q, Sum, Value, When
from django.db.models.functions import Abs, Coalesce
from django.utils import timezone

from apps.payhub import service as payhub
from apps.samian.models import SamianColor, SamianProduct, SamianSalesRow, SamianSalesTransaction
from apps.storefront.envelope import jalali
from apps.storefront.payments import SNAPPPAY, snapp_order
from apps.website.models import City, CompanyInfo, Customer, Invoice, Product, ProductComment, ProductSamianLink, Province

from ..envelope import fail, ok
from ..paging import sort_spec, to_bool, to_int
from .auth import AdminView
from .comments import _date
from .dashboard import _aware, month_range, today_j

# Samian onlinestore/orderwebstatus -> the panel's invoice state
AWAITING_PAYMENT, WEB_CANCELLED = 1, 5
VOIDED = (4, 5)  # retail/transactionstatus «ابطال شده», «حذف شده»
PRE_INVOICE, SUCCESSFUL, CANCELLED = 1, 3, 4


def _state(t) -> int:
    if t.status_id in VOIDED or t.order_web_status_id == WEB_CANCELLED:
        return CANCELLED
    return PRE_INVOICE if t.order_web_status_id == AWAITING_PAYMENT else SUCCESSFUL


def _in_state(qs, state: int):
    cancelled = Q(status_id__in=VOIDED) | Q(order_web_status_id=WEB_CANCELLED)
    if state == CANCELLED:
        return qs.filter(cancelled)
    if state == PRE_INVOICE:
        return qs.filter(order_web_status_id=AWAITING_PAYMENT).exclude(cancelled)
    if state == SUCCESSFUL:
        return qs.exclude(cancelled).exclude(order_web_status_id=AWAITING_PAYMENT)
    return qs.none()


NOT_YET = "ویرایش و لغو فاکتور همراه با ثبت سفارش‌های سایت در سامیان راه‌اندازی می‌شود."


def _signed(field: str, kind=BigIntegerField):
    """Sum of a row field over the receipt's Mong rows; returned rows count negative (Samian already stores them so)."""
    value = F(f"rows__{field}")
    total = Sum(Case(When(rows__is_return=True, then=-Abs(value)), default=value, output_field=kind()))
    return Coalesce(total, Value(0), output_field=kind())


def _invoices():
    """Online orders with at least one Mong row, with their Mong totals (rial)."""
    return (
        SamianSalesTransaction.objects.filter(rows__isnull=False, store_order_id__isnull=False)
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
        qs = _in_state(qs, state)
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
    if ids := [to_int(i) for i in q.getlist("ShippingMethodIds") if to_int(i) is not None]:
        qs = qs.filter(shipment_type_id__in=ids)  # site methods are to carry their Samian shipment type id
    if search := (q.get("SearchText") or "").strip():
        qs = qs.filter(
            Q(transaction_code__icontains=search) | Q(samian_id=to_int(search, -1))
            | Q(samian_customer__mobile__contains=search) | Q(samian_customer__first_name__icontains=search)
            | Q(samian_customer__last_name__icontains=search) | Q(samian_customer__display_name__icontains=search)
        | Q(store_order_id=to_int(search, -1)) | Q(delivery_tel__contains=search)
        )
    return qs


# -----------------------------------------------------------------------------
# Site orders not yet in Samian
# -----------------------------------------------------------------------------
def _site():
    return (Invoice.objects.filter(is_deleted=False, samian_transaction_id__isnull=True)
            .select_related("customer", "shipping_method__type", "address").prefetch_related("payments"))


def _snapp_payment(inv: Invoice):
    return next((p for p in inv.payments.all() if p.gateway == SNAPPPAY and p.is_success), None)


def _site_filter(qs, q):
    if (state := to_int(q.get("InvoiceState") or q.get("invoiceState"))) is not None:
        qs = qs.filter(state=state)
    if begin := _date(q.get("FromDate")):
        qs = qs.filter(created__gte=begin)
    if end := _date(q.get("ToDate"), end=True):
        qs = qs.filter(created__lte=end)
    if (low := to_int(q.get("FromAmount"))) is not None:
        qs = qs.filter(amount__gte=low)
    if (high := to_int(q.get("ToAmount"))) is not None:
        qs = qs.filter(amount__lte=high)
    if (discount := to_bool(q.get("HasDiscount"))) is not None:
        qs = qs.filter(reduction_amount__gt=0) if discount else qs.filter(reduction_amount__lte=0)
    if (commented := to_bool(q.get("HasComment"))) is not None:
        products = ProductComment.objects.filter(is_deleted=False, is_buyer=True, is_admin_comment=False).values("product_id")
        qs = qs.filter(lines__product_id__in=products).distinct() if commented else qs.exclude(lines__product_id__in=products)
    if ids := [to_int(i) for i in q.getlist("ShippingMethodIds") if to_int(i) is not None]:
        qs = qs.filter(shipping_method_id__in=ids)
    if search := (q.get("SearchText") or "").strip():
        qs = qs.filter(Q(id=to_int(search, -1)) | Q(number=search) | Q(customer__cellphone__contains=search)
                       | Q(customer__first_name__icontains=search) | Q(customer__last_name__icontains=search))
    return qs


SITE_NOTE = "سفارش سایت؛ هنوز به سامیان ارسال نشده"


def _site_header(inv: Invoice) -> dict:
    m, c = inv.shipping_method, inv.customer
    lines = list(inv.lines.all())
    after = inv.amount - inv.reduction_amount
    snapp = _snapp_payment(inv)
    return {
        "id": inv.id, "invoiceNumber": inv.number, "customerId": c.id, "customerName": c.first_name, "customerLastName": c.last_name,
        "qty": float(sum(ln.qty for ln in lines)), "createDate": inv.created.isoformat(),
        "createDatePersian": jalali(inv.created, with_time=False), "branchId": None, "branchTitle": None,
        "invoiceState": inv.state, "invoiceType": inv.state,
        "shippingMethodId": inv.shipping_method_id or 0, "shippingMethodName": m.name if m else "",
        "shippingMethodTypeId": m.type_id if m else 0, "shippingMethodTypeTitle": m.type.name if m and m.type else "",
        "deliveryAmount": inv.delivery_amount, "customerAddressId": inv.address_id or 0, "storeOrderId": inv.id,
        "amount": inv.amount, "amountAfterReduction": after, "reductionAmount": inv.reduction_amount,
        "totalReductionAmounts": inv.reduction_amount + inv.deduction_amount, "reduction": 0, "discount": inv.reduction_amount,
        "hasDiscount": inv.reduction_amount > 0, "deductionAmount": inv.deduction_amount, "deductionType": "None",
        "fixedAmount": 0, "variableAmount": 0, "insuranceFee": 0, "tax": 0, "taxAmount": 0, "vat": 0, "vatAmount": 0,
        "amountAfterVatAndTax": after, "payableAmount": inv.payable_amount, "totalAmountPayable": inv.payable_amount,
        "finalAmount": inv.payable_amount, "giftCardId": inv.gift_card_id, "couponId": inv.coupon_id,
        "erpInvoiceId": inv.erp_invoice_id, "erpError": inv.erp_error,
        "erpTakenAt": inv.erp_taken_at.isoformat() if inv.erp_taken_at else None,
        "description": "\n".join(x for x in (SITE_NOTE, inv.description) if x),
        "commentCounts": 0, "hasComment": False,
        "snappPayTransactionId": snapp.transaction_id if snapp else None, "snappPayToken": snapp.authority if snapp else None,
    }


def _site_detail(inv: Invoice) -> dict:
    header = _site_header(inv)
    c, a, info = inv.customer, inv.address, CompanyInfo.objects.filter(is_deleted=False).first()
    slugs = dict(Product.objects.filter(id__in=inv.lines.values("product_id")).values_list("id", "slug"))
    lines = []
    for ln in inv.lines.all():
        qty = float(ln.qty)
        lines.append({
            "id": ln.id, "variantFeatureValueId": ln.variant_id, "featureValueDependencyId": 0, "barcode": ln.barcode,
            "name": ln.name, "slug": slugs.get(ln.product_id), "price": ln.price, "reduction": float(ln.reduction),
            "discount": float(ln.reduction), "tax": 0, "vat": 0, "qty": qty, "reductionEffect": 1 - float(ln.reduction) / 100,
            "priceAfterReduction": ln.price_after_reduction, "reductionPrice": ln.price - ln.price_after_reduction,
            "vatDecimal": 0, "taxDecimal": 0, "vatPrice": 0, "taxPrice": 0, "priceAfterVatAndTax": ln.price_after_reduction,
            "totalPrice": round(ln.price * qty), "totalPriceAfterReduction": round(ln.price_after_reduction * qty),
            "totalReductionPrice": round((ln.price - ln.price_after_reduction) * qty), "totalTaxPrice": 0, "totalVatPrice": 0,
            "totalpriceAfterVatAndTax": round(ln.price_after_reduction * qty),
            "featureValues": [
                {"sortOrder": 0, "featureValueId": ln.color_id or 0, "featureValueName": ln.color_name or "-", "featureId": 1, "featureName": "رنگ"},
                {"sortOrder": 1, "featureValueId": 0, "featureValueName": ln.size_name or "-", "featureId": 2, "featureName": "سایز"},
            ],
            "description": None,
        })
    names = {"zarinpal": "زرین‌پال", "snapppay": "اسنپ‌پی"}
    payments = [
        {"id": p.id, "transactionId": p.reference or None, "bankId": 0, "traceNumber": p.authority or None,
         "fullName": f"{c.first_name} {c.last_name}".strip(), "authority": p.authority, "paymentAmount": p.amount,
         "isSuccess": p.is_success, "cellPhone": c.cellphone, "errorCode": None, "errorMessage": p.error_message or None,
         "bankName": names.get(p.gateway, p.gateway), "key": p.gateway}
        for p in inv.payments.all()
    ]
    return {
        "buyer": {"id": c.id, "firstName": c.first_name, "lastName": c.last_name, "mobile": c.cellphone},
        "seller": {"companyName": info.name if info else "", "address": info.address if info else "", "branchTitle": None},
        "address": {
            "id": a.id if a else 0, "customerId": c.id, "isDefault": bool(a and a.is_default), "title": a.title if a else "",
            "zipCode": (a.zip_code if a else "") or inv.postal_code,
            "firstName": (a.first_name if a else "") or (inv.recipient_name.split()[0] if inv.recipient_name else "") or c.first_name,
            "lastName": (a.last_name if a else "") or (inv.recipient_name.split(None, 1)[1] if len(inv.recipient_name.split()) > 1 else "") or c.last_name,
            "mobile": (a.mobile if a else "") or inv.recipient_mobile or c.cellphone,
            "isMyselfRecipient": a.is_myself_recipient if a else True, "provinceId": a.province_id if a else 0,
            "cityId": a.city_id if a else 0, "address": (a.address if a else "") or inv.full_address,
            "provinceTitle": (Province.objects.filter(id=a.province_id).values_list("name", flat=True).first() if a else "") or inv.province_name,
            "cityTitle": (City.objects.filter(id=a.city_id).values_list("name", flat=True).first() if a else "") or inv.city_name,
        },
        "invoiceHeader": header, "invoiceDetails": lines, "invoicePayments": payments,
    }


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
    payable = t.revenue + t.vat_amount + t.shipment_price
    state = _state(t)
    return {
        "id": t.samian_id, "invoiceNumber": t.transaction_code or str(t.samian_id),
        "customerId": cu.id if cu else 0, "customerName": first, "customerLastName": last,
        "qty": float(t.units), "createDate": t.transaction_date.isoformat() if t.transaction_date else None,
        "createDatePersian": jalali(t.transaction_date, with_time=False),
        "branchId": t.warehouse_id, "branchTitle": t.warehouse or None,
        "invoiceState": state, "invoiceType": state,
        "shippingMethodId": t.shipment_type_id or 0, "shippingMethodName": t.shipment_type,
        "shippingMethodTypeId": t.shipment_type_id or 0, "shippingMethodTypeTitle": t.shipment_type,
        "deliveryAmount": t.shipment_price, "customerAddressId": 0, "storeOrderId": t.store_order_id,
        "amount": t.amount, "amountAfterReduction": t.amount - t.reduction_amount, "reductionAmount": t.reduction_amount,
        "totalReductionAmounts": t.reduction_amount, "reduction": 0, "discount": t.reduction_amount,
        "hasDiscount": t.reduction_amount > 0, "deductionAmount": 0, "deductionType": "None",
        "fixedAmount": 0, "variableAmount": 0, "insuranceFee": 0,
        "tax": 0, "taxAmount": 0, "vat": 0, "vatAmount": t.vat_amount, "amountAfterVatAndTax": payable - t.shipment_price,
        "payableAmount": payable, "totalAmountPayable": payable, "finalAmount": payable,
        "giftCardId": None, "couponId": None, "description": t.order_web_status,
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


def _page(qs, q, site_qs=None) -> dict:
    """One page of Samian receipts and site orders together, newest first or by the column the panel sorts."""
    size, number = max(to_int(q.get("pageSize"), 10), 1), max(to_int(q.get("pageNumber"), 1), 1)
    site_qs = site_qs if site_qs is not None else Invoice.objects.none()
    total = qs.count() + site_qs.count()
    upto = number * size
    key, desc = sort_spec(q, ("qty", "payableAmount", "createDate"))
    key = key or "createDate"
    desc = desc if q.get("SortBy") else True
    oldest = timezone.make_aware(datetime.min.replace(year=2000))
    # Each side sorted in the database by the same value, then merged.
    if key == "qty":
        qs = qs.order_by(("-" if desc else "") + "units", "-samian_id")
        site_qs = site_qs.annotate(units=Coalesce(Sum("lines__qty"), Value(0), output_field=DecimalField())).order_by(("-" if desc else "") + "units", "-id")
        value = lambda obj: float(obj.units)  # noqa: E731
    elif key == "payableAmount":
        qs = qs.annotate(payable=F("revenue") + F("vat_amount") + F("shipment_price")).order_by(("-" if desc else "") + "payable", "-samian_id")
        site_qs = site_qs.order_by(("-" if desc else "") + "payable_amount", "-id")
        value = lambda obj: obj.payable if isinstance(obj, SamianSalesTransaction) else obj.payable_amount  # noqa: E731
    else:
        qs = qs.order_by(("-" if desc else "") + "transaction_date", "-samian_id")
        site_qs = site_qs.order_by(("-" if desc else "") + "created", "-id")
        value = lambda obj: (obj.transaction_date or oldest) if isinstance(obj, SamianSalesTransaction) else obj.created  # noqa: E731
    merged = sorted(list(qs[:upto]) + list(site_qs[:upto]), key=value, reverse=desc)[(number - 1) * size: upto]
    receipts = _headers([obj for obj in merged if isinstance(obj, SamianSalesTransaction)])
    by_id = {h["id"]: h for h in receipts}
    items = [by_id[obj.samian_id] if isinstance(obj, SamianSalesTransaction) else _site_header(obj) for obj in merged]
    return {"totalCount": total, "totalPages": math.ceil(total / size), "pageNumber": number, "pageSize": size, "items": items}


class ListView(AdminView):
    def get(self, request):
        q = request.query_params
        return ok({"result": _page(_filter(_invoices(), q), q, _site_filter(_site(), q))})


class CustomerInvoicesView(AdminView):
    def get(self, request):
        q = request.query_params
        customer = Customer.objects.filter(id=to_int(q.get("customerId")), is_deleted=False).first()
        if not customer:
            return fail("مشتری یافت نشد.", 404)
        qs = _invoices().filter(samian_customer_id=customer.samian_customer_id) if customer.samian_customer_id else _invoices().none()
        site = _site().filter(customer=customer)
        if to_int(q.get("couponId")) or to_int(q.get("giftCardId")):
            qs, site = qs.none(), site.none()  # coupons and gift cards are not linked yet
        return ok({"result": _page(qs, q, site)})


class StatisticsView(AdminView):
    def get(self, request):
        state = to_int(request.query_params.get("invoiceState"))
        qs, site = _invoices(), _site()
        if state is not None:
            qs, site = _in_state(qs, state), site.filter(state=state)
        jy, jm, _ = today_j()
        month = _aware(month_range(jy, jm)[0])
        with_comment = SamianSalesRow.objects.filter(samian_product_id__in=_commented_products()).values("transaction_id")
        commented = ProductComment.objects.filter(is_deleted=False, is_buyer=True, is_admin_comment=False).values("product_id")
        return ok({"result": {
            "totalCount": qs.count() + site.count(),
            "recentInvoicesCount": qs.filter(transaction_date__gte=month).count() + site.filter(created__gte=month).count(),
            "commentInvoicesCount": qs.filter(pk__in=with_comment).count() + site.filter(lines__product_id__in=commented).distinct().count(),
            "discountInvoicesCount": qs.filter(reduction_amount__gt=0).count() + site.filter(reduction_amount__gt=0).count(),
        }})


class AmountRangeView(AdminView):
    def get(self, request):
        r = _invoices().aggregate(low=Min("amount"), high=Max("amount"))
        s = _site().aggregate(low=Min("amount"), high=Max("amount"))
        lows, highs = [x for x in (r["low"], s["low"]) if x is not None], [x for x in (r["high"], s["high"]) if x is not None]
        return ok({"result": {"minAmount": min(lows) if lows else 0, "maxAmount": max(highs) if highs else 0}})


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
        if inv := _site().filter(id=invoice_id).first():
            return ok({"result": _site_detail(inv)})
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
                "id": 0, "customerId": header["customerId"], "isDefault": False, "title": t.delivery_desc,
                "zipCode": t.delivery_postal_code, "firstName": t.delivery_person or header["customerName"],
                "lastName": "" if t.delivery_person else header["customerLastName"],
                "mobile": t.delivery_tel or (sc.mobile if sc else ""), "isMyselfRecipient": not t.delivery_person,
                "provinceId": 0, "cityId": 0, **_address(t.delivery_address),
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


def _snapp_order(invoice_id: int) -> tuple[Invoice | None, object]:
    inv = _site().filter(id=invoice_id, state=SUCCESSFUL).first()
    return inv, _snapp_payment(inv) if inv else None


def _refused(message: str):
    return fail(message, 400, {"errorMessage": [message]})


class CancelView(AdminView):
    def post(self, request, invoice_id: int):
        inv, payment = _snapp_order(invoice_id)
        if not payment:
            return fail(NOT_YET, 400)
        done, message = payhub.cancel(payment.authority)
        if not done:
            return _refused(message)
        inv.state = CANCELLED
        inv.save(update_fields=["state", "last_modified"])
        return ok({"result": {"successful": True}})


class UpdateView(AdminView):
    """Lowers the quantities of a settled order; a row that goes to zero is removed from what SnappPay is sent."""

    def post(self, request, invoice_id: int):
        inv, payment = _snapp_order(invoice_id)
        if not payment:
            return fail(NOT_YET, 400)
        wanted = {to_int(r.get("id")): r.get("qty") for r in request.data.get("invoiceDetails") or [] if isinstance(r, dict)}
        lines = list(inv.lines.all())
        for ln in lines:
            qty = Decimal(str(wanted.get(ln.id) or 0))
            if qty < 0 or qty > ln.qty or qty != qty.to_integral_value():
                return _refused("تعداد ردیف‌ها فقط می‌تواند کم شود.")
            ln.qty = qty
        kept = [ln for ln in lines if ln.qty > 0]
        if not kept:
            return _refused("برای حذف همه‌ی ردیف‌ها، فاکتور را لغو کنید.")

        order = snapp_order(inv, kept)
        done, message = payhub.update(payment.authority, order)
        if not done:
            return _refused(message)
        with transaction.atomic():
            inv.lines.exclude(id__in=[ln.id for ln in kept]).delete()
            for ln in kept:
                ln.save(update_fields=["qty"])
            inv.amount = sum(int(ln.price * ln.qty) for ln in kept)
            inv.reduction_amount = inv.amount - sum(int(ln.price_after_reduction * ln.qty) for ln in kept)
            inv.payable_amount = order["amount"]
            inv.save(update_fields=["amount", "reduction_amount", "payable_amount", "last_modified"])
        return ok({"result": {"successful": True}})
