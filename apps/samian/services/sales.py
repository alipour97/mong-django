"""
Mong sales from Samian, for best sellers and customers' purchase history.

Samian is shared with Lebaza, and Mong products are sold in Lebaza branches
too; those sales count. So every sale row is scanned (keyset on
postransactionitems_id, so each run only reads rows added since the last one)
and a row is kept when its product is a Mong product, i.e. one synced into
SamianProduct (brands مانگ and توليد, settings.SAMIAN_BRAND_IDS). The invoice
headers of kept rows are then read by id.

    retail/postransactionitems  -> SamianSalesRow          (Mong items only)
    retail/postransaction       -> SamianSalesTransaction  (invoices with a Mong item)

Read only: nothing is written to Samian.
"""
from __future__ import annotations

import logging
from typing import Any

from django.db.models import Max
from django.utils import timezone

from apps.samian.client import SamianClient, get_samian_client
from apps.samian.models import (
    SamianBarcode,
    SamianCustomer,
    SamianProduct,
    SamianSalesRow,
    SamianSalesTransaction,
    SamianSyncLog,
)
from apps.samian.services.customers import _iter_matching, _upsert
from apps.samian.services.erp_sync import _dec, _dt, _int, _log_finish, _log_start, _money, _s, _warehouse_pks

logger = logging.getLogger(__name__)

PAGE = 1000

TRANSACTION_FIELDS = [
    "transaction_code", "transaction_unique_id", "transaction_date", "report_date", "order_date",
    "samian_customer", "customer_samian_id", "warehouse_id", "warehouse", "samian_warehouse",
    "department_id", "department", "cash_id", "cash_name", "cashier_person_id", "cashier_name",
    "status_id", "status", "total_amount", "total_discount", "total_vat", "net_amount",
    "rounding_discount", "transaction_score", "is_first_buy", "year_info_id", "delivery_address",
    "store_order_id", "store_user_id", "order_web_status_id", "order_web_status", "shipment_type_id", "shipment_type",
    "shipment_price", "delivery_person", "delivery_tel", "delivery_postal_code", "delivery_desc", "delivery_time",
    "updated_at",
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
        store_order_id=_int(item.get("storeorderid")),
        store_user_id=_int(item.get("storeuserid")),
        order_web_status_id=_int(item.get("orderwebstatus_id")),
        order_web_status=_s(item.get("__orderwebstatus_id_value"), 128),
        shipment_type_id=_int(item.get("shipmenttypes_id")),
        shipment_type=_s(item.get("__shipmenttypes_id_value"), 128),
        shipment_price=_money(item.get("shipmentprice")),
        delivery_person=_s(item.get("deliveryperson"), 255),
        delivery_tel=_s(item.get("deliverytel"), 64),
        delivery_postal_code=_s(item.get("deliverypostalcode"), 32),
        delivery_desc=_s(item.get("deliverydesc"), 512),
        delivery_time=_dt(item.get("deliverytime")),
    )



def _row(item: dict, products: dict[int, int], barcodes: dict[int, int]) -> SamianSalesRow:
    """Invoice pk, date and branch are filled in by _link_rows_to_transactions."""
    return SamianSalesRow(
        samian_id=_int(item.get("postransactionitems_id") or item.get("id")),
        transaction_samian_id=_int(item.get("postransaction_id")),
        samian_barcode_id=barcodes.get(_int(item.get("barcodemain_id"))),
        samian_product_id=products.get(_int(item.get("productmain_id"))),
        barcode=_s(item.get("itembarcode") or item.get("__barcodemain_id_value"), 255),
        barcodemain_id=_int(item.get("barcodemain_id")),
        productmain_id=_int(item.get("productmain_id")),
        subcode=_s(item.get("subcode"), 128),
        item_name=_s(item.get("itemname") or item.get("__productmain_id_value"), 512),
        quantity=_dec(item.get("qty"), "1"),
        unit_price_before_discount=_money(item.get("itemprice")),
        unit_price=_money(item.get("saleprice")),
        discount_percent=_dec(item.get("finaldiscount")),
        discount_amount=_money(item.get("discountcost")),
        vat_amount=_money(item.get("vatcost")),
        gross_amount=_money(item.get("tritemamount")),
        line_revenue=_money(item.get("tritemnetamount")),
        sale_person_id=_int(item.get("salepersoninfo_id")),
        sale_person_name=_s(item.get("__salepersoninfo_id_value"), 255),
        warehouse_id=_int(item.get("itemwarehouse_id")),
        is_return=bool(item.get("isreturn")),
        is_gifted=bool(item.get("isgifted")),
    )


def _link_rows_to_transactions(row_ids: list[int] | None = None) -> None:
    """Copy invoice pk, date and branch onto rows (headers are stored after the rows)."""
    rows = SamianSalesRow.objects.filter(transaction__isnull=True)
    if row_ids is not None:
        rows = rows.filter(samian_id__in=row_ids)
    pending = list(rows)
    txs = {
        t.samian_id: t
        for t in SamianSalesTransaction.objects.filter(samian_id__in={r.transaction_samian_id for r in pending})
    }
    for r in pending:
        t = txs.get(r.transaction_samian_id)
        if t:
            r.transaction_id, r.transaction_date, r.report_date = t.pk, t.transaction_date, t.report_date
            r.warehouse_id = r.warehouse_id or t.warehouse_id
            r.samian_warehouse_id = t.samian_warehouse_id
    SamianSalesRow.objects.bulk_update(
        pending, ["transaction", "transaction_date", "report_date", "warehouse_id", "samian_warehouse"], batch_size=1000
    )


def link_customers() -> int:
    """Attach invoices to the Samian customers we hold (site customers, see services/customers.py)."""
    pks = dict(SamianCustomer.objects.values_list("samian_id", "pk"))
    changed = []
    for t in SamianSalesTransaction.objects.filter(customer_samian_id__in=pks).only("pk", "customer_samian_id", "samian_customer"):
        if t.samian_customer_id != pks[t.customer_samian_id]:
            t.samian_customer_id = pks[t.customer_samian_id]
            changed.append(t)
    SamianSalesTransaction.objects.bulk_update(changed, ["samian_customer"], batch_size=1000)
    return len(changed)


def sync_sales(client: SamianClient | None = None, *, full: bool = False) -> dict[str, Any]:
    """
    Read sale rows added since the last run (all of them with full=True), keep
    the Mong ones and read their invoices. A full run also picks up rows of
    products that were synced into SamianProduct after their sale.
    """
    client = client or get_samian_client()
    log = _log_start(SamianSyncLog.Action.SYNC_SALES)
    try:
        after = 0 if full else (SamianSalesRow.objects.aggregate(m=Max("samian_id"))["m"] or 0)
        products = dict(SamianProduct.objects.values_list("samian_id", "pk"))
        scanned = kept = 0
        tx_ids: set[int] = set()
        page: list[dict] = []

        def flush():
            nonlocal kept
            barcodes = dict(
                SamianBarcode.objects.filter(samian_id__in={_int(i.get("barcodemain_id")) for i in page})
                .values_list("samian_id", "pk")
            )
            rows = [_row(i, products, barcodes) for i in page]
            _upsert(SamianSalesRow, rows, ROW_FIELDS)
            kept += len(rows)
            page.clear()

        for item in client.iter_keyset("retail/postransactionitems", key="postransactionitems_id", take_count=PAGE, after=after):
            scanned += 1
            if _int(item.get("productmain_id")) not in products:
                continue
            page.append(item)
            tx_ids.add(_int(item.get("postransaction_id")))
            if len(page) >= PAGE:
                flush()
        if page:
            flush()

        # Invoice headers: new ones, and on a full run all of them (status can change).
        wanted = tx_ids if full else tx_ids - set(SamianSalesTransaction.objects.filter(samian_id__in=tx_ids).values_list("samian_id", flat=True))
        customer_pks = dict(SamianCustomer.objects.values_list("samian_id", "pk"))
        warehouse_pks = _warehouse_pks()
        headers = [
            _transaction(item, customer_pks, warehouse_pks)
            for item in _iter_matching(client, "retail/postransaction", "postransaction_id", "postransaction_id", sorted(wanted))
        ]
        _upsert(SamianSalesTransaction, headers, TRANSACTION_FIELDS)
        _link_rows_to_transactions()
        return _log_finish(log, total=scanned, synced=kept, details={
            "after": after, "rows_scanned": scanned, "mong_rows": kept, "invoices_read": len(headers), "full": full,
        })
    except Exception as exc:
        logger.exception("sync_sales failed")
        _log_finish(log, total=0, synced=0, error=exc)
        raise
