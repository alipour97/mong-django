"""
Coupon/* and the gift card part of Customer/*, as the old AdminApi's CouponController.

Coupons and gift cards live in the sales software, so the panel reads them through the connector.

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
from sqlalchemy.exc import SQLAlchemyError

from apps.erp.connector import get_connector
from apps.storefront.envelope import jalali

from ..envelope import fail, ok
from ..paging import one_page, to_int
from .auth import AdminView

NO_ANSWER = "نرم‌افزار فروش پاسخ نمی‌دهد. لطفا کمی بعد دوباره تلاش کنید."
MAX_PAGE_SIZE = 200


def _moment(value) -> datetime | None:
    """A date from the panel, in the software's local time."""
    moment = parse_datetime(str(value or ""))
    if moment and timezone.is_aware(moment):
        return timezone.localtime(moment).replace(tzinfo=None)
    return moment


def _paging(q) -> tuple[int, int]:
    return max(to_int(q.get("pageNumber"), 1), 1), min(max(to_int(q.get("pageSize"), 10), 1), MAX_PAGE_SIZE)


def _labels(row: dict) -> dict:
    return {"totalCount": row["total"], "totalActive": row["active"], "totalUnActice": row["total"] - row["active"], "totalUsed": row["used"]}


class SoftwareView(AdminView):
    """A panel page that waits on the sales software."""

    def handle_exception(self, exc):
        if isinstance(exc, SQLAlchemyError):
            return fail(NO_ANSWER, 502)
        return super().handle_exception(exc)


class CouponListView(SoftwareView):
    def get(self, request):
        q = request.query_params
        page, size = _paging(q)
        total, rows = get_connector().coupon_page(search=(q.get("search") or "").strip(), created_from=_moment(q.get("fromDate")),
                                                  expires_to=_moment(q.get("toDate")), page=page, size=size)
        items = [{
            "id": r["Id"], "customerId": r["CustomerId"], "serial": r["Serial"], "reduction": float(r["Reduction"] or 0),
            "expiredDate": r["ExpiredDate"], "isUsed": bool(r["IsUsed"]), "usedDate": jalali(r["UsedDate"]),
            "minPrice": float(r["MinPrice"] or 0), "maxPrice": float(r["MaxPrice"]) if r["MaxPrice"] is not None else None,
            "isActive": bool(r["IsActive"]), "bankPortalEndTime": r["BankPortalEndTime"],
            "customerFirstName": r["FirstName"], "customerLastName": r["LastName"],
        } for r in rows]
        return ok({"result": one_page(items, total, page, size)})


class CouponLabelView(SoftwareView):
    def get(self, request):
        return ok({"result": _labels(get_connector().coupon_labels())})


class CouponInfoView(SoftwareView):
    def get(self, request):
        coupon_id = to_int(request.query_params.get("id"))
        if not coupon_id:  # the panel asks once before a coupon is picked
            return ok({"result": None})
        info = get_connector().coupon_info(coupon_id)
        if info is None:
            return fail("کوپن وجود ندارد.", 404)
        rows = info["rows"]
        return ok({"result": {
            "totalCustomerCount": len(rows), "totalUsed": info["used"], "totalUnUsed": len(rows) - info["used"],
            "totalActive": info["active"], "totalUnActive": len(rows) - info["active"],
            "customers": [{"id": r["CustomerId"], "couponId": r["Id"], "firstName": r["FirstName"], "lastName": r["LastName"]} for r in rows],
        }})


class GiftCardListView(SoftwareView):
    def post(self, request):
        q, d = request.query_params, request.data or {}
        page, size = _paging(q)
        filters = {
            "search": str(d.get("search") or "").strip(), "start_from": _moment(d.get("fromStartDate")), "start_to": _moment(d.get("toStartDate")),
            "exp_from": _moment(d.get("fromExpDate")), "exp_to": _moment(d.get("toExpDate")),
            "balance_from": to_int(d.get("fromGCBalance")), "balance_to": to_int(d.get("toGCBalance")),
        }
        total, rows = get_connector().gift_card_page(filters, page, size)
        items = [{
            "id": r["Id"], "gcNum": r["GCNum"], "startDate": jalali(r["StartDate"], with_time=False), "expDate": jalali(r["ExpDate"], with_time=False),
            "gcBalance": float(r["GCBalance"]), "isActive": bool(r["IsActive"]), "customerId": r["CustomerId"], "useDepCode": bool(r["UseDepCode"]),
            "minFactorPrice": float(r["MinFactorPrice"] or 0), "giftGroupMapId": r["GiftGroupMapId"], "customerMapId": r["CustomerMapId"],
            "useCompelete": bool(r["UseCompelete"]), "customerMobile": r["Mobile"], "customerFirstName": r["FirstName"],
            "customerLastName": r["LastName"], "invoiceCount": r["InvoiceCount"],
        } for r in rows]
        return ok({"result": one_page(items, total, page, size)})


class GiftCardLabelView(SoftwareView):
    def get(self, request):
        return ok({"result": _labels(get_connector().gift_card_labels())})
