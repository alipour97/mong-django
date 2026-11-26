"""Record browsing and checkout activity for the admin invoice page."""
import logging
from uuid import UUID

from django.db import DatabaseError, transaction
from django.utils import timezone

from apps.website.models import Invoice, StoreActivity, StoreVisitor

logger = logging.getLogger(__name__)


def browser_uuid(value):
    if not isinstance(value, str) or len(value) != 36:
        return None
    try:
        key = UUID(value)
    except ValueError:
        return None
    return key if key.version == 4 else None


def identify_visitor(value, customer):
    if key := browser_uuid(value):
        try:
            with transaction.atomic():
                visitor, _ = StoreVisitor.objects.get_or_create(browser_id=key)
                StoreVisitor.objects.filter(pk=visitor.pk, identified_at__isnull=True).update(
                    customer=customer, identified_at=timezone.now(),
                )
        except DatabaseError:
            logger.exception("Unable to link storefront activity on sign-in")


@transaction.atomic
def change_checkout_stage(invoices, stage):
    invoice = invoices.select_for_update().exclude(checkout_stage=stage).first()
    if invoice is None:
        return
    invoice.checkout_stage = stage
    invoice.status_changed_at = timezone.now()
    invoice.save(update_fields=["checkout_stage", "status_changed_at"])
    record_status(invoice, invoice.get_checkout_stage_display())


def record_status(invoice, label=None):
    StoreActivity.objects.create(
        invoice=invoice,
        kind=StoreActivity.Kind.STATUS,
        detail=str(label or invoice.get_state_display()),
        occurred_at=invoice.status_changed_at,
    )


def status_time(invoice):
    if invoice.status_changed_at:
        return invoice.status_changed_at
    if invoice.state == Invoice.State.SUCCESSFUL:
        return invoice.paid_at
    if invoice.state == Invoice.State.PRE_INVOICE and invoice.checkout_stage == Invoice.CheckoutStage.CART:
        return invoice.created
    return None
