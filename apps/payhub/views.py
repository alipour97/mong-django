"""
The hub over HTTP: the contract of Mong.Pay (and Dadehfa's hub before it), kept
as it is so the old site only needs PayUrl changed. Same routes, same fields:

    POST /GenerateToken                                     -> {id, token, status, message}
    GET  /GoToPayPage/<token>/<invoiceId>/<amount>          (browser, Zarinpal)
    POST /GetPaymentToken/<token>/<invoiceId>/<amount>      -> {paymentToken, paymentPageUrl, transactionId}
    GET|POST /zarinpal/callback/<token>                     <- Zarinpal
    GET|POST /api/SnappPay/CallBack/<id>/<token>            <- SnappPay returnURL
    POST /PaymentVerification/<token>                       -> {status, companyId, customerId, amount}, "ok" once
    GET  /CheckToken/<token>
    POST /api/SnappPay/GetTokenByCompany/<id>               -> a hub token for the calls below
    POST /api/SnappPay/EligibleWithAuth?amount= | PaymentCancel | UpdatePayment | PaymentStatus

Server-to-server routes answer only PAYHUB_ALLOWED_API_IPS or the X-Mong-Hub-Key
that Mong.Pay's SnappPayForward sends (PAYHUB_ACCEPT_KEY).
"""
from __future__ import annotations

import hmac
import json
import logging
from decimal import Decimal, InvalidOperation
from html import escape
from urllib.parse import urlsplit

import requests
from django.conf import settings
from django.core import signing
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from . import service, snapppay, zarinpal
from .models import PayRecord
from .service import S, SNAPPPAY, ZARINPAL, Refused

logger = logging.getLogger(__name__)

HUB_TOKEN_SALT = "payhub.api"
HUB_TOKEN_SECONDS = 3000


def _page(message: str, status: int = 400, head: str = "") -> HttpResponse:
    html = (f"<!doctype html><html lang=fa dir=rtl><meta charset=utf-8><meta name=viewport content=\"width=device-width\">{head}"
            f"<title>پرداخت</title><body style=\"font-family:Tahoma,sans-serif;max-width:480px;margin:60px auto;padding:0 16px;line-height:2\">"
            f"<p>{escape(message)}</p><p><a href=\"{escape(settings.SITE_URL)}\">بازگشت به فروشگاه</a></p></body></html>")
    return HttpResponse(html, status=status, content_type="text/html; charset=utf-8")


def _wait_page() -> HttpResponse:
    return _page("در حال بررسی پرداخت شما، لطفا چند لحظه صبر کنید.", 200, '<meta http-equiv="refresh" content="3">')


def _caller_ip(request) -> str:
    # nginx overwrites X-Real-IP (deploy/nginx), and gunicorn listens on 127.0.0.1 only.
    return (request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR") or "").strip()


def is_api_caller(request) -> bool:
    key = request.META.get("HTTP_X_MONG_HUB_KEY", "")
    if key and settings.PAYHUB_ACCEPT_KEY:
        return hmac.compare_digest(key.encode(), settings.PAYHUB_ACCEPT_KEY.encode())
    ip = _caller_ip(request)
    return ip in ("127.0.0.1", "::1") or ip in settings.PAYHUB_ALLOWED_API_IPS


def _allowed_callback(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and (parts.hostname or "").lower() in settings.PAYHUB_ALLOWED_CALLBACK_HOSTS


def _body(request) -> dict:
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def _find(data: dict, name: str):
    """The old site sends camelCase; any casing is accepted, as before."""
    for key, value in data.items():
        if key.lower() == name.lower():
            return value
    return None


def _text(data: dict, name: str) -> str:
    value = _find(data, name)
    return str(value) if isinstance(value, (str, int, float, Decimal)) else ""


def _rial(value) -> int | None:
    """A whole, positive amount."""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return int(number) if number > 0 and number == number.to_integral_value() else None


def _record(token: str) -> PayRecord | None:
    return PayRecord.objects.filter(token=token).first()


def _pass_to_old_hub(request, path: str) -> HttpResponse | None:
    """While moving: a token this hub does not know was made by Mong.Pay, and only Mong.Pay can finish it."""
    if not settings.PAYHUB_OLD_HUB_URL:
        return None
    try:
        resp = requests.request(request.method, f"{settings.PAYHUB_OLD_HUB_URL}{path}", data=request.body,
                                headers={"Content-Type": "application/json"}, timeout=90)
    except requests.RequestException:
        logger.exception("payhub: old hub did not answer %s", path)
        return None
    return HttpResponse(resp.content, status=resp.status_code, content_type=resp.headers.get("Content-Type", "application/json"))


class HubView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]


class ServerView(HubView):
    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not is_api_caller(request):
            logger.warning("payhub: refused %s from %s", request.path, _caller_ip(request))
            raise PermissionDenied()


class SnappApiView(ServerView):
    """Routes that also need the token of GetTokenByCompany."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        header = request.META.get("HTTP_AUTHORIZATION", "")
        try:
            signing.loads(header[7:].strip(), salt=HUB_TOKEN_SALT, max_age=HUB_TOKEN_SECONDS)
        except signing.BadSignature:
            self.unauthorized = True
            return
        self.unauthorized = False

    def dispatch_snapp(self, call):
        if self.unauthorized:
            return HttpResponse(status=401)
        reply = call()
        return HttpResponse(reply.for_caller(), content_type="application/json",
                            status=502 if reply.no_answer else reply.http if 200 <= reply.http < 600 else 502)


class HealthView(HubView):
    def get(self, request):
        return HttpResponse(f"ok sandbox={settings.ZARINPAL_SANDBOX} snapppay={'set' if snapppay.configured() else 'MISSING'}",
                            content_type="text/plain")


class GenerateTokenView(ServerView):
    def post(self, request):
        data = _body(request)
        amount = _rial(_find(data, "payAmount"))
        success, failed = _text(data, "successCallBack"), _text(data, "failedCallBack")
        gateway = _text(data, "gateway").strip().lower()
        # BankGateways.MerchantKey is nvarchar with trailing spaces.
        gateway_code = _text(data, "gatewayCode").strip()

        def fail(message: str) -> JsonResponse:
            logger.warning("payhub generate refused: %s gateway=%s amount=%s", message, gateway, amount)
            return JsonResponse({"id": None, "token": None, "status": "error", "message": message})

        if amount is None:
            return fail("مبلغ پرداخت نامعتبر است.")
        if not _allowed_callback(success) or not _allowed_callback(failed):
            return fail("آدرس بازگشت مجاز نیست.")
        if gateway not in service.GATEWAYS:
            return fail("درگاه پرداخت پشتیبانی نمی‌شود.")
        merchant = ""
        if gateway == SNAPPPAY:
            if not snapppay.configured():
                return fail("اسنپ‌پی روی هاب پرداخت تنظیم نشده است.")
        else:
            merchant = gateway_code if len(gateway_code) == zarinpal.UUID_LEN else settings.ZARINPAL_MERCHANT_ID
            if len(merchant) != zarinpal.UUID_LEN:
                return fail("مرچنت زرین‌پال تنظیم نشده است.")

        company = _rial(_find(data, "companyId")) or 0
        record = service.create(gateway=gateway, amount=amount, success=success, failed=failed, merchant_id=merchant,
                                cell_phone=_text(data, "cellPhone"), customer_key=_text(data, "customerKey"), company_id=company)
        return JsonResponse({"id": record.pk, "token": record.token, "status": "success", "message": None})


class GoToPayPageView(HubView):
    def get(self, request, token: str, transaction_id: str, pay_amount: str):
        record = _record(token)
        if not record or record.gateway != ZARINPAL:
            return _page(service.BAD_LINK, 404)
        try:
            return HttpResponseRedirect(service.start_zarinpal(record, transaction_id, _rial(pay_amount) or 0))
        except Refused as exc:
            if record.state == S.FAILED:
                return HttpResponseRedirect(service.failed_redirect(record, "خطا در اتصال به درگاه پرداخت: " + exc.message))
            return _page(exc.message, exc.status)


class ZarinpalCallbackView(HubView):
    def handle(self, request, token: str):
        record = _record(token)
        if not record or record.gateway != ZARINPAL:
            return _page("تراکنش پیدا نشد. اگر مبلغی از حساب شما کسر شده، به‌صورت خودکار برمی‌گردد.", 404)
        q = request.query_params
        try:
            return HttpResponseRedirect(service.zarinpal_return(record, q.get("Authority", ""), q.get("Status", "")))
        except Refused as exc:
            return _page(exc.message, exc.status)

    get = post = handle


class GetPaymentTokenView(ServerView):
    def post(self, request, token: str, transaction_id: str, pay_amount: str):
        empty = {"paymentToken": None, "paymentPageUrl": None}
        record = _record(token)
        if not snapppay.configured() or not record:
            return JsonResponse(empty, status=400)
        data = _body(request)
        order = {"amount": _rial(_find(data, "amount")), "discountAmount": int(_rial(_find(data, "discountAmount")) or 0),
                 "externalSourceAmount": int(_rial(_find(data, "externalSourceAmount")) or 0),
                 "mobile": _text(data, "mobile"), "cartList": _find(data, "cartList")}
        try:
            return JsonResponse(service.start_snapp(record, transaction_id, _rial(pay_amount) or 0, order))
        except Refused:
            return JsonResponse(empty, status=400)  # the old site reads a GetPaymentTokenResponse on 400


class SnappCallbackView(HubView):
    def handle(self, request, record_id: str, token: str):
        record = _record(token)
        if not record or record.gateway != SNAPPPAY or str(record.pk) != record_id:
            return _page("تراکنش پیدا نشد. اگر مبلغی از حساب شما کسر شده، به‌صورت خودکار برمی‌گردد.", 404)
        fields = {**request.query_params.dict(), **(request.data.dict() if hasattr(request.data, "dict") else request.data)}
        try:
            url = service.snapp_return(record, fields)
        except Refused as exc:
            return _page(exc.message, exc.status)
        return HttpResponseRedirect(url) if url else _wait_page()

    get = post = handle


class PaymentVerificationView(ServerView):
    def post(self, request, token: str):
        record = _record(token)
        if not record:
            passed = _pass_to_old_hub(request, f"/PaymentVerification/{token}")
            return passed or JsonResponse({"status": "not_found", "companyId": None, "customerId": None, "amount": None})
        data = _body(request)
        return JsonResponse(service.confirm(record, _text(data, "transactionId"), _rial(_find(data, "amount")) or 0))


class CheckTokenView(HubView):
    def get(self, request, token: str):
        record = _record(token)
        if not record:
            return _pass_to_old_hub(request, f"/CheckToken/{token}") or HttpResponse(status=404)
        return JsonResponse({"token": record.token, "gateway": record.gateway, "status": record.state,
                             "amount": record.amount, "transactionId": record.transaction_id or None})


class SnappHubTokenView(ServerView):
    def post(self, request, company_id: str):
        if not snapppay.configured():
            return HttpResponse(status=404)  # the old site: "SnappPay is not set up"
        return JsonResponse({"access_token": signing.dumps(company_id, salt=HUB_TOKEN_SALT), "token_type": "Bearer",
                             "expires_in": HUB_TOKEN_SECONDS, "scope": "online-merchant"})


class SnappEligibleView(SnappApiView):
    def post(self, request):
        amount = _rial(request.query_params.get("amount")) or 0
        return self.dispatch_snapp(lambda: snapppay.eligible(amount))


class SnappCancelView(SnappApiView):
    def post(self, request):
        return self.dispatch_snapp(lambda: snapppay.cancel(_text(_body(request), "paymentToken")))


class SnappUpdateView(SnappApiView):
    def post(self, request):
        data = _body(request)
        return self.dispatch_snapp(lambda: snapppay.update({
            "amount": _rial(_find(data, "amount")) or 0, "discountAmount": _rial(_find(data, "discountAmount")) or 0,
            "externalSourceAmount": _rial(_find(data, "externalSourceAmount")) or 0,
            "paymentToken": _text(data, "paymentToken"), "cartList": _find(data, "cartList") or [],
        }))


class SnappStatusView(SnappApiView):
    def post(self, request):
        return self.dispatch_snapp(lambda: snapppay.status(_text(_body(request), "paymentToken")))
