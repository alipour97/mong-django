"""Receipt submission and review for manual bank transfers."""
from __future__ import annotations

import logging
import threading
from io import BytesIO

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError
from rest_framework.parsers import MultiPartParser

from apps import smsir
from apps.erp.connector import Refused
from apps.website.models import CARD_TRANSFER, BankGateway, CardTransferReceipt, Customer, Invoice, InvoicePayment

from .account import CustomerView, answer
from .payments import _hold_voucher, _mark_paid, _out_of_stock, _release_voucher

logger = logging.getLogger(__name__)
S = Invoice.State
MAX_RECEIPT_BYTES = 4 * 1024 * 1024
PENDING_MESSAGE = "رسید کارت‌به‌کارت ثبت شد و در انتظار بررسی است."


def _receipt_image(file) -> bytes:
    if not file or file.size > MAX_RECEIPT_BYTES:
        raise ValueError("یک تصویر JPG، PNG یا WebP تا ۴ مگابایت انتخاب کنید.")
    try:
        with Image.open(file, formats=["JPEG", "PNG", "WEBP"]) as source:
            if source.width * source.height > 16_000_000 or getattr(source, "is_animated", False):
                raise ValueError
            preview = ImageOps.exif_transpose(source)
            preview.thumbnail((2400, 2400))
            output = BytesIO()
            preview.convert("RGB").save(output, format="JPEG", quality=90)
            return output.getvalue()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError) as exc:
        raise ValueError("تصویر رسید معتبر نیست. یک عکس JPG، PNG یا WebP انتخاب کنید.") from exc


def _notify(template_id: int, invoice: Invoice) -> None:
    if not template_id:
        return
    mobile = invoice.customer.cellphone
    number = invoice.number or str(invoice.pk)

    def send():
        try:
            smsir.send_verify(mobile, template_id, {settings.SMSIR_CARD_TRANSFER_PARAM: number})
        except Exception:
            logger.exception("card transfer SMS failed for invoice %s", invoice.pk)

    transaction.on_commit(lambda: threading.Thread(target=send, daemon=True).start(), robust=True)


class SubmitCardTransferView(CustomerView):
    parser_classes = [MultiPartParser]

    @transaction.atomic
    def post(self, request, invoice_id: int):
        Customer.objects.select_for_update().get(pk=request.user.pk)
        invoice = (Invoice.objects.select_for_update()
                   .filter(pk=invoice_id, customer=request.user, is_deleted=False).first())
        if invoice is None:
            return answer(None, 404, "فاکتور یافت نشد.")
        result = {"invoiceNumber": invoice.number or str(invoice.pk)}
        if invoice.state == S.SUSPENDED and invoice.payments.filter(gateway=CARD_TRANSFER, verified_at__isnull=True).exists():
            return answer(result, message=PENDING_MESSAGE)
        if invoice.state != S.PRE_INVOICE or invoice.payable_amount <= 0:
            return answer(None, 409, "امکان ثبت رسید برای این فاکتور وجود ندارد.")
        gateway_id = request.data.get("gatewayId", "")
        if not str(gateway_id).isascii() or not str(gateway_id).isdecimal() or len(str(gateway_id)) > 18:
            return answer(None, 400, "روش پرداخت کارت‌به‌کارت معتبر نیست.")
        gateway = (BankGateway.objects.filter(pk=gateway_id, bank__key=CARD_TRANSFER, is_deleted=False)
                   .exclude(card_number="").first())
        if not gateway:
            return answer(None, 409, "روش پرداخت کارت‌به‌کارت فعال نیست.")
        if str(request.data.get("amount")) != str(invoice.payable_amount):
            return answer(None, 409, "مبلغ فاکتور تغییر کرده است. مبلغ پرداخت‌شده را با پشتیبانی پیگیری کنید.")
        try:
            image = _receipt_image(request.FILES.get("receipt"))
            _hold_voucher(invoice)
        except ValueError as exc:
            return answer(None, 400, str(exc))
        except Refused as exc:
            return answer(None, 409, str(exc))
        payment = InvoicePayment.objects.create(
            invoice=invoice, gateway=CARD_TRANSFER, amount=invoice.payable_amount,
            reference=f"card-transfer-{invoice.pk}",
        )
        CardTransferReceipt.objects.create(payment=payment, image=image)
        invoice.state = S.SUSPENDED
        invoice.save(update_fields=["state", "last_modified"])
        _notify(settings.SMSIR_CARD_TRANSFER_RECEIVED_TEMPLATE_ID, invoice)
        return answer(result, message=PENDING_MESSAGE)


@transaction.atomic
def review(payment_id: int, approved: bool, reviewer) -> None:
    customer_id = (InvoicePayment.objects.filter(pk=payment_id, gateway=CARD_TRANSFER, transfer_receipt__isnull=False)
                   .values_list("invoice__customer_id", flat=True).first())
    if customer_id is None:
        raise InvoicePayment.DoesNotExist
    Customer.objects.select_for_update().get(pk=customer_id)
    payment = InvoicePayment.objects.get(pk=payment_id)
    invoice = Invoice.objects.select_for_update().get(pk=payment.invoice_id)
    if payment.verified_at:
        if payment.is_success == approved:
            return
        raise Refused("برای این رسید قبلاً تصمیم ثبت شده است.")
    if invoice.state != S.SUSPENDED or invoice.is_deleted:
        raise Refused("این فاکتور دیگر در انتظار بررسی رسید نیست.")
    if approved:
        if payment.amount != invoice.payable_amount:
            raise Refused("مبلغ فاکتور با مبلغ ثبت‌شده برای رسید مطابقت ندارد.")
        if _out_of_stock(invoice):
            raise Refused("موجودی کالاهای این سفارش کافی نیست.")
        _hold_voucher(invoice)
    payment.is_success = approved
    payment.verified_at = timezone.now()
    payment.error_message = "" if approved else "رسید کارت‌به‌کارت رد شد."
    payment.save(update_fields=["is_success", "verified_at", "error_message"])
    CardTransferReceipt.objects.filter(payment=payment).update(reviewed_by=reviewer)
    if approved:
        _mark_paid(invoice)
        _notify(settings.SMSIR_CARD_TRANSFER_APPROVED_TEMPLATE_ID, invoice)
    else:
        invoice.state = S.CANCELLED
        invoice.save(update_fields=["state", "last_modified"])
        _release_voucher(invoice)
