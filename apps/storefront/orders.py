"""
Cart, pre-invoice and the customer's orders (Invoice/*, ShipingMethod/*), as api.mong.ir.

The cart lives in the browser. At checkout the site posts it to Invoice/Add,
which (re)builds the customer's one pre-invoice: each line is a Samian barcode
(productVariantId), priced from Samian and capped at the stock of the online
branches less the safety stock. Lines that are gone or short come back in
failedItems ({productVariantId: message}); a short line is kept at the stock
left. Delivery costs the method's fixed cost when its type includes costs.

Any failed line makes the whole request answer 409 with failedItems (the
pre-invoice is still saved with what is left), so the site always tells the
customer and drops those lines before paying. A pre-invoice gets its invoice
number when it is created (see assign_number).

The Invoice/* endpoints answer HTTP 200 with the status in statusCode, as the
old InvoiceController did: the site reads 403/409/404 there (with no
pre-invoice, statusCode 404 makes it push the guest cart to the server).

Gift cards and coupons are refused until their Samian side is settled.

    POST Invoice/Add {productVariants: [{productVariantId, qty, name}], ShippingMethodId, description, gcNum?, serial?}
         -> {id, payableAmount, shippingMethodId, failedItems}
    GET  Invoice/GetLastPreInvoice | Invoice/SoftDelete/<id> | Invoice/GetAllCustomerInvoice?invoiceType=
    GET  Invoice/GetCustomerInvoiceById/<id>      POST Invoice/ClearCart
    POST ShipingMethod/GetAllShipingMethod [{productVariantId, qty, name}]
"""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.samian.models import SamianBarcode, SamianInventory
from apps.website.models import (
    City, CustomerAddress, Invoice, InvoiceLine, ProductSamianLink, Province, ShippingMethod, online_warehouse_ids,
)

from . import catalog
from .account import CustomerView, answer
from .envelope import MSG_FETCHED, _g2j, envelope, jalali

S = Invoice.State


def reply(data=None, status: int = 200, message: str | None = None):
    """Invoice/* style: always HTTP 200, the outcome in statusCode."""
    return envelope(data, status_code=status, message=message or MSG_FETCHED, http_status=200)
NOT_YET = "استفاده از کارت هدیه و کوپن به‌زودی فعال می‌شود."


FIRST_IN_MONTH = 101


def number_prefix(at) -> str:
    """Persian year without the thousands digit and the month: 1405/08 -> "40508"."""
    local = timezone.localtime(at)
    jy, jm, _ = _g2j(local.year, local.month, local.day)
    return f"{jy % 1000:03d}{jm:02d}"


def assign_number(inv: Invoice) -> str:
    """Gives the invoice the next number of its month (prefix + sequence from 101). Call inside a transaction."""
    if inv.number:
        return inv.number
    prefix = number_prefix(inv.created or timezone.now())
    # Lock the month's invoices so two payments at once cannot take the same number.
    taken = list(Invoice.objects.select_for_update().filter(number__startswith=prefix).values_list("number", flat=True))
    seqs = [int(n[len(prefix):]) for n in taken if n[len(prefix):].isdigit()]
    inv.number = f"{prefix}{max(seqs + [FIRST_IN_MONTH - 1]) + 1}"
    inv.save(update_fields=["number"])
    return inv.number


def _int(value) -> int | None:
    return int(value) if str(value if value is not None else "").lstrip("-").isdigit() else None


def _cart(raw) -> list[tuple[int, Decimal, str]]:
    """[(productVariantId, qty, name)] with repeated variants merged."""
    merged: dict[int, list] = {}
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        vid, qty = _int(item.get("productVariantId")), item.get("qty")
        try:
            qty = Decimal(str(qty))
        except Exception:
            continue
        if vid is None or qty <= 0:
            continue
        line = merged.setdefault(vid, [Decimal(0), str(item.get("name") or "")])
        line[0] += qty
    return [(vid, q, name) for vid, (q, name) in merged.items()]


def _bundle_for(variant_ids) -> tuple[catalog.ProductBundle, dict[int, tuple[int, catalog.Variant]]]:
    """The products of the given Samian barcodes, and barcode id -> (site product id, variant)."""
    sp_of = dict(SamianBarcode.objects.filter(samian_id__in=variant_ids).values_list("samian_id", "samian_product__samian_id"))
    pid_of_sp = dict(ProductSamianLink.objects.filter(samian_product_id__in=set(sp_of.values())).values_list("samian_product_id", "product_id"))
    bundle = catalog.ProductBundle.load(set(pid_of_sp.values()))
    found = {}
    for pid in bundle.products:
        for v in bundle.visible_variants(pid):
            if v.id in sp_of:
                found[v.id] = (pid, v)
    return bundle, found


# -----------------------------------------------------------------------------
# Shipping
# -----------------------------------------------------------------------------
def delivery_cost(method: ShippingMethod | None) -> int:
    return int(method.fixed_cost) if method and method.type and method.type.include_costs else 0


def _single_warehouse(cart) -> bool:
    """Whether one online branch has every cart line in stock (needed by methods that depend on the source)."""
    if not cart:
        return True
    pks = dict(SamianBarcode.objects.filter(samian_id__in=[v for v, _, _ in cart]).values_list("samian_id", "pk"))
    stock: dict[int, dict[int, float]] = {}
    for bpk, wh, qty in (
        SamianInventory.objects.filter(samian_barcode_id__in=pks.values(), warehouse_id__in=online_warehouse_ids())
        .values("samian_barcode_id", "warehouse_id").annotate(q=Sum("qty")).values_list("samian_barcode_id", "warehouse_id", "q")
    ):
        stock.setdefault(wh, {})[bpk] = float(qty or 0)
    return any(all(per_wh.get(pks.get(v), 0) >= float(q) for v, q, _ in cart) for per_wh in stock.values())


def shipping_dict(m: ShippingMethod) -> dict:
    return {
        "id": m.id, "name": m.name, "fixedCost": float(m.fixed_cost), "insuranceCost": float(m.insurance_cost),
        "taxAmount": float(m.tax_amount), "variableFee": float(m.variable_fee), "description": m.description,
        "icon": catalog.absolute_url(catalog.site_images.site_media_url(m.icon)) if m.icon else "",
        "requiresInsurance": m.requires_insurance, "shippingMethodType": m.type.key if m.type else "",
        "shippingMethodTypeId": m.type_id or 0,
        "locations": [{"provinceId": loc.province_id, "cityId": loc.city_id} for loc in m.locations.filter(is_deleted=False)] or None,
    }


class ShippingMethodsView(CustomerView):
    def post(self, request):
        cart = _cart(request.data)
        one_source = _single_warehouse(cart)
        methods = ShippingMethod.objects.filter(is_deleted=False).select_related("type").order_by("id")
        data = [shipping_dict(m) for m in methods if one_source or not m.source_dependent]
        return answer(data)


# -----------------------------------------------------------------------------
# Pre-invoice
# -----------------------------------------------------------------------------
def _pre_invoice(customer) -> Invoice | None:
    return customer.invoices.filter(state=S.PRE_INVOICE, is_deleted=False).order_by("-id").first()


class AddView(CustomerView):
    def post(self, request):
        d = request.data if isinstance(request.data, dict) else {}
        customer = request.user
        method_id = _int(d.get("ShippingMethodId") or d.get("shippingMethodId"))
        method_id = method_id or None  # 0 means "not chosen yet"
        if (d.get("gcNum") or "").strip() or (d.get("serial") or "").strip():
            return reply(None, 400, NOT_YET)
        if method_id and not (customer.first_name.strip() or customer.last_name.strip()):
            return reply(None, 403, "اجازه ایجاد فاکتور را ندارید. ابتدا اطلاعات پروفایل را تکمیل نمایید.")
        address = customer.addresses.filter(is_deleted=False).order_by("-is_default", "-id").first()
        if method_id and address is None:
            return reply(None, 409, "اجازه ایجاد فاکتور را ندارید. ابتدا آدرس خود را وارد نمایید.")
        method = None
        if method_id:
            method = ShippingMethod.objects.filter(id=method_id, is_deleted=False).select_related("type").first()
            if method is None:
                return reply(None, 404, "روش ارسال پیدا نشد.")
        cart = _cart(d.get("productVariants"))
        if not cart:
            return reply(None, 409, "سبد خرید خالی است، حداقل یک کالا انتخاب نمایید.")

        bundle, found = _bundle_for([v for v, _, _ in cart])
        listed = {r.id for r in catalog.listing_rows()}
        failed: dict[str, str] = {}
        lines: list[InvoiceLine] = []
        for vid, qty, name in cart:
            if vid not in found or found[vid][0] not in listed:
                failed[str(vid)] = "کالای مورد نظر یافت نشد."
                continue
            pid, v = found[vid]
            pricing = bundle.pricing(pid)
            available = Decimal(str(bundle.variant_stock(pid, v)))
            if pricing.after <= 0 or available <= 0:
                failed[str(vid)] = "موجودی کالا به اتمام رسید."
                continue
            if qty > available:
                qty = available
                failed[str(vid)] = "موجودی کالا کم است."
            lines.append(InvoiceLine(
                product_id=pid, variant_id=vid, barcode=v.barcode, name=name or bundle.products[pid].title,
                color_id=v.color_id, color_name=v.color.name if v.color else "", color_value=v.color.value if v.color else "",
                size_name=v.size.name if v.size else "", qty=qty, price=int(pricing.base), reduction=Decimal(str(pricing.reduction)),
                price_after_reduction=pricing.after,
            ))
        if not lines:
            return reply({"id": 0, "payableAmount": 0, "shippingMethodId": method_id, "failedItems": failed},
                         409, "امکان ثبت فاکتور وجود ندارد. موجودی کالاهای سبد به اتمام رسیده است.")

        amount = sum(int(ln.price * ln.qty) for ln in lines)
        after = sum(int(ln.price_after_reduction * ln.qty) for ln in lines)
        delivery = delivery_cost(method)
        with transaction.atomic():
            inv = _pre_invoice(customer) or Invoice(customer=customer)
            is_new = inv.pk is None
            inv.shipping_method, inv.address = method, address
            inv.amount, inv.reduction_amount, inv.delivery_amount, inv.deduction_amount = amount, amount - after, delivery, 0
            inv.payable_amount = after + delivery
            inv.description = str(d.get("description") or "")[:2000]
            inv.save()
            inv.lines.all().delete()
            for ln in lines:
                ln.invoice = inv
            InvoiceLine.objects.bulk_create(lines)
            if is_new or not inv.number:
                assign_number(inv)
        data = {"id": inv.id, "number": inv.number, "payableAmount": inv.payable_amount, "shippingMethodId": method_id,
                "failedItems": failed}
        if failed:
            return reply(data, 409, "موجودی بعضی از کالاهای سبد کافی نیست؛ آن‌ها از سبد حذف شدند. لطفا سبد را دوباره بررسی کنید.")
        return reply(data, message="فاکتور شما با موفقیت ثبت شد.")


# -----------------------------------------------------------------------------
# Rendering
# -----------------------------------------------------------------------------
def _feature(feature_id: int, value_id, name: str, value: str = "", media=None) -> dict:
    return {"featureId": feature_id, "value": value, "name": name, "displayPriority": None, "tsCodeId": 0,
            "mediaAttachments": media, "id": value_id or 0, "created": None}


def _address(a: CustomerAddress | None) -> dict | None:
    if a is None:
        return None
    province = Province.objects.filter(id=a.province_id).values_list("name", flat=True).first() or ""
    city = City.objects.filter(id=a.city_id).values_list("name", flat=True).first() or ""
    return {
        "id": a.id, "customerId": a.customer_id, "isDefault": a.is_default, "address": a.address,
        "provinceId": a.province_id, "provinceTitle": province, "cityId": a.city_id, "cityTitle": city,
        "isMyselfRecipient": a.is_myself_recipient, "firstName": a.first_name, "lastName": a.last_name,
        "zipCode": a.zip_code, "mobile": a.mobile, "title": a.title,
        "latitude": float(a.latitude) if a.latitude is not None else None,
        "longitude": float(a.longitude) if a.longitude is not None else None,
    }


def _customer(c) -> dict:
    return {"firstName": c.first_name, "lastName": c.last_name, "cellPhone": c.cellphone, "email": c.email,
            "isActive": c.is_active, "isTowFactorAuthentication": False, "nationalCode": c.national_code,
            "birthDate": c.birth_date.isoformat() if c.birth_date else None, "job": None, "id": c.id,
            "created": c.created.isoformat() if c.created else None}


def _lines(inv: Invoice) -> list[dict]:
    rows = list(inv.lines.all())
    bundle = catalog.ProductBundle.load({ln.product_id for ln in rows})
    stock = {}
    for pid in bundle.products:
        for v in bundle.visible_variants(pid):
            stock[v.id] = (pid, bundle.variant_stock(pid, v), v)
    out = []
    for ln in rows:
        p = bundle.products.get(ln.product_id)
        _, available, v = stock.get(ln.variant_id, (None, 0.0, None))
        images = bundle.color_images(ln.product_id, v) if v else []
        qty = float(ln.qty)
        out.append({
            "id": ln.id, "invoiceId": inv.id, "branchId": None, "productId": ln.product_id,
            "slug": p.slug if p else "", "name": ln.name,
            "variantFeatureValue": {
                "productVariantId": ln.variant_id, "featureValueDependencyId": 0, "id": ln.variant_id, "created": None,
                "productVariant": {"productId": ln.product_id, "price": ln.price, "reduction": float(ln.reduction), "discount": 0,
                                   "qty": available, "tax": 0, "vat": 0, "id": ln.variant_id, "created": None},
            },
            "qty": qty, "productQty": available, "image": images[0] if images else None,
            "price": ln.price, "totalPrice": int(ln.price * qty), "priceAfterReduction": ln.price_after_reduction,
            "totalPriceAfterReduction": int(ln.price_after_reduction * qty),
            "categoryId": p.category_id if p else None,
            "parentCategoryId": p.category.parent_id if p and p.category else None,
            "reductionPercent": float(ln.reduction), "reduction": float(ln.reduction),
            "reductionPrice": ln.price - ln.price_after_reduction,
            "parentFeatureValue": _feature(1, ln.color_id, ln.color_name, ln.color_value, images or None),
            "childFeatureValue": _feature(2, None, ln.size_name, ln.size_name) if ln.size_name else None,
        })
    return out


def full_invoice(inv: Invoice) -> dict:
    lines = _lines(inv)
    return {
        "id": inv.id, "created": inv.created.isoformat(), "customerId": inv.customer_id, "amount": inv.amount,
        "reduction": 0, "discount": inv.reduction_amount, "tax": 0, "vat": 0, "invoiceType": inv.state,
        "description": inv.description, "image": None, "customer": _customer(inv.customer),
        "customerAddressId": inv.address_id, "customerAddress": _address(inv.address), "invoiceDetails": lines,
        "categoryId": lines[0]["categoryId"] if lines else None, "parentCategoryId": lines[0]["parentCategoryId"] if lines else None,
        "payableAmount": inv.payable_amount, "deliveryAmount": inv.delivery_amount, "shippingMethodId": inv.shipping_method_id,
    }


def invoice_summary(inv: Invoice) -> dict:
    m = inv.shipping_method
    lines = _lines(inv)
    return {
        "id": inv.id, "customerId": inv.customer_id, "amount": inv.amount, "payableAmount": inv.payable_amount,
        "finalAmount": inv.payable_amount, "totalAmountPayable": inv.payable_amount, "discount": inv.reduction_amount,
        "reductionAmount": inv.reduction_amount, "totalReductionAmounts": inv.reduction_amount + inv.deduction_amount,
        "amountAfterReduction": inv.amount - inv.reduction_amount, "hasDiscount": inv.reduction_amount > 0,
        "invoiceNumber": inv.number,
        "invoiceState": inv.state, "invoiceType": inv.state, "createDatePersian": jalali(inv.created, with_time=False),
        "shippingMethodId": inv.shipping_method_id or 0, "shippingMethodName": m.name if m else "",
        "shippingMethodType": m.type.key if m and m.type else "", "shippingMethodTypeId": m.type_id if m else 0,
        "shippingMethodTypeTitle": m.type.name if m and m.type else "", "deliveryAmount": inv.delivery_amount,
        "customerAddress": _address(inv.address), "customer": _customer(inv.customer),
        "invoiceDetails": [
            {"invoiceId": inv.id, "name": ln["name"], "price": ln["price"], "totalPrice": ln["totalPrice"], "qty": ln["qty"],
             "productId": ln["productId"], "slug": ln["slug"], "image": ln["image"], "childFeatureValue": ln["childFeatureValue"],
             "parentFeatureValue": ln["parentFeatureValue"], "priceAfterReduction": ln["priceAfterReduction"],
             "reductionPrice": ln["reductionPrice"]}
            for ln in lines
        ],
        "reduction": 0, "snappPayToken": None, "snappPayTransactionId": None, "tax": 0, "taxAmount": 0, "variableAmount": 0,
        "vat": 0, "vatAmount": 0, "qty": sum(ln["qty"] for ln in lines),
    }


class LastPreInvoiceView(CustomerView):
    def get(self, request):
        inv = _pre_invoice(request.user)
        if not inv:
            return reply(None, 404, "پیش فاکتوری وجود ندارد.")
        return reply(full_invoice(inv))


class DeletePreInvoiceView(CustomerView):
    def get(self, request, invoice_id: int):
        n = request.user.invoices.filter(id=invoice_id, state=S.PRE_INVOICE, is_deleted=False).update(is_deleted=True)
        return reply(True, message="اطلاعات با موفقیت حذف شدند.") if n else reply(False, 400, "فاکتور یافت نشد")


class ClearCartView(CustomerView):
    def post(self, request):
        request.user.invoices.filter(state=S.PRE_INVOICE, is_deleted=False).update(is_deleted=True)
        return reply(True, message="سبد خرید خالی شد.")


class CustomerInvoicesView(CustomerView):
    def get(self, request):
        qs = request.user.invoices.filter(is_deleted=False).select_related("shipping_method__type", "address", "customer")
        if (kind := _int(request.query_params.get("invoiceType"))) is not None:
            qs = qs.filter(state=kind)
        rows = [invoice_summary(inv) for inv in qs.order_by("-id")]
        return reply({
            "invoices": rows,
            "successfully": [r for r in rows if r["invoiceState"] == S.SUCCESSFUL],
            "preInvoice": [r for r in rows if r["invoiceState"] in (S.PRE_INVOICE, S.SUSPENDED)],
            "canceledInvoices": [r for r in rows if r["invoiceState"] == S.CANCELLED],
        })


class CustomerInvoiceView(CustomerView):
    def get(self, request, invoice_id: int):
        inv = request.user.invoices.filter(id=invoice_id, is_deleted=False).first()
        if not inv:
            return reply(None, 404, "فاکتور یافت نشد")
        return reply(full_invoice(inv))
