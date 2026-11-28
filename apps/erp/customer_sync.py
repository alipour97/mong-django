"""Deliver customer accounts through the same legacy table as paid invoices."""
from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

from apps.website.models import Customer

from . import dadehfa_write

logger = logging.getLogger(__name__)
VALID_MOBILE = r"^09[0-9]{9}$"
BATCH_SIZE = 100


def eligible():
    return Customer.objects.filter(is_active=True, is_deleted=False, cellphone__regex=VALID_MOBILE)


def pending():
    return eligible().filter(erp_customer_pending_at__isnull=False).order_by("erp_customer_pending_at", "pk")


def send(customer: Customer) -> bool:
    queued = Customer.objects.filter(pk=customer.pk, erp_customer_pending_at=customer.erp_customer_pending_at)
    try:
        customer_id = dadehfa_write.push_customer(customer)
    except Exception:
        logger.exception("Dadehfa customer %s not sent", customer.pk)
        # Give newer accounts a turn if one account repeatedly fails.
        queued.update(erp_customer_pending_at=timezone.now())
        return False

    queued.update(erp_customer_id=customer_id, erp_customer_pending_at=None)
    return True


def run(log) -> list[str]:
    if settings.ERP_CONNECTOR != "dadehfa" or not settings.ERP_WRITES_ENABLED:
        return ["ارسال حساب مشتری به داده‌فا غیرفعال است"]
    sent = failed = 0
    for customer in pending()[:BATCH_SIZE]:
        if send(customer):
            sent += 1
        else:
            failed += 1
    log(f"Dadehfa customers: {sent} sent or already present, {failed} failed")
    lines = [f"{sent} حساب مشتری در دیتابیس آنلاین‌شاپ تأیید شد"]
    if failed:
        lines.append(f"ارسال {failed} حساب ناموفق بود و در صف ماند")
    return lines
