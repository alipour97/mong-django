"""
Paid invoices into DadehfaOnlineShop, the one way this project writes there. The row shapes
copy what the .NET service leaves for a paid invoice: InvoiceType 3 with an empty MapId is
what its SyncInvoices job picks up and carries to the ERP.

Three locks, on top of the review: ERP_WRITES_ENABLED stays off until a test order is agreed;
the login is its own (DADEHFA_WRITE_DB_*), and is refused if it is a sysadmin; and every
statement is checked against the short list below before it reaches the server.

An invoice is marked with its site id in CreatedBy, so a retry after a lost answer finds
it instead of writing it twice.
"""
from __future__ import annotations

import re
import secrets
import urllib.parse
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache

from django.conf import settings
from django.utils import timezone
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

from apps.website.models import Invoice

from .models import SiteCoupon

GIFT_CARD_BANK = 13
BANKS = {"zarinpal": 1, "snapppay": 14, "PayTypeGiftCard": GIFT_CARD_BANK}
SYSTEM = "Created By System"

_ALLOWED = re.compile(
    r"^\s*(SELECT\b|SET\s+NOCOUNT\b"
    r"|INSERT\s+INTO\s+(Customers|CustomerAddresses|Coupons|Invoices|InvoiceDetails|InvoicePayments)\b"
    r"|UPDATE\s+(Coupons|GiftCards)\s+SET\b)", re.I)
_FORBIDDEN = re.compile(r"\b(DELETE|MERGE|TRUNCATE|DROP|ALTER|CREATE|EXEC|EXECUTE|GRANT|REVOKE|DENY)\b|;", re.I)
_STRINGS = re.compile(r"N?'(?:[^']|'')*'")


class NotAllowed(RuntimeError):
    pass


class CannotSend(RuntimeError):
    """This invoice cannot go as it is; someone has to look at it."""


def check(statement: str) -> None:
    bare = _STRINGS.sub("''", statement)
    if not _ALLOWED.match(bare) or _FORBIDDEN.search(bare):
        raise NotAllowed(f"not a statement this site may send: {statement[:200]!r}")


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    cfg = settings.DADEHFA_DB
    user, password = settings.DADEHFA_WRITE_DB_USER, settings.DADEHFA_WRITE_DB_PASSWORD
    if not user or not password:
        raise CannotSend("DADEHFA_WRITE_DB_USER / DADEHFA_WRITE_DB_PASSWORD are not set")
    engine = create_engine(
        f"mssql+pymssql://{user}:{urllib.parse.quote_plus(password)}@{cfg['HOST']}:{cfg['PORT']}/{cfg['NAME']}?charset=UTF8",
        pool_pre_ping=True, pool_size=1, max_overflow=1,
    )

    @event.listens_for(engine, "before_cursor_execute")
    def _guard(conn, cursor, statement, parameters, context, executemany):
        check(statement)

    with engine.connect() as conn:
        if conn.execute(text("SELECT IS_SRVROLEMEMBER('sysadmin')")).scalar() == 1:
            raise CannotSend("the writing login must not be a sysadmin")
    return engine


# -----------------------------------------------------------------------------
# What is written
# -----------------------------------------------------------------------------
@dataclass
class Plan:
    """The rows of one invoice, ready to send; built apart so it can be read and compared with real invoices."""

    invoice: dict
    details: list[dict] = field(default_factory=list)
    payments: list[dict] = field(default_factory=list)


def _percent(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.001"), ROUND_HALF_UP)


def full_name(invoice: Invoice) -> str:
    return f"{invoice.customer.first_name} {invoice.customer.last_name}".strip()


def plan(invoice: Invoice) -> Plan:
    delivery = invoice.delivery_amount
    goods_after = invoice.amount - invoice.reduction_amount
    rows = Plan(invoice={
        "Amount": invoice.amount, "Reduction": _percent(invoice.coupon_reduction), "Discount": invoice.reduction_amount,
        "Tax": 0, "VAT": 0, "InvoiceType": Invoice.State.SUCCESSFUL.value, "Description": invoice.description,
        "IsDeleted": 0, "TsCodeId": 0, "DeliveryAmount": delivery, "DeductionAmount": invoice.deduction_amount,
        "FixedAmount": delivery, "InsuranceFee": 0, "ShippingMethodId": invoice.shipping_method_id, "TaxAmount": 0,
        "VariableAmount": 0, "AmountAfterReduction": goods_after, "AmountAfterVatAndTax": goods_after,
        "PayableAmount": invoice.payable_amount, "ReductionAmount": invoice.reduction_amount, "VatAmount": 0,
        "LastModifiedBy": full_name(invoice)[:50],
    })
    for line in invoice.lines.all():
        if not line.erp_ref:
            raise CannotSend(f"line {line.pk} has no variant reference")
        rows.details.append({
            "VariantFeatureValueId": line.erp_ref, "Name": line.name, "Price": line.price, "Reduction": _percent(line.reduction),
            "Discount": int((line.price - line.price_after_reduction) * line.qty), "Tax": 0, "VAT": 0, "Qty": line.qty,
            "IsDeleted": 0, "TsCodeId": 0,
        })
    for payment in invoice.payments.filter(is_success=True):
        if payment.gateway not in BANKS:
            raise CannotSend(f"payment {payment.pk}: unknown gateway {payment.gateway!r}")
        rows.payments.append({
            "PaymentAmount": payment.amount, "BankId": BANKS[payment.gateway], "TransactionId": payment.transaction_id or payment.reference,
            "TraceNumber": payment.reference, "CellPhone": invoice.customer.cellphone, "FullName": full_name(invoice),
            "Authority": payment.authority, "IsSuccess": 1, "IsDeleted": 0, "TsCodeId": 0, "DeliveryAmount": delivery,
        })
    paid_by_card = any(p["BankId"] == GIFT_CARD_BANK for p in rows.payments)
    if not paid_by_card and (invoice.gift_card_number or invoice.payable_amount <= 0):  # what the voucher paid is a payment of its own
        rows.payments.append({
            "PaymentAmount": invoice.deduction_amount, "BankId": GIFT_CARD_BANK, "TransactionId": str(invoice.pk),
            "TraceNumber": f"{invoice.pk}#{'G' if invoice.gift_card_number else 'C'}#{invoice.gift_card_number or invoice.coupon_serial}",
            "CellPhone": invoice.customer.cellphone, "FullName": full_name(invoice), "Authority": None, "IsSuccess": 1,
            "IsDeleted": 0, "TsCodeId": 0, "DeliveryAmount": delivery,
        })
    if not rows.details or not rows.payments:
        raise CannotSend("an invoice needs at least one line and one successful payment")
    return rows


def _insert(db, table: str, row: dict) -> int:
    columns = ", ".join(row)
    values = ", ".join(f":{c}" for c in row)
    return db.execute(text(f"INSERT INTO {table} ({columns}) OUTPUT INSERTED.Id VALUES ({values})"), row).scalar()


def _stamp(at, by: str = SYSTEM) -> dict:
    return {"Created": at.isoformat(sep=" ", timespec="seconds"), "CreatedBy": by}


def _customer_id(db, invoice: Invoice, at) -> int:
    customer = invoice.customer
    found = db.execute(text("SELECT TOP 1 Id FROM Customers WHERE CellPhone = :c AND IsDeleted = 0 ORDER BY Id"),
                       {"c": customer.cellphone}).scalar()
    if found:
        return found
    # Sign-in lives on the site, so these only have to satisfy the table.
    return _insert(db, "Customers", {
        "FirstName": customer.first_name[:40] or None, "LastName": customer.last_name[:40] or None,
        "CellPhone": customer.cellphone, "IsTowFactorAuthentication": 0, "Password": "", "IsActive": 1,
        "PublicKey": secrets.token_hex(16), "SecretKey": secrets.token_hex(25), "RefreshToken": secrets.token_hex(16),
        "NationalCode": customer.national_code[:11] or None, "IsDeleted": 0, "TsCodeId": 0, "AnnualPurchaseAmount": 0,
        **_stamp(at),
    })


def _address_id(db, invoice: Invoice, customer_id: int, at) -> int:
    address = invoice.address
    if address is None or not address.province_id or not address.city_id:
        raise CannotSend("the invoice has no complete address")
    found = db.execute(text("SELECT TOP 1 Id FROM CustomerAddresses WHERE CustomerId = :c AND Address = :a AND IsDeleted = 0 ORDER BY Id"),
                       {"c": customer_id, "a": address.address}).scalar()
    if found:
        return found
    return _insert(db, "CustomerAddresses", {
        "CustomerId": customer_id, "IsDefault": 1 if address.is_default else 0, "Address": address.address[:500],
        "ProvinceId": address.province_id, "CityId": address.city_id, "FirstName": address.first_name[:40] or None,
        "LastName": address.last_name[:40] or None, "ZipCode": address.zip_code[:10] or None, "Mobile": address.mobile[:16] or None,
        "Title": address.title[:200] or None, "IsDeleted": 0, "TsCodeId": 0, "IsMyselfRecipient": 1 if address.is_myself_recipient else 0,
        **_stamp(at),
    })


def _use_coupon(db, invoice: Invoice, customer_id: int, at) -> int | None:
    if not invoice.coupon_serial or SiteCoupon.objects.filter(serial=invoice.coupon_serial).exists():
        return None
    if invoice.coupon_id:
        db.execute(text("UPDATE Coupons SET IsUsed = 1, UsedDate = :at WHERE Id = :id"), {"at": at.replace(tzinfo=None), "id": invoice.coupon_id})
        return invoice.coupon_id
    source = db.execute(text("SELECT TOP 1 ExpiredDate, MinPrice, MaxPrice, Reduction, MapId FROM Coupons "
                             "WHERE Serial = :s AND CustomerId IS NULL AND IsDeleted = 0"), {"s": invoice.coupon_serial}).mappings().first()
    if source is None:
        raise CannotSend("the general coupon is gone")
    return _insert(db, "Coupons", {
        "CustomerId": customer_id, "Serial": invoice.coupon_serial, "Reduction": source["Reduction"], "ExpiredDate": source["ExpiredDate"],
        "IsUsed": 1, "UsedDate": at.replace(tzinfo=None), "MinPrice": source["MinPrice"], "MaxPrice": source["MaxPrice"], "IsActive": 1,
        "MapId": source["MapId"], "IsDeleted": 0, "TsCodeId": 0, **_stamp(at),
    })


def _use_gift_card(db, invoice: Invoice) -> int | None:
    if not invoice.gift_card_id:
        return None
    db.execute(text("""UPDATE GiftCards SET
            GCBalance = CASE WHEN UseCompelete = 1 OR GCBalance <= :d THEN 0 ELSE GCBalance - :d END,
            IsActive = CASE WHEN UseCompelete = 1 OR GCBalance <= :d THEN 0 ELSE IsActive END,
            BankPortalEndTime = NULL
        WHERE Id = :id"""), {"d": invoice.deduction_amount, "id": invoice.gift_card_id})
    return invoice.gift_card_id


def push(invoice: Invoice) -> None:
    """Writes one paid invoice. Does nothing until ERP_WRITES_ENABLED; safe to call again."""
    if not settings.ERP_WRITES_ENABLED or invoice.erp_sent_at or invoice.is_test:
        return
    rows = plan(invoice)
    at = timezone.localtime()
    mark = f"site:{invoice.pk}"
    with get_engine().begin() as db:
        invoice_id = db.execute(text("SELECT TOP 1 Id FROM Invoices WHERE CreatedBy = :m"), {"m": mark}).scalar()
        if not invoice_id:
            customer_id = _customer_id(db, invoice, at)
            address_id = _address_id(db, invoice, customer_id, at)
            invoice_id = _insert(db, "Invoices", {
                **rows.invoice, "CustomerId": customer_id, "CustomerAddressId": address_id, "CouponId": _use_coupon(db, invoice, customer_id, at),
                "GiftCardId": _use_gift_card(db, invoice), **_stamp(at, mark),
            })
            for row in rows.details:
                _insert(db, "InvoiceDetails", {**row, "InvoiceId": invoice_id, **_stamp(at)})
            for row in rows.payments:
                _insert(db, "InvoicePayments", {**row, "InvoiceId": invoice_id, **_stamp(at)})
    Invoice.objects.filter(pk=invoice.pk).update(erp_invoice_id=invoice_id, erp_sent_at=timezone.now(), erp_error="")
