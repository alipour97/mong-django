"""
Management command: bring customers and their order history over from DadehfaOnlineShop
(read only). Run once before the site goes live, and again just before the domain moves:
rows that are already here are updated, and nothing the site made itself is touched.

    python manage.py import_dadehfa_orders
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.utils import timezone

from apps.legacy.db import fetch_all, iter_rows
from apps.website.models import Customer, CustomerAddress, CustomerFavoriteProduct, Invoice, InvoiceLine, InvoicePayment

BATCH = 1000
# New rows start above every id the old site can reach before the move, so an imported id never lands on one of ours.
OUR_IDS_START = 1_000_000
GROUPS_OF_INVOICES = "2, 3, 4"  # suspended, paid, cancelled: an old cart (1) is nothing to keep

CUSTOMER_COLUMNS = ["first_name", "last_name", "cellphone", "email", "national_code", "birth_date", "job_id", "is_active",
                    "is_bulletin_enabled", "bulletin_subscription_date", "map_id", "is_deleted", "created", "last_modified",
                    "erp_customer_id"]


def _s(value) -> str:
    return "" if value is None else str(value)


def _dt(value: datetime | None):
    if value is None or value.year <= 1 or value.year >= 9999:
        return None
    return timezone.make_aware(value) if timezone.is_naive(value) else value


class Command(BaseCommand):
    help = "ورود مشتریان و سابقه سفارش‌ها از DadehfaOnlineShop (فقط خواندنی)"

    def handle(self, *args, **opts):
        with transaction.atomic():
            owners = self.customers()
            addresses = self.addresses(owners)
            self.favorites(owners)
            self.orders(owners, addresses)
            self.make_room()
        self.stdout.write(self.style.SUCCESS("تمام شد"))

    def customers(self) -> dict[int, int]:
        """Old customer id -> the account here. Duplicate mobiles fall on one account, and a mobile that
        signed up here first keeps that account."""
        here = dict(Customer.objects.values_list("cellphone", "id"))
        owners, rows = {}, []
        for r in iter_rows("SELECT * FROM Customers ORDER BY Id"):
            phone = _s(r["CellPhone"]).strip()
            if phone in here and here[phone] != r["Id"]:
                owners[r["Id"]] = here[phone]
                continue
            here[phone] = r["Id"]
            owners[r["Id"]] = r["Id"]
            rows.append(Customer(
                id=r["Id"], first_name=_s(r["FirstName"]), last_name=_s(r["LastName"]), cellphone=phone, email=_s(r["Email"]),
                national_code=_s(r["NationalCode"]), birth_date=r["BirthDate"] if r["BirthDate"] and r["BirthDate"].year > 1 else None,
                job_id=r["JobId"], is_active=bool(r["IsActive"]), is_bulletin_enabled=bool(r["IsBulletinEnable"]),
                bulletin_subscription_date=_dt(r["BulletinSubscriptionDate"]), map_id=_s(r["MapId"]), is_deleted=bool(r["IsDeleted"]),
                created=_dt(r["Created"]), last_modified=_dt(r["LastModified"]), erp_customer_id=r["Id"],
            ))
        Customer.objects.bulk_create(rows, batch_size=BATCH, update_conflicts=True, unique_fields=["id"], update_fields=CUSTOMER_COLUMNS)
        self.stdout.write(f"customers: {len(rows)}")
        return owners

    def addresses(self, owners: dict[int, int]) -> set[int]:
        rows = []
        for r in iter_rows("SELECT * FROM CustomerAddresses"):
            if r["CustomerId"] not in owners:
                continue
            rows.append(CustomerAddress(
                id=r["Id"], customer_id=owners[r["CustomerId"]], title=_s(r["Title"]), is_default=bool(r["IsDefault"]), address=_s(r["Address"]),
                province_id=r["ProvinceId"], city_id=r["CityId"], zip_code=_s(r["ZipCode"]), latitude=r["Latitude"], longitude=r["Longitude"],
                first_name=_s(r["FirstName"]), last_name=_s(r["LastName"]), mobile=_s(r["Mobile"]), is_myself_recipient=bool(r["IsMyselfRecipient"]),
                map_id=_s(r["MapId"]), is_deleted=bool(r["IsDeleted"]), created=_dt(r["Created"]), last_modified=_dt(r["LastModified"]),
                erp_address_id=r["Id"],
            ))
        columns = [f.name for f in CustomerAddress._meta.concrete_fields if f.name not in ("id", "samian_contact_id")]
        CustomerAddress.objects.bulk_create(rows, batch_size=BATCH, update_conflicts=True, unique_fields=["id"], update_fields=columns)
        self.stdout.write(f"addresses: {len(rows)}")
        return {r.id for r in rows}

    def favorites(self, owners: dict[int, int]) -> None:
        rows = [
            CustomerFavoriteProduct(
                id=r["Id"], customer_id=owners[r["CustomerId"]], product_id=r["ProductId"], color_id=r["ColerId"], size_id=r["SizeId"],
                map_id=_s(r.get("MapId")), is_deleted=bool(r.get("IsDeleted")), created=_dt(r.get("Created")), last_modified=_dt(r.get("LastModified")),
            )
            for r in iter_rows("SELECT * FROM CustomerFavoriteProducts") if r["CustomerId"] in owners
        ]
        columns = [f.name for f in CustomerFavoriteProduct._meta.concrete_fields if f.name != "id"]
        CustomerFavoriteProduct.objects.bulk_create(rows, batch_size=BATCH, update_conflicts=True, unique_fields=["id"], update_fields=columns)
        self.stdout.write(f"favorites: {len(rows)}")

    def orders(self, owners: dict[int, int], addresses: set[int]) -> None:
        names = {r["Id"]: r["Name"] for r in fetch_all("SELECT Id, Name FROM Provinces")}
        cities = {r["Id"]: r["Name"] for r in fetch_all("SELECT Id, Name FROM Cities")}
        banks = {r["Id"]: r["BankWebSite"] for r in fetch_all("SELECT Id, BankWebSite FROM BankInfos")}
        address_of = {a.id: a for a in CustomerAddress.objects.filter(id__in=addresses)}
        invoices, skipped = [], 0
        coupons = {r["Id"]: r["Serial"] for r in fetch_all("SELECT Id, Serial FROM Coupons WHERE Id IN (SELECT CouponId FROM Invoices)")}
        gifts = {r["Id"]: r["GCNum"] for r in fetch_all("SELECT Id, GCNum FROM GiftCards WHERE Id IN (SELECT GiftCardId FROM Invoices)")}
        for r in iter_rows(f"SELECT * FROM Invoices WHERE InvoiceType IN ({GROUPS_OF_INVOICES})"):
            if r["CustomerId"] not in owners:
                skipped += 1
                continue
            a = address_of.get(r["CustomerAddressId"])
            taken = _dt(r["Created"]) if r["MapId"] else None
            invoices.append(Invoice(
                id=r["Id"], customer_id=owners[r["CustomerId"]], state=r["InvoiceType"], shipping_method_id=r["ShippingMethodId"],
                address=a, recipient_name=f"{a.first_name} {a.last_name}".strip() if a else "", recipient_mobile=a.mobile if a else "",
                full_address=a.address if a else "", postal_code=a.zip_code if a else "",
                province_name=names.get(a.province_id, "") if a else "", city_name=cities.get(a.city_id, "") if a else "",
                amount=int(r["Amount"]), reduction_amount=int(r["ReductionAmount"]), delivery_amount=int(r["DeliveryAmount"] or 0),
                deduction_amount=int(r["DeductionAmount"]), payable_amount=int(r["PayableAmount"]), description=_s(r["Description"]),
                gift_card_number=gifts.get(r["GiftCardId"], ""), coupon_serial=coupons.get(r["CouponId"], ""), coupon_id=r["CouponId"],
                gift_card_id=r["GiftCardId"], coupon_reduction=r["Reduction"] or 0,
                paid_at=_dt(r["LastModified"]) if r["InvoiceType"] == Invoice.State.SUCCESSFUL else None, number=str(r["Id"]),
                erp_invoice_id=r["Id"], erp_sent_at=_dt(r["Created"]), erp_taken_at=taken or _dt(r["Created"]),
                is_deleted=bool(r["IsDeleted"]),
            ))
            invoices[-1].legacy_created = _dt(r["Created"])
        columns = [f.name for f in Invoice._meta.concrete_fields if f.name not in ("id", "created", "last_modified", "samian_transaction_id", "erp_error")]
        Invoice.objects.bulk_create(invoices, batch_size=BATCH, update_conflicts=True, unique_fields=["id"], update_fields=columns)
        for chunk in range(0, len(invoices), BATCH):  # created fills itself in on insert
            Invoice.objects.bulk_update(
                [Invoice(id=i.id, created=i.legacy_created) for i in invoices[chunk:chunk + BATCH]], ["created"])
        ids = {i.id for i in invoices}
        self.stdout.write(f"invoices: {len(ids)} ({skipped} without a customer)")

        id_list = ",".join(str(i) for i in sorted(ids)) or "0"
        values = {r["Id"]: r["Name"] for r in fetch_all("SELECT Id, Name FROM FeatureValues")}
        hex_of = {r["Id"]: r["Value"] for r in fetch_all("SELECT Id, Value FROM FeatureValues")}
        lines = []
        for r in iter_rows(f"""
                SELECT d.Id, d.InvoiceId, d.VariantFeatureValueId, d.Name, d.Price, d.Reduction, d.Discount, d.Qty,
                       v.Id AS Vid, v.ProductId, v.Barcode, f.ParentFeatureValueId AS Color, f.ChildFeatureValueId AS Size
                FROM InvoiceDetails d
                LEFT JOIN VariantFeatureValues l ON l.Id = d.VariantFeatureValueId
                LEFT JOIN ProductVariants v ON v.Id = l.ProductVariantId
                LEFT JOIN FeatureValueDependencies f ON f.Id = l.FeatureValueDependencyId
                WHERE d.IsDeleted = 0 AND d.InvoiceId IN ({id_list})"""):
            if r["ProductId"] is None:
                continue
            qty = Decimal(r["Qty"] or 0)
            lines.append(InvoiceLine(
                id=r["Id"], invoice_id=r["InvoiceId"], product_id=r["ProductId"], variant_id=r["Vid"], erp_ref=r["VariantFeatureValueId"],
                barcode=_s(r["Barcode"]).strip(), name=_s(r["Name"])[:512], color_id=r["Color"], color_name=_s(values.get(r["Color"])),
                color_value=_s(hex_of.get(r["Color"])), size_name=_s(values.get(r["Size"])), qty=qty, price=int(r["Price"]),
                reduction=r["Reduction"] or 0, price_after_reduction=int(r["Price"] - (r["Discount"] / qty if qty else 0)),
            ))
        columns = [f.name for f in InvoiceLine._meta.concrete_fields if f.name != "id"]
        InvoiceLine.objects.bulk_create(lines, batch_size=BATCH, update_conflicts=True, unique_fields=["id"], update_fields=columns)
        self.stdout.write(f"lines: {len(lines)}")

        payments = [
            InvoicePayment(
                id=r["Id"], invoice_id=r["InvoiceId"], gateway=_s(banks.get(r["BankId"])), amount=int(r["PaymentAmount"]), authority=_s(r["Authority"])[:255],
                transaction_id=_s(r["TransactionId"])[:64], reference=_s(r["TraceNumber"])[:255], is_success=bool(r["IsSuccess"]),
                error_message=_s(r["ErrorMessage"]), verified_at=_dt(r["Created"]),
            )
            for r in iter_rows(f"SELECT * FROM InvoicePayments WHERE InvoiceId IN ({id_list})")
        ]
        columns = [f.name for f in InvoicePayment._meta.concrete_fields if f.name not in ("id", "created", "card_pan")]
        InvoicePayment.objects.bulk_create(payments, batch_size=BATCH, update_conflicts=True, unique_fields=["id"], update_fields=columns)
        self.stdout.write(f"payments: {len(payments)}")

    def make_room(self) -> None:
        if connection.vendor != "postgresql":
            return
        with connection.cursor() as cursor:
            for model in (Customer, CustomerAddress, CustomerFavoriteProduct, Invoice, InvoiceLine, InvoicePayment):
                table = model._meta.db_table
                cursor.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), GREATEST((SELECT COALESCE(MAX(id), 0) FROM {table}), %s))",
                               [OUR_IDS_START])
