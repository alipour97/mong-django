"""
Coupon/* and the gift card part of Customer/*, as the old AdminApi's CouponController.

The sales software's coupons and gift cards, as its last sync read them. The site's own are in the Django admin.

    GET  Coupon/GetAll?search=&fromDate=&toDate=&pageNumber=&pageSize=  fromDate: created, toDate: expires
    GET  Coupon/GetLable
    GET  Coupon/GetGeneralCouponInfo?id=                                who took a general coupon
    POST Customer/GetAllGiftCard?pageNumber=&pageSize=
    GET  Customer/GetGiftCardLable
"""
from __future__ import annotations

from datetime import datetime

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.erp.models import ErpCoupon, ErpGiftCard
from apps.storefront.catalog import norm
from apps.storefront.envelope import jalali

from ..envelope import fail, ok
from ..paging import one_page, to_int
from .auth import AdminView

MAX_PAGE_SIZE = 200


def _moment(value) -> datetime | None:
    """A date from the panel."""
    moment = parse_datetime(str(value or ""))
    if moment and timezone.is_naive(moment):
        return timezone.make_aware(moment)
    return moment


def _paging(q) -> tuple[int, int]:
    return max(to_int(q.get("pageNumber"), 1), 1), min(max(to_int(q.get("pageSize"), 10), 1), MAX_PAGE_SIZE)


def _labels(total: int, active: int, used: int) -> dict:
    return {"totalCount": total, "totalActive": active, "totalUnActice": total - active, "totalUsed": used}


class CouponListView(AdminView):
    def get(self, request):
        q = request.query_params
        page, size = _paging(q)
        rows = ErpCoupon.objects.filter(listed=True)
        search = norm(q.get("search"))
        if search:
            rows = rows.filter(search_text__contains=search)
        created_from, expires_to = _moment(q.get("fromDate")), _moment(q.get("toDate"))
        if created_from:
            rows = rows.filter(created__gte=created_from)
        if expires_to:
            rows = rows.filter(expires__lte=expires_to)
        total = rows.count()
        items = [{
            "id": r.id, "customerId": r.customer_erp_id, "serial": r.serial, "reduction": float(r.reduction),
            "expiredDate": r.expires, "isUsed": r.is_used, "usedDate": jalali(r.used_at),
            "minPrice": r.min_price, "maxPrice": r.max_price,
            "isActive": r.is_active, "bankPortalEndTime": r.held_until,
            "customerFirstName": r.first_name or None, "customerLastName": r.last_name or None,
        } for r in rows[(page - 1) * size:page * size]]
        return ok({"result": one_page(items, total, page, size)})


class CouponLabelView(AdminView):
    def get(self, request):
        rows = ErpCoupon.objects.filter(listed=True)
        return ok({"result": _labels(rows.count(), rows.filter(is_active=True).count(), rows.filter(is_used=True).count())})


class CouponInfoView(AdminView):
    def get(self, request):
        coupon_id = to_int(request.query_params.get("id"))
        if not coupon_id:  # the panel asks once before a coupon is picked
            return ok({"result": None})
        source = ErpCoupon.objects.filter(id=coupon_id).first()
        if source is None:
            return fail("کوپن وجود ندارد.", 404)
        rows = list(ErpCoupon.objects.filter(serial=source.serial, customer_erp_id__isnull=False))
        used, active = sum(r.is_used for r in rows), sum(r.is_active for r in rows)
        return ok({"result": {
            "totalCustomerCount": len(rows), "totalUsed": used, "totalUnUsed": len(rows) - used,
            "totalActive": active, "totalUnActive": len(rows) - active,
            "customers": [{"id": r.customer_erp_id, "couponId": r.id, "firstName": r.first_name or None, "lastName": r.last_name or None} for r in rows],
        }})


class GiftCardListView(AdminView):
    def post(self, request):
        q, d = request.query_params, request.data or {}
        page, size = _paging(q)
        rows = ErpGiftCard.objects.all()
        search = norm(str(d.get("search") or ""))
        if search:
            rows = rows.filter(search_text__contains=search)
        for lookup, value in (
            ("starts__gte", _moment(d.get("fromStartDate"))), ("starts__lte", _moment(d.get("toStartDate"))),
            ("expires__gte", _moment(d.get("fromExpDate"))), ("expires__lte", _moment(d.get("toExpDate"))),
            ("balance__gte", to_int(d.get("fromGCBalance"))), ("balance__lte", to_int(d.get("toGCBalance"))),
        ):
            if value is not None:
                rows = rows.filter(**{lookup: value})
        total = rows.count()
        items = [{
            "id": r.id, "gcNum": r.number, "startDate": jalali(r.starts, with_time=False), "expDate": jalali(r.expires, with_time=False),
            "gcBalance": r.balance, "isActive": r.is_active, "customerId": r.customer_erp_id, "useDepCode": r.use_dep_code,
            "minFactorPrice": r.min_price, "giftGroupMapId": r.gift_group_map_id or None, "customerMapId": r.customer_map_id or None,
            "useCompelete": r.use_whole, "customerMobile": r.mobile or None, "customerFirstName": r.first_name or None,
            "customerLastName": r.last_name or None, "invoiceCount": r.invoice_count,
        } for r in rows[(page - 1) * size:page * size]]
        return ok({"result": one_page(items, total, page, size)})


class GiftCardLabelView(AdminView):
    def get(self, request):
        rows = ErpGiftCard.objects.all()
        return ok({"result": _labels(rows.count(), rows.filter(is_active=True).count(), rows.filter(balance=0).count())})
