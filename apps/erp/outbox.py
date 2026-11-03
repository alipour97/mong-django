"""
Paid orders on their way to the sales software. An order waits here until the connector has
taken it, so a failure or a closed door loses nothing: the next run sends it again.
"""
from __future__ import annotations

import logging
import threading

from django.db import close_old_connections
from django.utils import timezone

from apps.website.models import Invoice

from .connector import Log, get_connector

logger = logging.getLogger(__name__)


def waiting():
    return Invoice.objects.filter(state=Invoice.State.SUCCESSFUL, is_deleted=False, erp_sent_at__isnull=True).order_by("id")


def send(invoice: Invoice) -> bool:
    try:
        get_connector().push(invoice)
    except Exception as exc:  # the order stays queued and the panel shows why
        logger.exception("invoice %s not sent", invoice.pk)
        Invoice.objects.filter(pk=invoice.pk).update(erp_error=str(exc)[:2000], last_modified=timezone.now())
        return False
    return True


def send_soon(invoice_id: int) -> None:
    """The customer's redirect must not wait on the software; the scheduled run is the safety net."""

    def run():
        close_old_connections()
        try:
            invoice = waiting().filter(pk=invoice_id).first()
            if invoice:
                send(invoice)
        finally:
            close_old_connections()

    threading.Thread(target=run, daemon=True).start()


def run(log: Log) -> None:
    connector = get_connector()
    sent = failed = 0
    for invoice in waiting():
        if send(invoice):
            sent += 1
        else:
            failed += 1
    connector.follow(log)
    log(f"outbox: {sent} handed over, {failed} failed")
