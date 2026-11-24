"""
The payment flow of the hub, gateway by gateway. views.py exposes it over HTTP
for the old site; apps.storefront.payments calls it directly for the new one.

    create          -> a record with its token and the caller's two return addresses
    start_zarinpal  -> Zarinpal session, the customer goes to its page
    start_snapp     -> SnappPay payment token, the customer goes to its page
    zarinpal_return, snapp_return  <- the gateway sends the customer back
                       (SnappPay is verified here; the customer then goes to the caller's address)
    confirm         -> Zarinpal verify / SnappPay settle, answered "ok" only once
    reconcile       -> runs from cron: asks about what stayed unclear and refunds what was never confirmed

SnappPay follows the API document and the "Action" column of its error list:
verify and settle fall back on Get Payment Status, 1053 is retried after a few
seconds, and what cannot be decided now waits (UNKNOWN, asked again after 40
minutes) or goes to a person (REVIEW).
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from datetime import timedelta
from urllib.parse import quote

import requests
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from . import mellat, snapppay, zarinpal
from .models import PayRecord

logger = logging.getLogger(__name__)

S = PayRecord.State
Source = PayRecord.Source
ZARINPAL, SNAPPPAY = "zarinpal", "snapppay"
MELLAT = "mellat"
GATEWAYS = (ZARINPAL, SNAPPPAY, MELLAT)

RETRY_DELAY = 3  # seconds, before asking SnappPay again (GENERAL, ONGOING_PAYMENT_TRANSITION_PROCESS)
CONFIRM_WAIT = 40  # seconds a second confirm waits for the first one
ZARINPAL_SESSION = timedelta(minutes=10)  # the same session serves a double click
STALE_STEP = timedelta(minutes=5)  # a process died in the middle of a step
UNCONFIRMED_AFTER = timedelta(minutes=20)  # verified, but the caller never confirmed
RECHECK_AFTER = timedelta(minutes=40)  # error list: ask again after at least 40 minutes
ABANDONED_AFTER = timedelta(hours=2)  # the customer never came back from the gateway
MAX_RESOLVE_TRIES = 3

# Error list: "the payment token is wrong / not ours": only a person can follow these up.
MANUAL_CODES = {100, 1005, 1007, 1048}
RETRY_CODES = {1000, 1053}

CONNECTION_FAILED = "اتصال به درگاه پرداخت برقرار نشد. لطفا دوباره تلاش کنید."
CHECKING = "وضعیت پرداخت شما در حال بررسی است. اگر مبلغی کسر شده باشد، به‌صورت خودکار برمی‌گردد."
LINK_USED = "این لینک پرداخت قبلاً استفاده شده است. لطفاً از سبد خرید دوباره اقدام کنید."
BAD_LINK = "لینک پرداخت نامعتبر است."
NOT_CONFIRMED = "پرداخت تایید شد اما سفارش ثبت نشد؛ مبلغ برگشت داده شد."


class Refused(Exception):
    """The request cannot go on; the message can be shown to the customer."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message, self.status = message, status


def note(record: PayRecord, event: str, **detail) -> None:
    logger.info("payhub %s #%s %s %s", record.gateway, record.pk, event, detail)
    record.events = [*record.events, {"at": timezone.now().isoformat(timespec="seconds"), "event": event, **detail}][-60:]


def _set(record: PayRecord, state: str, error: str | None = None) -> None:
    record.state = state
    if error is not None:
        record.error = error
    record.save()


def _claim(record: PayRecord, sources: tuple, target: str) -> bool:
    """Moves the record only if it is still in one of sources: of two parallel requests, one wins (on any database)."""
    won = PayRecord.objects.filter(pk=record.pk, state__in=sources).update(state=target, updated=timezone.now())
    record.refresh_from_db()
    return bool(won)


def with_query(url: str, **values) -> str:
    for key, value in values.items():
        if value:
            url += ("&" if "?" in url else "?") + f"{key}={quote(str(value), safe='')}"
    return url


# The old site's PaymentVerification reads these names from the redirect.
def success_redirect(record: PayRecord) -> str:
    if record.gateway == SNAPPPAY:
        return with_query(record.success_callback, trackingToken=record.token, snappTrackingToken=record.payment_token,
                          paymentTransactionId=record.gateway_transaction_id)
    return with_query(record.success_callback, trackingToken=record.token, paymentTransactionId=record.authority)


def failed_redirect(record: PayRecord, error: str) -> str:
    if record.gateway == SNAPPPAY:
        return with_query(record.failed_callback, trackingToken=record.token, snappTrackingToken=record.payment_token,
                          paymentTransactionId=record.gateway_transaction_id, errorMessage=error)
    return with_query(record.failed_callback, trackingToken=record.token, paymentTransactionId=record.authority,
                      errorMessage=error)


def create(*, gateway: str, amount: int, success: str, failed: str, source: str = Source.LEGACY, cell_phone: str = "",
           customer_key: str = "", company_id: int = 0, merchant_id: str = "") -> PayRecord:
    record = PayRecord.objects.create(
        token=uuid.uuid4().hex, source=source, gateway=gateway, amount=amount, success_callback=success, failed_callback=failed,
        cell_phone=cell_phone, customer_key=customer_key, company_id=company_id, merchant_id=merchant_id,
        mellat_sandbox=settings.MELLAT_SANDBOX)
    note(record, "created", amount=amount)
    record.save()
    return record


# -----------------------------------------------------------------------------
# Zarinpal
# -----------------------------------------------------------------------------
def start_zarinpal(record: PayRecord, transaction_id: str, pay_amount: int) -> str:
    """Opens the session; returns the Zarinpal page. Refused with state FAILED if Zarinpal said no."""
    if record.gateway != ZARINPAL:
        raise Refused(BAD_LINK, 404)
    if pay_amount != record.amount:
        raise Refused("مبلغ پرداخت با فاکتور مطابقت ندارد.")
    if (record.state == S.REDIRECTED and record.authority and record.transaction_id == transaction_id
            and timezone.now() - record.updated < ZARINPAL_SESSION):
        return zarinpal.start_url(record.authority)
    if not _claim(record, (S.CREATED, S.REDIRECTED), S.STARTING):
        raise Refused(LINK_USED, 409)

    record.transaction_id = transaction_id
    if record.amount > zarinpal.MAX_RIAL:
        _set(record, S.FAILED, zarinpal.ERRORS[-41])
        raise Refused(zarinpal.ERRORS[-41])
    result = zarinpal.request(record.merchant_id, record.amount, f"پرداخت فاکتور شماره {transaction_id} - فروشگاه مانگ",
                              f"{settings.PAYHUB_PUBLIC_URL}/zarinpal/callback/{record.token}", record.cell_phone, transaction_id)
    note(record, "request", code=result.code, authority=result.authority, raw=result.raw[:500])
    if not result.ok or not result.authority:
        _set(record, S.FAILED, f"{result.code}: {result.message}")
        raise Refused(result.message if result.code in zarinpal.CUSTOMER_FACING else CONNECTION_FAILED)
    record.authority = result.authority
    _set(record, S.REDIRECTED)
    return zarinpal.start_url(result.authority)


def zarinpal_return(record: PayRecord, authority: str, status: str) -> str:
    """?Authority=&Status=OK|NOK. Verified later, in confirm."""
    if record.state in (S.RETURNED, S.CONFIRMING, S.CONSUMED):
        return success_redirect(record)
    if not record.authority or record.authority != authority:
        raise Refused("اطلاعات بازگشتی از درگاه معتبر نیست.")
    if status.upper() != "OK":
        error = record.error or "پرداخت توسط کاربر لغو شد یا ناموفق بود."
        if record.state == S.REDIRECTED:
            _set(record, S.FAILED, error)
        return failed_redirect(record, error)
    if not _claim(record, (S.REDIRECTED,), S.RETURNED):
        return failed_redirect(record, record.error or "پرداخت ناموفق بود.")
    note(record, "returned")
    record.save()
    return success_redirect(record)


# -----------------------------------------------------------------------------
# Behpardakht Mellat
# -----------------------------------------------------------------------------
def mellat_page_url(record: PayRecord) -> str:
    return f"{settings.PAYHUB_PUBLIC_URL}/mellat/pay/{record.token}"


def start_mellat(record: PayRecord, transaction_id: str, pay_amount: int) -> str:
    if record.gateway != MELLAT:
        raise Refused(BAD_LINK, 404)
    if pay_amount != record.amount or not mellat.positive_long(pay_amount):
        raise Refused("مبلغ پرداخت با فاکتور مطابقت ندارد.")
    if record.state == S.REDIRECTED and record.authority and record.transaction_id == transaction_id:
        return mellat_page_url(record)
    if not _claim(record, (S.CREATED,), S.STARTING):
        raise Refused(LINK_USED, 409)
    record.transaction_id = transaction_id
    # One bank order per payment attempt, never the invoice id (which can be retried).
    record.gateway_transaction_id = str(record.pk)
    values = mellat.config()
    record.merchant_id = record.merchant_id or values["terminal"]
    record.mellat_gateway = values["gateway"]
    record.mellat_sandbox = values["sandbox"]
    record.save()
    if not mellat.positive_long(record.merchant_id) or not values["username"] or not values["password"]:
        _set(record, S.FAILED, "درگاه به‌پرداخت ملت تنظیم نشده است.")
        raise Refused(record.error)
    result = mellat.request(record.merchant_id, record.mellat_sandbox, record.gateway_transaction_id, record.amount,
                            f"{settings.PAYHUB_PUBLIC_URL}/mellat/callback/{record.token}",
                            f"پرداخت فاکتور شماره {transaction_id} - فروشگاه مانگ",
                            credentials=(values["username"], values["password"]))
    note(record, "mellat_request", code=result.code, sandbox=record.mellat_sandbox)
    if result.code != 0 or not result.authority:
        _set(record, S.FAILED, result.message)
        raise Refused(CONNECTION_FAILED, 502)
    record.authority = result.authority
    _set(record, S.REDIRECTED)
    return mellat_page_url(record)


def mellat_return(record: PayRecord, fields: dict) -> str | None:
    # IPG 1.38, table 13: validate both identifiers before ANY verify, even on a replay.
    if (not record.authority or fields.get("RefId") != record.authority
            or str(fields.get("SaleOrderId") or "") != record.gateway_transaction_id):
        raise Refused("اطلاعات بازگشتی از درگاه ملت معتبر نیست.")
    code = str(fields.get("ResCode", ""))
    reference = str(fields.get("SaleReferenceId") or "")
    if not code.isascii() or not code.isdigit() or len(code) > 4:
        raise Refused("کد وضعیت بازگشتی معتبر نیست.")
    if code == "0" and not mellat.positive_long(reference):
        raise Refused("کد مرجع تراکنش معتبر نیست.")
    if record.ref_id and record.ref_id != reference:
        raise Refused("کد مرجع تراکنش مطابقت ندارد.")
    if record.state in (S.RETURNED, S.CONSUMED):
        return success_redirect(record)
    if record.state in (S.VERIFYING, S.CONFIRMING):
        return None
    if not _claim(record, (S.REDIRECTED,), S.VERIFYING):
        return failed_redirect(record, record.error or "پرداخت ناموفق بود.")
    note(record, "mellat_callback", code=int(code))
    if code != "0":
        _set(record, S.FAILED, mellat.Result(int(code)).message)
        return failed_redirect(record, record.error)
    record.ref_id = reference
    # Keep only masked PANs, never a full card number supplied in an untrusted POST.
    pan = str(fields.get("CardHolderPan") or "")
    if re.fullmatch(r"[0-9]{6}[*xX•]{3,9}[0-9]{4}", pan):
        record.card_pan = pan
    _set(record, S.RETURNED)
    return success_redirect(record)


def _mellat_call(record: PayRecord, method: str) -> mellat.Result:
    result = mellat.transaction(method, record)
    note(record, "mellat_operation", method=method, code=result.code)
    record.save()  # persist each step before issuing another bank request
    return result


def _mellat_reverse(record: PayRecord, reason: str) -> None:
    result = _mellat_call(record, "bpReversalRequest")
    state = (S.REVERTED if result.code in (0, 48) else S.REVIEW if result.code == 45 else S.UNKNOWN)
    _set(record, state, reason)


def _mellat_confirm(record: PayRecord) -> str:
    result = _mellat_call(record, "bpVerifyRequest")
    if result.code not in (0, 43, 45, 48):
        result = _mellat_call(record, "bpVerifyRequest")  # official document: retry non-successful verify
    if result.code not in (0, 43, 45, 48):
        result = _mellat_call(record, "bpInquiryRequest")
    if result.code == 45:
        return S.CONSUMED
    if result.code == 48:
        return S.REVERTED
    if result.code not in (0, 43):
        _mellat_reverse(record, CHECKING)
        return record.state
    result = _mellat_call(record, "bpSettleRequest")
    if result.code in (0, 45):
        return S.CONSUMED
    if result.code == 48:
        return S.REVERTED
    # A lost settle response can mean it was settled. A retry is idempotent;
    # never report success on a timeout or reverse blindly after settlement.
    status = _mellat_call(record, "bpInquiryRequest")
    if status.code == 45:
        return S.CONSUMED
    return S.REVERTED if status.code == 48 else S.RETURNED


def _mellat_resolve(record: PayRecord, reason: str = NOT_CONFIRMED) -> None:
    if not record.ref_id:
        _set(record, S.FAILED, reason)  # no verify: the bank automatically reverses after 20 minutes
        return
    result = _mellat_call(record, "bpInquiryRequest")
    if result.code == 45:
        _set(record, S.REVIEW, "ملت تراکنش را تسویه کرده ولی سفارش ثبت نشده است.")
        return
    if result.code == 48:
        _set(record, S.REVERTED, reason)
        return
    # The document requires verify before reversal (maximum 3 hours after verify).
    result = _mellat_call(record, "bpVerifyRequest")
    if result.code == 45:
        _set(record, S.REVIEW, reason)
    elif result.code == 48:
        _set(record, S.REVERTED, reason)
    else:
        _mellat_reverse(record, reason)
        tries = sum(e.get("event") == "mellat_operation" and e.get("method") == "bpReversalRequest" for e in record.events)
        if record.state == S.UNKNOWN and tries >= MAX_RESOLVE_TRIES:
            _set(record, S.REVIEW, CHECKING)


# -----------------------------------------------------------------------------
# SnappPay
# -----------------------------------------------------------------------------
def start_snapp(record: PayRecord, transaction_id: str, pay_amount: int, order: dict) -> dict:
    """
    order: amount, discountAmount, externalSourceAmount, mobile, cartList. Every attempt gets its own 5-10 digit
    transactionId, and the returnURL is always ours (the whitelisted address), whatever the caller sent.
    """
    if record.gateway != SNAPPPAY:
        raise Refused(BAD_LINK, 404)
    if pay_amount != record.amount or order.get("amount") != record.amount:
        note(record, "token_rejected", amount=order.get("amount"), pay_amount=pay_amount)
        record.save()
        raise Refused("مبلغ پرداخت با فاکتور مطابقت ندارد.")
    if record.state == S.REDIRECTED and record.transaction_id == transaction_id and record.payment_token:
        return {"paymentToken": record.payment_token, "paymentPageUrl": record.payment_page_url,
                "transactionId": record.gateway_transaction_id}
    if not _claim(record, (S.CREATED,), S.STARTING):
        raise Refused(LINK_USED, 409)

    record.transaction_id = transaction_id
    record.gateway_transaction_id = str(settings.SNAPPAY_TRANSACTION_ID_START + record.pk)
    mobile = snapppay.format_mobile(order.get("mobile") or record.cell_phone)
    if not mobile:
        _set(record, S.FAILED, "شماره موبایل معتبر نیست.")
        raise Refused(record.error)
    body = {
        "amount": record.amount, "discountAmount": order.get("discountAmount", 0),
        "externalSourceAmount": order.get("externalSourceAmount", 0), "mobile": mobile,
        "returnURL": f"{settings.PAYHUB_SNAPP_RETURN_URL}/api/SnappPay/CallBack/{record.pk}/{record.token}",
        "transactionId": record.gateway_transaction_id, "cartList": order.get("cartList") or [],
    }
    reply = snapppay.payment_token(body)
    if reply.code == 1000:  # GENERAL: may be retried, with a pause
        time.sleep(RETRY_DELAY)
        reply = snapppay.payment_token(body)
    note(record, "token", tx=record.gateway_transaction_id, reply=reply.brief())
    payment_token, page_url = reply.value("paymentToken"), reply.value("paymentPageUrl")
    if not reply.ok or not payment_token or not page_url:
        if (reply.http == 403 or (not reply.ok and getattr(reply, "http", 0) in (403, 0))) and getattr(settings, "PAYHUB_OLD_HUB_URL", ""):
            logger.warning("Direct SnappPay returned %s. Attempting fallback to %s", reply.http, settings.PAYHUB_OLD_HUB_URL)
            relayed = _start_snapp_fallback(record, transaction_id, order, mobile)
            if relayed:
                return relayed
        _set(record, S.FAILED, reply.message)
        raise Refused(CONNECTION_FAILED, 502)
    record.payment_token, record.payment_page_url = str(payment_token), str(page_url)
    _set(record, S.REDIRECTED)
    return {"paymentToken": record.payment_token, "paymentPageUrl": record.payment_page_url,
            "transactionId": record.gateway_transaction_id}


def _start_snapp_fallback(record: PayRecord, transaction_id: str, order: dict, mobile: str) -> dict | None:
    hub_url = getattr(settings, "PAYHUB_OLD_HUB_URL", "").rstrip("/")
    if not hub_url:
        return None
    try:
        gen_payload = {
            "gateway": "snapppay",
            "payAmount": record.amount,
            "successCallBack": record.success_callback,
            "failedCallBack": record.failed_callback,
            "cellPhone": mobile,
            "customerKey": str(record.customer_key or ""),
            "companyId": 0,
        }
        res = requests.post(f"{hub_url}/GenerateToken", json=gen_payload, timeout=15)
        if res.status_code != 200:
            logger.warning("SnappPay fallback GenerateToken failed: %s %s", res.status_code, res.text)
            return None
        gen_data = res.json()
        hub_token = gen_data.get("token")
        if not hub_token:
            return None

        tok_payload = {
            "amount": record.amount,
            "discountAmount": order.get("discountAmount", 0),
            "externalSourceAmount": order.get("externalSourceAmount", 0),
            "mobile": mobile,
            "cartList": order.get("cartList") or [],
        }
        tok_res = requests.post(
            f"{hub_url}/GetPaymentToken/{hub_token}/{record.gateway_transaction_id}/{record.amount}",
            json=tok_payload,
            timeout=25,
        )
        if tok_res.status_code != 200:
            logger.warning("SnappPay fallback GetPaymentToken failed: %s %s", tok_res.status_code, tok_res.text)
            return None
        tok_data = tok_res.json()
        payment_token = tok_data.get("paymentToken")
        page_url = tok_data.get("paymentPageUrl")
        if not payment_token or not page_url:
            return None

        record.payment_token = str(payment_token)
        record.payment_page_url = str(page_url)
        record.ref_id = str(hub_token)
        note(record, "snapp_fallback", hub=hub_url, hub_token=hub_token, reply="http=200 ok=True")
        _set(record, S.REDIRECTED)
        return {
            "paymentToken": record.payment_token,
            "paymentPageUrl": record.payment_page_url,
            "transactionId": record.gateway_transaction_id,
        }
    except Exception as exc:
        logger.exception("SnappPay fallback exception: %s", exc)
        return None


def _settle_fallback(record: PayRecord, transaction_id: str, amount: int) -> str:
    hub_url = getattr(settings, "PAYHUB_OLD_HUB_URL", "").rstrip("/")
    hub_token = record.ref_id
    if not hub_url or not hub_token:
        return S.FAILED
    try:
        res = requests.post(
            f"{hub_url}/PaymentVerification/{hub_token}",
            json={"transactionId": transaction_id, "amount": amount},
            timeout=45,
        )
        note(record, "settle_fallback", status=res.status_code, body=res.text[:200])
        if res.status_code == 200:
            data = res.json()
            if data.get("status") in ("ok", "duplicate"):
                return S.CONSUMED
            if data.get("status") == "reverted":
                return S.REVERTED
        return S.FAILED
    except Exception as exc:
        logger.exception("SnappPay fallback settle exception: %s", exc)
        return S.UNKNOWN


def _delivery_problem(record: PayRecord) -> str:
    """Site orders only: why this order can no longer be delivered. The old site checks its own."""
    if record.source != Source.SITE:
        return ""
    from apps.storefront.payments import delivery_problem

    return delivery_problem(record)


def _again_if_busy(record: PayRecord, call, reply: snapppay.Reply) -> snapppay.Reply:
    if reply.ok or reply.code not in RETRY_CODES:
        return reply
    time.sleep(RETRY_DELAY)
    reply = call(record.payment_token)
    note(record, "retried", reply=reply.brief())
    return reply


def _verify(record: PayRecord) -> str:
    """Returns the state the record should move to."""
    reply = _again_if_busy(record, snapppay.verify, snapppay.verify(record.payment_token))
    note(record, "verify", reply=reply.brief())
    if reply.ok:
        return S.RETURNED
    if reply.code == 1011:
        # No transaction-status: the payment never reached the bank for its first installment.
        status = reply.transaction_status
        return S.RETURNED if status in ("VERIFY", "SETTLE") else S.FAILED if status in (None, "REVERT") else S.REVIEW
    if reply.code in MANUAL_CODES:
        return S.REVIEW

    status = snapppay.status(record.payment_token)
    note(record, "status", reply=status.brief())
    if status.status in ("VERIFY", "SETTLE"):
        return S.RETURNED
    if status.status == "PENDING":
        reply = snapppay.verify(record.payment_token)
        note(record, "verify_again", reply=reply.brief())
        return S.RETURNED if reply.ok else S.UNKNOWN
    return S.UNKNOWN if status.status is None else S.FAILED


def _settle(record: PayRecord) -> str:
    """Returns CONSUMED when the purchase is final, else the state the record should move to."""
    token = record.payment_token
    reply = snapppay.settle(token)
    note(record, "settle", reply=reply.brief())
    if reply.ok:
        return S.CONSUMED
    if reply.code == 1011:
        status = reply.transaction_status
        if status == "SETTLE":
            return S.CONSUMED
        if status == "REVERT":
            return S.REVERTED
        if status == "PENDING":
            if _verify(record) != S.RETURNED:
                return S.RETURNED
        elif status != "VERIFY":
            return S.FAILED if status is None else S.REVIEW
    elif reply.code in MANUAL_CODES:
        return S.REVIEW

    status = snapppay.status(token)
    note(record, "status", reply=status.brief())
    if status.status == "SETTLE":
        return S.CONSUMED
    if status.status in ("REVERT", "CANCEL"):
        return S.REVERTED
    if status.status != "VERIFY":
        return S.RETURNED
    again = snapppay.settle(token)
    note(record, "settle_again", reply=again.brief())
    # Still VERIFY and SnappPay answers 1000 again: the error list (settle, 1000) says ignore it, they settle it
    # themselves at night. No answer at all is not that answer: reconcile asks again and refunds or hands it on.
    return S.CONSUMED if again.ok or again.code == 1000 else S.RETURNED


def _revert(record: PayRecord, reason: str) -> None:
    reply = _again_if_busy(record, snapppay.revert, snapppay.revert(record.payment_token))
    note(record, "revert", reason=reason, reply=reply.brief())
    if reply.ok:
        state = S.REVERTED
    elif reply.code == 1011:
        status = reply.transaction_status
        state = (S.REVERTED if status in ("REVERT", "CANCEL") else S.FAILED if status is None
                 else S.UNKNOWN if status == "REGISTERED" else S.REVIEW)
    elif reply.code in MANUAL_CODES:
        state = S.REVIEW
    else:
        status = snapppay.status(record.payment_token)
        note(record, "status", reply=status.brief())
        state = (S.REVERTED if status.status in ("REVERT", "CANCEL") else S.REVIEW if status.status == "SETTLE" else S.UNKNOWN)
    _set(record, state, reason)


def snapp_return(record: PayRecord, fields: dict) -> str | None:
    """The returnURL: verify exactly once, however many times it is called. None: another request is on it, wait."""
    if record.state in (S.RETURNED, S.CONFIRMING, S.CONSUMED):
        return success_redirect(record)
    if record.state == S.VERIFYING:
        return None
    if record.state != S.REDIRECTED or not record.payment_token:
        return failed_redirect(record, record.error or "پرداخت ناموفق بود.")
    if str(fields.get("transactionId") or "") != record.gateway_transaction_id:
        raise Refused("اطلاعات بازگشتی از اسنپ‌پی معتبر نیست.")
    if not _claim(record, (S.REDIRECTED,), S.VERIFYING):
        return None

    state_field = str(fields.get("state") or "").upper()
    note(record, "callback", state=state_field, amount=str(fields.get("amount") or ""))
    if state_field != "OK":
        error = "پرداخت اسنپ‌پی انجام نشد یا توسط کاربر لغو شد."
        reply = snapppay.revert(record.payment_token)  # best effort: the payment may not have been taken at all
        note(record, "revert_on_failed", reply=reply.brief())
        _set(record, S.FAILED, error)
        return failed_redirect(record, error)

    problem = _delivery_problem(record)
    if problem:
        _revert(record, problem)
        return failed_redirect(record, problem)

    state = _verify(record)
    if state == S.RETURNED:
        _set(record, state)
        return success_redirect(record)
    error = CHECKING if state in (S.UNKNOWN, S.REVIEW) else "تایید پرداخت اسنپ‌پی انجام نشد."
    _set(record, state, error)
    return failed_redirect(record, error)


# -----------------------------------------------------------------------------
# Confirming: the caller records the order only after this answered "ok"
# -----------------------------------------------------------------------------
def confirm(record: PayRecord, transaction_id: str, amount: int) -> dict:
    """The token must belong to this very invoice and amount: otherwise a paid token could mark other invoices paid."""
    def answer(status: str, customer: int | None = None) -> dict:
        if status != "ok":
            note(record, "confirm_rejected", status=status, state=record.state, invoice=transaction_id, amount=amount)
            record.save()
        return {"status": status, "companyId": record.company_id, "customerId": customer, "amount": record.amount}

    if not record.transaction_id or transaction_id != record.transaction_id or amount != record.amount:
        return answer("mismatch")
    for _ in range(CONFIRM_WAIT):
        if record.state != S.CONFIRMING:
            break
        time.sleep(1)
        record.refresh_from_db()
    if record.state == S.CONSUMED:
        return answer("duplicate")
    if not _claim(record, (S.RETURNED,), S.CONFIRMING):
        return answer("duplicate" if record.state == S.CONSUMED else "not_paid")

    if record.gateway == SNAPPPAY:
        if any(e.get("event") == "snapp_fallback" for e in record.events) and getattr(settings, "PAYHUB_OLD_HUB_URL", ""):
            state = _settle_fallback(record, transaction_id, amount)
        else:
            state = _settle(record)
        if state != S.CONSUMED:
            _set(record, state)  # RETURNED: the job in reconcile gives the money back
            return answer("failed")
    elif record.gateway == MELLAT:
        state = _mellat_confirm(record)
        if state != S.CONSUMED:
            _set(record, state, CHECKING)
            return answer("failed")
    else:
        result = zarinpal.verify(record.merchant_id, record.amount, record.authority)
        note(record, "verify", code=result.code, ref_id=result.ref_id, raw=result.raw[:500])
        if not result.ok and not result.already_verified:
            # When Zarinpal could not be reached the state stays RETURNED, so a retry can still verify.
            reachable = result.code > zarinpal.NO_ANSWER_CODE
            _set(record, S.FAILED if reachable else S.RETURNED, f"{result.code}: {result.message}")
            return answer("failed")
        record.ref_id, record.card_pan = result.ref_id or record.ref_id, result.card_pan or record.card_pan

    _set(record, S.CONSUMED, "")
    return answer("ok", int(record.customer_key) if record.customer_key.isdigit() else None)


def abandon(record: PayRecord, reason: str) -> None:
    """The caller cannot deliver this order after all: a verified SnappPay payment is reverted, Zarinpal is simply never verified."""
    if not _claim(record, (S.RETURNED,), S.CONFIRMING):
        return
    if record.gateway == SNAPPPAY:
        _revert(record, reason)
    elif record.gateway == MELLAT:
        _mellat_resolve(record, reason)
    else:
        _set(record, S.FAILED, reason)


# -----------------------------------------------------------------------------
# After the sale (the panel). Both are final: the panel confirms with the admin first.
# -----------------------------------------------------------------------------
def _when_settled(token: str, call, *args) -> snapppay.Reply:
    """Cancel and update need a settled payment. One still in VERIFY is settled first, as the error list says."""
    reply = call(*args)
    if reply.code == 1053:
        time.sleep(RETRY_DELAY)
        reply = call(*args)
    if reply.code == 1011 and reply.transaction_status == "VERIFY" and snapppay.settle(token).ok:
        reply = call(*args)
    return reply


def cancel(token: str) -> tuple[bool, str]:
    reply = _when_settled(token, snapppay.cancel, token)
    logger.info("payhub snapppay cancel %s: %s", token, reply.brief())
    if reply.ok or (reply.code == 1011 and reply.transaction_status in ("CANCEL", "REVERT")):
        return True, ""
    return False, reply.message


def update(token: str, order: dict) -> tuple[bool, str]:
    body = {key: order[key] for key in ("amount", "discountAmount", "externalSourceAmount", "cartList")}
    reply = _when_settled(token, snapppay.update, {**body, "paymentToken": token})
    logger.info("payhub snapppay update %s: %s", token, reply.brief())
    return (True, "") if reply.ok else (False, reply.message)


# -----------------------------------------------------------------------------
# Cron
# -----------------------------------------------------------------------------
def _resolve(record: PayRecord) -> None:
    """A SnappPay payment nobody confirmed: refund what can be refunded, and leave a settled one to a person."""
    status = snapppay.status(record.payment_token)
    note(record, "resolve", reply=status.brief())
    tries = sum(1 for event in record.events if event.get("event") == "resolve")
    if status.status in ("REVERT", "CANCEL"):
        _set(record, S.REVERTED)
    elif status.status == "SETTLE":
        _set(record, S.REVIEW, "اسنپ‌پی این تراکنش را تسویه کرده ولی سفارش ثبت نشده است.")
    elif status.status is None and tries >= MAX_RESOLVE_TRIES:
        _set(record, S.REVIEW, "استعلام اسنپ‌پی پاسخ نداد.")
    else:  # VERIFY, PENDING, or a second inquiry that failed too
        _revert(record, NOT_CONFIRMED)


def _due(now) -> Q:
    """The payments reconcile() has something to do with now."""
    return (Q(state__in=(S.VERIFYING, S.CONFIRMING), updated__lt=now - STALE_STEP)
            | Q(state__in=(S.CREATED, S.STARTING, S.REDIRECTED), updated__lt=now - ABANDONED_AFTER)
            | Q(state=S.RETURNED, updated__lt=now - UNCONFIRMED_AFTER)
            | Q(state=S.UNKNOWN, updated__lt=now - RECHECK_AFTER))


def unclear() -> int:
    """Payments whose end is not known yet (verifying, returned but not confirmed, unknown): the admin panel's count."""
    return PayRecord.objects.filter(state__in=(S.VERIFYING, S.CONFIRMING, S.RETURNED, S.UNKNOWN)).count()


def reconcile_if_due() -> int:
    """reconcile() when one of the payments is due, so the every-minute cron mostly asks one count."""
    return reconcile() if PayRecord.objects.filter(_due(timezone.now())).exists() else 0


def reconcile() -> int:
    """Returns how many payments were looked at."""
    now = timezone.now()
    records = PayRecord.objects
    count = 0

    for record in records.filter(state=S.VERIFYING, updated__lt=now - STALE_STEP):
        count += _claim(record, (S.VERIFYING,), S.UNKNOWN)
    for record in records.filter(state=S.CONFIRMING, updated__lt=now - STALE_STEP):
        count += _claim(record, (S.CONFIRMING,), S.RETURNED)
    for record in records.filter(state__in=(S.CREATED, S.STARTING, S.REDIRECTED), updated__lt=now - ABANDONED_AFTER):
        count += _claim(record, (S.CREATED, S.STARTING, S.REDIRECTED), S.FAILED)

    for record in records.filter(state=S.RETURNED, updated__lt=now - UNCONFIRMED_AFTER):
        if not _claim(record, (S.RETURNED,), S.CONFIRMING):
            continue
        count += 1
        if record.gateway == SNAPPPAY:
            _resolve(record)
        elif record.gateway == MELLAT:
            _mellat_resolve(record)
        else:
            _set(record, S.FAILED, NOT_CONFIRMED)  # never verified: Zarinpal refunds it by itself
    for record in records.filter(state=S.UNKNOWN, updated__lt=now - RECHECK_AFTER):
        if _claim(record, (S.UNKNOWN,), S.CONFIRMING):
            count += 1
            if record.gateway == MELLAT:
                _mellat_resolve(record)
            else:
                _resolve(record)
    return count
