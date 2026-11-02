"""
The configs page: ShippingMethod/*, Bank/*, ThirdParty/*.

Shipping methods keep the old shapes: a disabled method is soft-deleted and
still listed ("state" = active); its icon is a file from Cdn/upload (mediaId).

Bank gateways are the banks list (with logos, from Dadehfa) and the gateways
configured for the site; payments are counted per gateway. Torob visit logs are not
recorded any more, so the Torob report has the products and their Torob flag
with zero visits.

    GET  ShippingMethod/All | ShippingMethod/<id> | ShippingMethod/Types
    POST ShippingMethod {...} | ShippingMethod/<id> {...} | ShippingMethod/methods/<id>?state=
    POST ShippingMethod/default/<id>?isDefault=
    POST ShippingMethod/Types "title" | ShippingMethod/Types/<id> "title"
    GET  Bank/GetGateway | Bank/GetInfo | Bank/SoftDelete     POST Bank/AddBankGateway | Bank/UpdateBankGateway
    GET  ThirdParty/LogSummary | ThirdParty/ProductReport?pageNumber=&pageSize= | ThirdParty/ProductVisitPieChart | ThirdParty/ProductVisitBarChart
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.response import Response

from apps.storefront.envelope import jalali
from apps.website.models import BankGateway, BankInfo, City, InvoicePayment, MediaAttachment, Product, Province, ShippingMethod, ShippingMethodLocation, ShippingMethodType

from .. import products as index
from ..envelope import fail, ok
from ..paging import paginated, to_bool, to_int
from .auth import AdminView
from .gallery import _url

NOT_FOUND = "روش ارسال یافت نشد"


# -----------------------------------------------------------------------------
# Shipping
# -----------------------------------------------------------------------------
def _dto(m: ShippingMethod, provinces: dict, cities: dict) -> dict:
    return {
        "id": m.id, "name": m.name, "fixedCost": m.fixed_cost, "shippingMethodTypeId": m.type_id,
        "isDynamicPricing": m.is_dynamic_pricing, "description": m.description, "requiresInsurance": m.requires_insurance,
        "insuranceCost": m.insurance_cost, "taxPercentage": float(m.tax_percentage), "taxAmount": m.tax_amount,
        "variableFee": m.variable_fee, "insurancePercentage": float(m.insurance_percentage),
        "shippingMethodType": m.type.name if m.type else None, "state": not m.is_deleted, "isDefault": m.is_default,
        "icon": _url(m.icon) if m.icon else m.icon, "sourceDependent": m.source_dependent,
        "locations": [
            {
                "id": loc.id, "provinceId": loc.province_id, "cityId": loc.city_id,
                "provinceName": provinces.get(loc.province_id), "cityName": cities.get(loc.city_id),
            }
            for loc in m.locations.all() if not loc.is_deleted
        ],
    }


def _dtos(methods: list[ShippingMethod]) -> list[dict]:
    locs = [loc for m in methods for loc in m.locations.all()]
    provinces = dict(Province.objects.filter(id__in={l.province_id for l in locs}).values_list("id", "name"))
    cities = dict(City.objects.filter(id__in={l.city_id for l in locs}).values_list("id", "name"))
    return [_dto(m, provinces, cities) for m in methods]


def _methods():
    return ShippingMethod.objects.select_related("type").prefetch_related("locations").order_by("id")


class ShippingListView(AdminView):
    def get(self, request):
        return ok({"result": _dtos(list(_methods()))})


def _number(d: dict, key: str) -> Decimal:
    try:
        return Decimal(str(d.get(key) or 0))
    except InvalidOperation:
        raise ValueError(f"مقدار {key} نامعتبر است")


def _save(m: ShippingMethod, d: dict, is_new: bool):
    name = (d.get("name") or "").strip()
    if not name:
        return fail("نام روش ارسال الزامی است", 400)
    type_id = to_int(d.get("shippingMethodTypeId"))
    if not ShippingMethodType.objects.filter(id=type_id, is_deleted=False).exists():
        return fail("نوع روش ارسال نامعتبر است", 400)
    media_id = to_int(d.get("mediaId"))
    media = MediaAttachment.objects.filter(id=media_id, table=MediaAttachment.Table.MEDIA_ATTACHMENTS).first() if media_id else None
    if (is_new or media_id) and media is None:
        return fail("خطا در ثبت تصویر شاخص.", 400)
    try:
        numbers = {f: round(_number(d, k)) for f, k in (
            ("fixed_cost", "fixedCost"), ("insurance_cost", "insuranceCost"), ("tax_amount", "taxAmount"), ("variable_fee", "variableFee"),
        )}
        numbers |= {f: _number(d, k) for f, k in (("tax_percentage", "taxPercentage"), ("insurance_percentage", "insurancePercentage"))}
    except (ValueError, OverflowError) as exc:
        return fail(str(exc), 400)
    with transaction.atomic():
        m.name, m.type_id, m.description = name, type_id, d.get("description") or ""
        for f, v in numbers.items():
            setattr(m, f, v)
        m.is_dynamic_pricing = bool(to_bool(d.get("isDynamicPricing")))
        m.requires_insurance = bool(to_bool(d.get("requiresInsurance")))
        m.source_dependent = bool(to_bool(d.get("sourceDependent")))
        if media:
            m.icon = media.media_url
        m.last_modified = timezone.now()
        m.save()
        sent = [x for x in d.get("locations") or [] if isinstance(x, dict)]
        current = {loc.id: loc for loc in m.locations.filter(is_deleted=False)}
        keep = set()
        for x in sent:
            loc = current.get(to_int(x.get("id"))) or ShippingMethodLocation(shipping_method=m, created=timezone.now())
            loc.province_id, loc.city_id = to_int(x.get("provinceId")), to_int(x.get("cityId"))
            loc.last_modified = timezone.now()
            loc.save()
            keep.add(loc.id)
        m.locations.filter(is_deleted=False).exclude(id__in=keep).update(is_deleted=True, last_modified=timezone.now())
    return Response({"result": m.id if is_new else True})


class ShippingCreateView(AdminView):
    def post(self, request):
        return _save(ShippingMethod(created=timezone.now()), request.data, True)


class ShippingDetailView(AdminView):
    def get(self, request, method_id: int):
        m = _methods().filter(id=method_id).first()
        return ok({"result": _dtos([m])[0]}) if m else fail(NOT_FOUND, 404)

    def post(self, request, method_id: int):
        m = ShippingMethod.objects.filter(id=method_id).first()
        return _save(m, request.data, False) if m else fail(NOT_FOUND, 404)


class ShippingStateView(AdminView):
    """POST ShippingMethod/methods/<id>?state=true enables the method, false disables it (and it stops being the default)."""

    def post(self, request, method_id: int):
        active = to_bool(request.query_params.get("state")) is not False
        fields = {} if active else {"is_default": False}
        n = ShippingMethod.objects.filter(id=method_id).update(is_deleted=not active, last_modified=timezone.now(), **fields)
        return ok({"message": "عملیات موفقیت آمیز بود."}) if n else fail(NOT_FOUND, 404)


class ShippingDefaultView(AdminView):
    """POST ShippingMethod/default/<id>?isDefault=true makes it the only default, false leaves none."""

    def post(self, request, method_id: int):
        method = ShippingMethod.objects.filter(id=method_id).first()
        if not method:
            return fail(NOT_FOUND, 404)
        wanted = bool(to_bool(request.query_params.get("isDefault")))
        if wanted and method.is_deleted:
            return fail("روش ارسال غیرفعال نمی‌تواند پیش‌فرض باشد.", 400)
        with transaction.atomic():
            ShippingMethod.objects.filter(is_default=True).update(is_default=False, last_modified=timezone.now())
            if wanted:
                ShippingMethod.objects.filter(id=method_id).update(is_default=True, last_modified=timezone.now())
        return ok({"message": "عملیات موفقیت آمیز بود."})


def _title(request) -> str:
    data = request.data
    return (data if isinstance(data, str) else (data or {}).get("title") or "").strip()


class ShippingTypesView(AdminView):
    def get(self, request):
        types = ShippingMethodType.objects.filter(is_deleted=False).order_by("id")
        return ok({"result": [{"id": t.id, "name": t.name} for t in types]})

    def post(self, request):
        title = _title(request)
        if not title:
            return fail("عنوان الزامی است", 400)
        t = ShippingMethodType.objects.create(name=title, created=timezone.now())
        return Response(status=201, headers={"Location": f"Types?typeId={t.id}"})


class ShippingTypeUpdateView(AdminView):
    def post(self, request, type_id: int):
        title = _title(request)
        if not title:
            return fail("عنوان الزامی است", 400)
        n = ShippingMethodType.objects.filter(id=type_id, is_deleted=False).update(name=title, last_modified=timezone.now())
        return ok({"message": "عملیات موفقیت آمیز بود."}) if n else fail("نوع روش ارسال یافت نشد", 404)


# -----------------------------------------------------------------------------
# Bank gateways: the banks (with their logos) and the configured gateways. The
# site offers the active gateways it can talk to (zarinpal, snapppay).
# -----------------------------------------------------------------------------
def _gateway(g: BankGateway, stats: dict) -> dict:
    count, total, last = stats.get(g.bank.key, (0, 0, None))
    return {
        "id": g.id, "bankId": g.bank_id, "bankName": g.bank.name, "icon": g.bank.icon or None,
        "merchantCode": g.merchant or g.terminal_id, "isDelete": g.is_deleted,
        "transactionCount": count, "sumTransactionPrice": total,
        "lastTransaction": {"createDate": jalali(last.verified_at or last.created), "price": last.amount} if last else None,
    }


class GatewayListView(AdminView):
    def get(self, request):
        stats = {}
        for key in BankGateway.objects.values_list("bank__key", flat=True).distinct():
            paid = InvoicePayment.objects.filter(gateway=key, is_success=True)
            stats[key] = (paid.count(), paid.aggregate(t=Sum("amount"))["t"] or 0, paid.order_by("-id").first())
        gateways = BankGateway.objects.select_related("bank").order_by("id")
        return ok({"result": [_gateway(g, stats) for g in gateways]})


class BankInfoView(AdminView):
    def get(self, request):
        return ok({"result": [{"bankId": b.id, "bankName": b.name} for b in BankInfo.objects.filter(is_deleted=False)]})


def _save_gateway(request, g: BankGateway | None):
    d = request.data if isinstance(request.data, dict) else {}
    bank = BankInfo.objects.filter(id=to_int(d.get("bankId")), is_deleted=False).first()
    if not bank:
        return fail("این بانک موجود نیست.", 400)
    merchant, terminal = str(d.get("merchant") or "").strip(), str(d.get("terminalId") or "").strip()
    if g is None and BankGateway.objects.filter(bank=bank, is_deleted=False).exists():
        return fail("این پورتال وجود دارد.", 400)
    g = g or BankGateway(created=timezone.now())
    g.bank, g.merchant, g.terminal_id = bank, merchant, terminal
    g.merchant_key = merchant or terminal
    g.last_modified = timezone.now()
    g.save()
    return ok({"result": True})


class GatewayAddView(AdminView):
    def post(self, request):
        return _save_gateway(request, None)


class GatewayUpdateView(AdminView):
    def post(self, request):
        g = BankGateway.objects.filter(id=to_int(request.data.get("id"))).first() if isinstance(request.data, dict) else None
        if not g:
            return fail("اطلاعات اشتباه است.", 400)
        return _save_gateway(request, g)


class GatewayToggleView(AdminView):
    """SoftDelete?gatewayId=&active=: active=true switches it back on, otherwise off."""

    def get(self, request):
        q = request.query_params
        n = BankGateway.objects.filter(id=to_int(q.get("gatewayId"))).update(
            is_deleted=not bool(to_bool(q.get("active"))), last_modified=timezone.now())
        return ok({"result": True}) if n else fail("درگاه پرداخت موجود نیست.", 404)


# -----------------------------------------------------------------------------
# Torob
# -----------------------------------------------------------------------------
def _torob_flags() -> dict[int, bool]:
    return dict(Product.objects.filter(id__in=[r.id for r in index.admin_rows()]).values_list("id", "show_torob"))


class TorobSummaryView(AdminView):
    def get(self, request):
        return ok({"result": {
            "lastVisitDatePersian": None, "lastVisitTime": None,
            "shopProductInTorobCount": sum(_torob_flags().values()), "visitedFromTorobCount": 0, "mostVisitedProduct": None,
        }})


class TorobReportView(AdminView):
    def get(self, request):
        flags = _torob_flags()
        rows = [r for r in index.admin_rows() if flags.get(r.id)]

        def item(r) -> dict:
            return {
                "productId": r.id, "title": r.name, "amount": r.after, "qty": r.qty, "stockQty": r.qty,
                "visitCount": 0, "lastVisitDateTime": None,
            }

        page = paginated(rows, to_int(request.query_params.get("pageNumber"), 1), to_int(request.query_params.get("pageSize"), 20), item)
        shown = sum(flags.values())
        page["additionalInfo"] = {"totalShowTorobCount": shown, "totalHideTorobCount": len(flags) - shown}
        return ok({"result": page})


class EmptyChartView(AdminView):
    def get(self, request):
        return ok({"result": []})
