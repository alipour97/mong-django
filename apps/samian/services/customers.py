"""
Customers, their addresses and their purchase history, read from Samian.

Samian is shared with Lebaza, so instead of copying every Samian customer this
reads only the people who have an account on the site (website.Customer),
matched by mobile number, the one identifier both sides have:

    retail/poscustomer          -> SamianCustomer          filter mobilephone
    accounts/contactinfo        -> SamianCustomerAddress   filter poscustomer_id
    retail/postransaction       -> SamianSalesTransaction  filter poscustomer_id
    retail/postransactionitems  -> SamianSalesRow          filter postransaction_id

Samian has no "in" filter, so each request asks for CHUNK ids joined with
"or". Every Samian customer with the site customer's mobile is kept (a person
can have several); website.Customer.samian_customer points at the oldest.
All invoices of those customers are kept, from any branch.

Read only: nothing is written to Samian.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Iterator

from django.utils import timezone

from apps.samian.client import SamianClient, extract_records, get_samian_client
from apps.samian.models import (
    SamianBarcode,
    SamianCustomer,
    SamianCustomerAddress,
    SamianProduct,
    SamianSalesRow,
    SamianSalesTransaction,
    SamianSyncLog,
)
from apps.samian.services.erp_sync import (
    _chunks,
    _dec,
    _dt,
    _int,
    _log_finish,
    _log_start,
    _money,
    _s,
    _warehouse_pks,
)

logger = logging.getLogger(__name__)

CHUNK = 25
PAGE = 1000
BATCH = 1000

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize_mobile(value: Any) -> str:
    """09xxxxxxxxx from any spelling (Persian digits, +98, missing 0); other values as digits."""
    digits = "".join(ch for ch in _s(value).translate(_PERSIAN_DIGITS) if ch.isdigit())
    if digits.startswith("0098"):
        digits = "0" + digits[4:]
    elif digits.startswith("98") and len(digits) == 12:
        digits = "0" + digits[2:]
    elif digits.startswith("9") and len(digits) == 10:
        digits = "0" + digits
    return digits


def _date(value: Any):
    dt = _dt(value)
    return dt.date() if dt else None


def _any_of(field: str, values: Iterable[Any]) -> list:
    query: list = []
    for value in values:
        if query:
            query.append("or")
        query.append([field, "=", value])
    return query


def _iter_matching(client: SamianClient, endpoint: str, key: str, field: str, values: list) -> Iterator[dict]:
    """Every record of endpoint whose field equals one of values, CHUNK values per request."""
    for chunk in _chunks(values, CHUNK):
        yield from client.iter_keyset(endpoint, key=key, take_count=PAGE, filters=_any_of(field, chunk))


def _upsert(model, instances: list, update_fields: list[str]) -> None:
    for batch in _chunks(instances, BATCH):
        model.objects.bulk_create(batch, update_conflicts=True, unique_fields=["samian_id"], update_fields=update_fields)


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------
CUSTOMER_FIELDS = [
    "first_name", "last_name", "display_name", "mobile", "phone", "email",
    "gender_id", "gender", "club_level_id", "club_level",
    "customer_type_id", "customer_type", "customer_status_id", "customer_status",
    "subscription_code", "customer_card_num", "national_code", "birthdate", "subscription_date",
    "wallet_balance", "club_point_score", "club_price_score", "address", "postal_code",
    "is_active", "updated_at",
]


def _customer(item: dict) -> SamianCustomer:
    return SamianCustomer(
        samian_id=_int(item.get("poscustomer_id") or item.get("id")),
        first_name=_s(item.get("name"), 150),
        last_name=_s(item.get("family"), 150),
        display_name=_s(item.get("fullname"), 255),
        mobile=normalize_mobile(item.get("mobilephone"))[:50],
        phone=_s(item.get("telphone"), 50),
        email=_s(item.get("email"), 254),
        gender_id=_int(item.get("gender_id")),
        gender=_s(item.get("__gender_id_value"), 32),
        club_level_id=_int(item.get("posclublevel_id")),
        club_level=_s(item.get("__posclublevel_id_value"), 128),
        customer_type_id=_int(item.get("customertype_id")),
        customer_type=_s(item.get("__customertype_id_value"), 128),
        customer_status_id=_int(item.get("customerstatus_id")),
        customer_status=_s(item.get("__customerstatus_id_value"), 128),
        subscription_code=_s(item.get("subscriptioncode"), 128),
        customer_card_num=_s(item.get("customercardnum"), 128),
        national_code=_s(item.get("nationalcode") or item.get("nationalid"), 32),
        birthdate=_date(item.get("birthdate")),
        subscription_date=_dt(item.get("subscriptiondate")),
        wallet_balance=_money(item.get("walletbalance")),
        club_point_score=_dec(item.get("clubpointscore")),
        club_price_score=_money(item.get("clubpricescore")),
        address=_s(item.get("address")),
        postal_code=_s(item.get("postalcode"), 32),
        is_active=bool(item.get("isactive", True)),
    )


def sync_customers(client: SamianClient, mobiles: list[str]) -> int:
    """Store the Samian customers that have one of these mobiles. Returns how many."""
    wanted = set(mobiles)
    instances = {}
    # Samian stores the number as typed; ask for both 09.. and 9.. spellings.
    variants = sorted({v for m in mobiles for v in (m, m[1:])})
    for item in _iter_matching(client, "retail/poscustomer", "poscustomer_id", "mobilephone", variants):
        c = _customer(item)
        if c.samian_id and c.mobile in wanted:
            instances[c.samian_id] = c
    _upsert(SamianCustomer, list(instances.values()), CUSTOMER_FIELDS)
    return len(instances)


def link_site_customers(site_customers) -> int:
    """Point each site customer at the oldest Samian customer with the same mobile."""
    from apps.website.models import Customer

    oldest: dict[str, int] = {}
    mobiles = {normalize_mobile(c.cellphone) for c in site_customers}
    for pk, mobile in SamianCustomer.objects.filter(mobile__in=mobiles).order_by("samian_id").values_list("pk", "mobile"):
        oldest.setdefault(mobile, pk)
    now = timezone.now()
    for c in site_customers:
        c.samian_customer_id = oldest.get(normalize_mobile(c.cellphone))
        c.samian_checked_at = now
    Customer.objects.bulk_update(site_customers, ["samian_customer", "samian_checked_at"], batch_size=BATCH)
    return sum(1 for c in site_customers if c.samian_customer_id)


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------
ADDRESS_FIELDS = [
    "customer", "customer_samian_id", "title", "address", "receiver_name", "mobile", "phone",
    "postal_code", "province_id", "province", "town_id", "town", "is_default", "updated_at",
]


def sync_addresses(client: SamianClient, customer_pks: dict[int, int]) -> int:
    """Addresses of these Samian customers (samian id -> pk); addresses removed in Samian are deleted."""
    instances = []
    for item in _iter_matching(client, "accounts/contactinfo", "contactinfo_id", "poscustomer_id", list(customer_pks)):
        owner = _int(item.get("poscustomer_id"))
        instances.append(SamianCustomerAddress(
            samian_id=_int(item.get("contactinfo_id") or item.get("id")),
            customer_id=customer_pks.get(owner),
            customer_samian_id=owner,
            title=_s(item.get("contacttitle"), 255),
            address=_s(item.get("address")),
            receiver_name=_s(item.get("receiverfullname"), 255),
            mobile=normalize_mobile(item.get("mobilephone"))[:50],
            phone=_s(item.get("telphone"), 50),
            postal_code=_s(item.get("postalcode"), 32),
            province_id=_int(item.get("provinces_id")),
            province=_s(item.get("__provinces_id_value"), 128),
            town_id=_int(item.get("towns_id")),
            town=_s(item.get("__towns_id_value"), 128),
            is_default=bool(item.get("isdefault")),
        ))
    _upsert(SamianCustomerAddress, instances, ADDRESS_FIELDS)
    SamianCustomerAddress.objects.filter(customer_samian_id__in=customer_pks).exclude(
        samian_id__in=[a.samian_id for a in instances]
    ).delete()
    return len(instances)


# ---------------------------------------------------------------------------
# Purchase history
# ---------------------------------------------------------------------------
TRANSACTION_FIELDS = [
    "transaction_code", "transaction_unique_id", "transaction_date", "report_date", "order_date",
    "samian_customer", "customer_samian_id", "warehouse_id", "warehouse", "samian_warehouse",
    "department_id", "department", "cash_id", "cash_name", "cashier_person_id", "cashier_name",
    "status_id", "status", "total_amount", "total_discount", "total_vat", "net_amount",
    "rounding_discount", "transaction_score", "is_first_buy", "year_info_id", "delivery_address", "updated_at",
]

ROW_FIELDS = [
    "transaction", "transaction_samian_id", "samian_barcode", "samian_product", "barcode",
    "barcodemain_id", "productmain_id", "subcode", "item_name", "transaction_date", "report_date",
    "quantity", "unit_price_before_discount", "unit_price", "discount_percent", "discount_amount",
    "vat_amount", "gross_amount", "line_revenue", "sale_person_id", "sale_person_name",
    "warehouse_id", "samian_warehouse", "is_return", "is_gifted", "updated_at",
]


def _transaction(item: dict, customer_pks: dict[int, int], warehouse_pks: dict[int, int]) -> SamianSalesTransaction:
    tx_date = _dt(item.get("transactiondate"))
    customer = _int(item.get("poscustomer_id"))
    warehouse = _int(item.get("warehouse_id"))
    return SamianSalesTransaction(
        samian_id=_int(item.get("postransaction_id") or item.get("id")),
        transaction_code=_s(item.get("transactioncode"), 128),
        transaction_unique_id=_s(item.get("transactionuniqueid"), 64),
        transaction_date=tx_date,
        report_date=timezone.localtime(tx_date).date() if tx_date else None,
        order_date=_dt(item.get("orderdate")),
        samian_customer_id=customer_pks.get(customer),
        customer_samian_id=customer,
        warehouse_id=warehouse,
        warehouse=_s(item.get("__warehouse_id_value"), 255),
        samian_warehouse_id=warehouse_pks.get(warehouse),
        department_id=_int(item.get("departmentinfo_id")),
        department=_s(item.get("__departmentinfo_id_value"), 255),
        cash_id=_int(item.get("cashes_id")),
        cash_name=_s(item.get("__cashes_id_value"), 255),
        cashier_person_id=_int(item.get("cashierpersoninfo_id")),
        cashier_name=_s(item.get("__cashierpersoninfo_id_value"), 255),
        status_id=_int(item.get("transactionstatus_id")),
        status=_s(item.get("__transactionstatus_id_value"), 128),
        total_amount=_money(item.get("tramount")),
        total_discount=_money(item.get("trdiscountcost")),
        total_vat=_money(item.get("trvatcost")),
        net_amount=_money(item.get("trnetamount")),
        rounding_discount=_money(item.get("roundingdiscount")),
        transaction_score=_money(item.get("transactionscore")),
        is_first_buy=bool(item.get("firstbuy")),
        year_info_id=_int(item.get("yearinfo_id")),
        delivery_address=_s(item.get("deliveryaddress")),
    )


def sync_transactions(client: SamianClient, customer_pks: dict[int, int]) -> list[int]:
    """Invoices of these Samian customers. Returns their Samian ids."""
    warehouse_pks = _warehouse_pks()
    instances = [
        _transaction(item, customer_pks, warehouse_pks)
        for item in _iter_matching(client, "retail/postransaction", "postransaction_id", "poscustomer_id", list(customer_pks))
    ]
    _upsert(SamianSalesTransaction, instances, TRANSACTION_FIELDS)
    return [t.samian_id for t in instances]


def sync_rows(client: SamianClient, transaction_ids: list[int]) -> int:
    """Line items of these invoices, with the invoice date and links to barcode and product."""
    txs = {
        sid: (pk, dt, d, wh, whpk)
        for sid, pk, dt, d, wh, whpk in SamianSalesTransaction.objects.filter(samian_id__in=transaction_ids)
        .values_list("samian_id", "pk", "transaction_date", "report_date", "warehouse_id", "samian_warehouse_id")
    }
    items = list(_iter_matching(client, "retail/postransactionitems", "postransactionitems_id", "postransaction_id", transaction_ids))
    barcodes = dict(
        SamianBarcode.objects.filter(samian_id__in={_int(i.get("barcodemain_id")) for i in items})
        .values_list("samian_id", "pk")
    )
    products = dict(
        SamianProduct.objects.filter(samian_id__in={_int(i.get("productmain_id")) for i in items})
        .values_list("samian_id", "pk")
    )
    instances = []
    for item in items:
        tx_pk, tx_dt, tx_day, wh, wh_pk = txs.get(_int(item.get("postransaction_id")), (None,) * 5)
        qty = _dec(item.get("qty"), "1")
        unit_before = _money(item.get("itemprice"))
        discount = _money(item.get("discountcost"))
        instances.append(SamianSalesRow(
            samian_id=_int(item.get("postransactionitems_id") or item.get("id")),
            transaction_id=tx_pk,
            transaction_samian_id=_int(item.get("postransaction_id")),
            samian_barcode_id=barcodes.get(_int(item.get("barcodemain_id"))),
            samian_product_id=products.get(_int(item.get("productmain_id"))),
            barcode=_s(item.get("itembarcode") or item.get("__barcodemain_id_value"), 255),
            barcodemain_id=_int(item.get("barcodemain_id")),
            productmain_id=_int(item.get("productmain_id")),
            subcode=_s(item.get("subcode"), 128),
            item_name=_s(item.get("itemname") or item.get("__productmain_id_value"), 512),
            transaction_date=tx_dt,
            report_date=tx_day,
            quantity=qty,
            unit_price_before_discount=unit_before,
            unit_price=_money(item.get("saleprice")),
            discount_percent=_dec(item.get("finaldiscount")),
            discount_amount=discount,
            vat_amount=_money(item.get("vatcost")),
            gross_amount=_money(item.get("tritemamount")),
            line_revenue=_money(item.get("tritemnetamount")),
            sale_person_id=_int(item.get("salepersoninfo_id")),
            sale_person_name=_s(item.get("__salepersoninfo_id_value"), 255),
            warehouse_id=_int(item.get("itemwarehouse_id")) or wh,
            samian_warehouse_id=wh_pk,
            is_return=bool(item.get("isreturn")),
            is_gifted=bool(item.get("isgifted")),
        ))
    _upsert(SamianSalesRow, instances, ROW_FIELDS)
    return len(instances)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def sync_site_customers(
    client: SamianClient | None = None,
    *,
    customer_ids: list[int] | None = None,
    all_rows: bool = False,
) -> dict[str, Any]:
    """
    Read Samian data for site customers: the customer, addresses, invoices and
    invoice rows. Rows are fetched only for invoices that have none stored yet
    (Samian invoices do not change once closed) unless all_rows is set.
    """
    from apps.website.models import Customer

    client = client or get_samian_client()
    log = _log_start(SamianSyncLog.Action.SYNC_CUSTOMERS)
    try:
        site = Customer.objects.filter(is_deleted=False)
        if customer_ids:
            site = site.filter(id__in=customer_ids)
        site = list(site)
        mobiles = sorted({normalize_mobile(c.cellphone) for c in site} - {""})

        found = sync_customers(client, mobiles)
        linked = link_site_customers(site)
        customer_pks = dict(SamianCustomer.objects.filter(mobile__in=mobiles).values_list("samian_id", "pk"))
        addresses = sync_addresses(client, customer_pks)
        tx_ids = sync_transactions(client, customer_pks)
        if not all_rows:
            done = set(SamianSalesRow.objects.filter(transaction_samian_id__in=tx_ids).values_list("transaction_samian_id", flat=True))
            tx_ids = [t for t in tx_ids if t not in done]
        rows = sync_rows(client, tx_ids)
        return _log_finish(log, total=len(site), synced=linked, details={
            "samian_customers": found, "linked": linked, "addresses": addresses,
            "transactions": SamianSalesTransaction.objects.filter(customer_samian_id__in=customer_pks).count(),
            "rows_fetched": rows,
        })
    except Exception as exc:
        logger.exception("sync_site_customers failed")
        _log_finish(log, total=0, synced=0, error=exc)
        raise
