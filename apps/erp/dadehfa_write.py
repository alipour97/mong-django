"""
Paid invoices into DadehfaOnlineShop, the one way this project writes there. The row shapes
copy what the .NET site (api.mongnew.ir) leaves for a paid invoice: PaymentVerificationHandler
after a gateway, PayInvoiceByIdHandler when the voucher paid it all. InvoiceType 3 with an
empty MapId is what its SyncInvoices job picks up and carries to the ERP.

Three locks, on top of the review: ERP_WRITES_ENABLED stays off until a test order is agreed;
the login is its own (DADEHFA_WRITE_DB_*), and is refused if it is a sysadmin unless
DADEHFA_ALLOW_SYSADMIN; and every statement is checked against the short list below before it
reaches the server.

An invoice is marked with its site id in CreatedBy, so a retry after a lost answer finds
it instead of writing it twice. The coupon or gift card it spent, the variants' Qty and the
default address are settled in the same transaction, as the .NET site does. Test orders go
too, with a note in Description. Every statement that writes is logged in ErpWriteLog with
how its transaction ended, and failed attempts too.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache

from django.conf import settings
from django.utils import timezone
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import URL, Engine

from apps.website.models import Invoice

from .models import ErpWriteLog, SiteCoupon

logger = logging.getLogger(__name__)

GIFT_CARD_BANK = 13
BANKS = {"zarinpal": 1, "snapppay": 14, "PayTypeGiftCard": GIFT_CARD_BANK}
SYSTEM = "Created By System"
TEST_MARK = "سفارش تست: پولی جابه‌جا نشده"
# Description is nvarchar(300); the payment columns are 64, CellPhone 16 and FullName 80.
DESCRIPTION, CODE, PHONE, NAME = 300, 64, 16, 80

_ALLOWED = re.compile(
    r"^\s*(SELECT\b|SET\s+NOCOUNT\b"
    r"|INSERT\s+INTO\s+(Customers|CustomerAddresses|Coupons|Invoices|InvoiceDetails|InvoicePayments)\b"
    r"|UPDATE\s+(Coupons|GiftCards|CustomerAddresses|ProductVariants|Products)\s+SET\b)", re.I)
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
    # User and password go together: the writing pair if it is set, else the reading one (sa on a machine that allows it).
    # Mixing one's user with the other's password is what makes "Login failed".
    if settings.DADEHFA_WRITE_DB_USER and settings.DADEHFA_WRITE_DB_USER != cfg.get("USER"):
        user, password = settings.DADEHFA_WRITE_DB_USER, settings.DADEHFA_WRITE_DB_PASSWORD
    else:
        user, password = cfg.get("USER", ""), cfg.get("PASSWORD", "")
    if not user or not password:
        raise CannotSend("DADEHFA_WRITE_DB_USER / DADEHFA_WRITE_DB_PASSWORD are not set")
    url = URL.create("mssql+pymssql", username=user, password=password, host=cfg["HOST"], port=int(cfg["PORT"]),
                     database=cfg["NAME"], query={"charset": "UTF8"})
    engine = create_engine(url, pool_pre_ping=True, pool_size=1, max_overflow=1)

    @event.listens_for(engine, "before_cursor_execute")
    def _guard(conn, cursor, statement, parameters, context, executemany):
        check(statement)

    with engine.connect() as conn:
        allow_sysadmin = getattr(settings, "DADEHFA_ALLOW_SYSADMIN", False)
        if not allow_sysadmin and conn.execute(text("SELECT IS_SRVROLEMEMBER('sysadmin')")).scalar() == 1:
            raise CannotSend("the writing login must not be a sysadmin")
    return engine


class _Logged:
    """Sends one invoice's statements and keeps a record of those that write."""

    def __init__(self, invoice_id: int):
        self.invoice_id, self.db, self.rows = invoice_id, None, []

    def execute(self, statement, params=None):
        sql = str(statement)
        words = sql.split()
        if words[0].upper() == "SELECT":
            return self.db.execute(statement, params)
        table = words[2] if words[0].upper() == "INSERT" else words[1]
        row = ErpWriteLog(invoice_id=self.invoice_id, software="dadehfa", action=f"{words[0].upper()} {table}", statement=sql,
                          params=json.loads(json.dumps(params or {}, default=str)))
        self.rows.append(row)
        return _Recorded(self.db.execute(statement, params), row)

    def save(self, error: str = "") -> None:
        """Called once the transaction has ended: its rows all went in, or none did."""
        rows = self.rows or ([ErpWriteLog(invoice_id=self.invoice_id, software="dadehfa")] if error else [])
        for row in rows:
            row.ok, row.error = not error, error[:2000]
            logger.info("dadehfa write: invoice %s %s %s %s", self.invoice_id, row.action, row.result, "ok" if row.ok else error)
        ErpWriteLog.objects.bulk_create(rows)


class _Recorded:
    """A statement's result; the id it hands back goes into the log."""

    def __init__(self, result, row: ErpWriteLog):
        self.result, self.row = result, row

    def scalar(self):
        value = self.result.scalar()
        self.row.result = str(value)
        return value


# -----------------------------------------------------------------------------
# What is written
# -----------------------------------------------------------------------------
@dataclass
class Plan:
    """
    The rows of one invoice, ready to send; built apart so it can be read and compared with real invoices.
    In the voucher's payment row "{invoice}" stands for the software's invoice id, known once the head is in.
    """

    invoice: dict
    free: bool = False
    details: list[dict] = field(default_factory=list)
    payments: list[dict] = field(default_factory=list)
    taken: dict[int, Decimal] = field(default_factory=dict)  # VariantFeatureValueId: qty, off ProductVariants.Qty


def _percent(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.001"), ROUND_HALF_UP)


def full_name(invoice: Invoice) -> str:
    """Customer.FullName in .NET: first and last name with a space between, even when one is empty."""
    return f"{invoice.customer.first_name or ''} {invoice.customer.last_name or ''}"


def _description(invoice: Invoice, free: bool) -> str:
    text = invoice.description
    if free:  # PayInvoiceByIdHandler adds how it was paid on a line of its own
        text += "\r\n" + ("پرداخت با کارت هدیه" if invoice.gift_card_id or invoice.gift_card_number else "پرداخت با کوپن")
    if invoice.is_test:
        text = f"{TEST_MARK}\r\n{text}" if text else TEST_MARK
    return text[:DESCRIPTION]


def plan(invoice: Invoice) -> Plan:
    # No gateway when the voucher covered it all: PayInvoiceByIdHandler. Otherwise PaymentVerificationHandler.
    free = invoice.payable_amount <= 0
    delivery = invoice.delivery_amount
    goods_after = invoice.amount - invoice.reduction_amount
    cellphone, name = invoice.customer.cellphone[:PHONE], full_name(invoice)[:NAME]
    rows = Plan(free=free, invoice={
        "Amount": invoice.amount, "Reduction": _percent(invoice.coupon_reduction), "Discount": invoice.reduction_amount,
        "Tax": 0, "VAT": 0, "InvoiceType": Invoice.State.SUCCESSFUL.value, "Description": _description(invoice, free),
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
        rows.taken[line.erp_ref] = rows.taken.get(line.erp_ref, Decimal(0)) + Decimal(line.qty)
    paid = []
    for payment in invoice.payments.filter(is_success=True):
        if payment.gateway not in BANKS:
            raise CannotSend(f"payment {payment.pk}: unknown gateway {payment.gateway!r}")
        # As in the shop's own rows: TraceNumber and Authority are one tracking code, TransactionId the gateway's own
        # (Zarinpal's authority, SnappPay's transactionId).
        trace = (payment.reference or payment.authority)[:CODE] or None
        paid.append({
            "PaymentAmount": payment.amount, "BankId": BANKS[payment.gateway], "TransactionId": (payment.transaction_id or payment.authority)[:CODE] or None,
            "TraceNumber": trace, "CellPhone": cellphone, "FullName": name, "Authority": trace,
            "IsSuccess": 1, "IsDeleted": 0, "TsCodeId": 0, "DeliveryAmount": delivery,
        })
    paid_by_card = any(p["BankId"] == GIFT_CARD_BANK for p in paid)
    voucher = None
    if paid_by_card:
        pass
    elif free:
        code = invoice.gift_card_number or invoice.coupon_serial or "Unknown"
        voucher = {
            "TransactionId": "{invoice}", "Authority": None,
            "TraceNumber": f"{{invoice}}#{'G' if invoice.gift_card_number else 'C'}#{code}"[:CODE],
        }
    elif invoice.gift_card_number:  # with a gateway the card's row comes first and carries the card's id
        voucher = {
            "TransactionId": None, "Authority": paid[0]["Authority"] if paid else None,
            "TraceNumber": f"{{invoice}}#G#{invoice.gift_card_id or invoice.gift_card_number}"[:CODE],
        }
    if voucher:
        rows.payments.append({
            "PaymentAmount": invoice.deduction_amount, "BankId": GIFT_CARD_BANK, "CellPhone": cellphone, "FullName": name,
            "IsSuccess": 1, "IsDeleted": 0, "TsCodeId": 0, "DeliveryAmount": delivery, **voucher,
        })
    rows.payments += paid
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
    if address.is_default:  # AddCustomerAddressRequestHandler: one default address per customer
        db.execute(text("UPDATE CustomerAddresses SET IsDefault = 0 WHERE CustomerId = :c AND IsDefault = 1"), {"c": customer_id})
    return _insert(db, "CustomerAddresses", {
        "CustomerId": customer_id, "IsDefault": 1 if address.is_default else 0, "Address": address.address[:500],
        "ProvinceId": address.province_id, "CityId": address.city_id, "FirstName": address.first_name[:40] or None,
        "LastName": address.last_name[:40] or None, "ZipCode": address.zip_code[:10] or None, "Mobile": address.mobile[:16] or None,
        "Title": address.title[:200] or None, "IsDeleted": 0, "TsCodeId": 0, "IsMyselfRecipient": 1 if address.is_myself_recipient else 0,
        **_stamp(at),
    })


def _use_coupon(db, invoice: Invoice, customer_id: int, at) -> int | None:
    """The customer's own copy of the coupon, marked used as PaymentVerificationHandler leaves it."""
    if not invoice.coupon_serial or SiteCoupon.objects.filter(serial=invoice.coupon_serial).exists():
        return None
    own = invoice.coupon_id or db.execute(text(
        "SELECT TOP 1 Id FROM Coupons WHERE Serial = :s AND CustomerId = :c AND (IsUsed IS NULL OR IsUsed = 0) AND IsDeleted = 0 ORDER BY Id"),
        {"s": invoice.coupon_serial, "c": customer_id}).scalar()
    if own:
        db.execute(text("UPDATE Coupons SET IsActive = 1, BankPortalEndTime = NULL, IsUsed = 1, UsedDate = :at WHERE Id = :id"),
                   {"at": at.replace(tzinfo=None), "id": own})
        return own
    source = db.execute(text("SELECT TOP 1 ExpiredDate, MinPrice, MaxPrice, Reduction, MapId FROM Coupons "
                             "WHERE Serial = :s AND CustomerId IS NULL AND IsActive = 1 AND IsDeleted = 0"), {"s": invoice.coupon_serial}).mappings().first()
    if source is None:
        raise CannotSend("the general coupon is gone")
    return _insert(db, "Coupons", {
        "CustomerId": customer_id, "Serial": invoice.coupon_serial, "Reduction": source["Reduction"], "ExpiredDate": source["ExpiredDate"],
        "IsUsed": 1, "UsedDate": at.replace(tzinfo=None), "MinPrice": source["MinPrice"], "MaxPrice": source["MaxPrice"], "IsActive": 1,
        "MapId": source["MapId"], "IsDeleted": 0, "TsCodeId": 0, **_stamp(at),
    })


def _use_gift_card(db, invoice: Invoice, free: bool) -> int | None:
    """
    The balance as the .NET site leaves it: what was taken comes off, and a card used up or for one use only
    is switched off. Only PayInvoiceByIdHandler (no gateway) also empties a one-use card.
    """
    if not invoice.gift_card_id:
        return None
    db.execute(text("""UPDATE GiftCards SET
            GCBalance = CASE WHEN GCBalance <= :d OR (:free = 1 AND UseCompelete = 1) THEN 0 ELSE GCBalance - :d END,
            IsActive = CASE WHEN UseCompelete = 1 OR GCBalance <= :d THEN 0 ELSE 1 END,
            BankPortalEndTime = NULL
        WHERE Id = :id"""), {"d": invoice.deduction_amount, "free": 1 if free else 0, "id": invoice.gift_card_id})
    return invoice.gift_card_id


_VARIANT = "(SELECT ProductVariantId FROM VariantFeatureValues WHERE Id = :ref)"


def _take_stock(db, rows: Plan) -> None:
    """The shop's own Qty goes down at once, as the .NET site does; its next stock sync puts the ERP's figure back."""
    for ref, qty in rows.taken.items():
        db.execute(text(f"UPDATE ProductVariants SET Qty = Qty - :q WHERE Id = {_VARIANT}"), {"q": qty, "ref": ref})
        if rows.free:  # only PayInvoiceByIdHandler counts the sale on the product
            db.execute(text(f"UPDATE Products SET SalesCount = SalesCount + :q WHERE Id = (SELECT ProductId FROM ProductVariants WHERE Id = {_VARIANT})"),
                       {"q": int(qty), "ref": ref})


def push(invoice: Invoice) -> None:
    """Writes one paid invoice, test orders too. Does nothing until ERP_WRITES_ENABLED; safe to call again."""
    if not settings.ERP_WRITES_ENABLED or invoice.erp_sent_at:
        return
    rows = plan(invoice)
    at = timezone.localtime()
    mark = f"site:{invoice.pk}"
    db = _Logged(invoice.pk)
    try:
        with get_engine().begin() as db.db:
            invoice_id = db.execute(text("SELECT TOP 1 Id FROM Invoices WHERE CreatedBy = :m"), {"m": mark}).scalar()
            if not invoice_id:
                customer_id = _customer_id(db, invoice, at)
                address_id = _address_id(db, invoice, customer_id, at)
                invoice_id = _insert(db, "Invoices", {
                    **rows.invoice, "CustomerId": customer_id, "CustomerAddressId": address_id, "CouponId": _use_coupon(db, invoice, customer_id, at),
                    "GiftCardId": _use_gift_card(db, invoice, rows.free), **_stamp(at, mark),
                    "LastModified": at.isoformat(sep=" ", timespec="seconds"),
                })
                for row in rows.details:
                    _insert(db, "InvoiceDetails", {**row, "InvoiceId": invoice_id, **_stamp(at)})
                for row in rows.payments:
                    row = {k: v.replace("{invoice}", str(invoice_id)) if isinstance(v, str) else v for k, v in row.items()}
                    _insert(db, "InvoicePayments", {**row, "InvoiceId": invoice_id, **_stamp(at)})
                _take_stock(db, rows)
    except Exception as exc:
        db.save(str(exc))
        raise
    db.save()
    Invoice.objects.filter(pk=invoice.pk).update(erp_invoice_id=invoice_id, erp_sent_at=timezone.now(), erp_error="")
