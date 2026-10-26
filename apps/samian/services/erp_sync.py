"""
ERP data sync: prices and inventory from Samian ERP.

Reads from the Samian ERP API and writes into local Samian* models.
Prices come from the «کنترل قیمت کالا» report; inventory from /v2/wm/stock.
Both can run together in a single pass (the user's preferred mode).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from django.db import models
from django.utils import timezone

from apps.samian.client import SamianClient, extract_records, samian_filters, get_samian_client
from apps.samian.models import (
    SamianBarcode,
    SamianInventory,
    SamianProduct,
    SamianSyncLog,
    SamianWarehouse,
)

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 1000
INVENTORY_SAFETY_MARGIN = timedelta(minutes=5)

# ---------------------------------------------------------------------------
# Price report constants
# ---------------------------------------------------------------------------

PRICE_REPORT_PATH = "report/161deff3-c9d2-46cd-a7e8-7d39e5543fff"

PRICE_REPORT_COLUMNS = {
    "productmain_id": "94296",   # «شناسه كالا»
    "subcode": "1094733",        # «كد فرعي»
    "name": "94295",             # «عنوان»
    "buy_price": "94299",        # «قيمت خريد»
    "sale_price": "94300",       # «قيمت فروش»
    "price_list": "94303",       # «عنوان ليست قيمت»
    "list_price": "94304",       # «قيمت در ليست»
    "list_discount": "94305",    # «تخفيف در ليست»
}


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------

def _s(value: Any, max_length: int | None = None) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"none", "null", "nan"}:
        return ""
    return text[:max_length] if max_length else text


def _int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _dec(value: Any, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _money(value: Any) -> int:
    return int(_dec(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _money_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return _money(value)


def _dt(value: Any):
    text = _s(value)
    if not text:
        return None
    from django.utils.dateparse import parse_datetime
    parsed = parse_datetime(text.replace(" ", "T"))
    if parsed is None:
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _chunks(iterable, size):
    buffer = []
    for item in iterable:
        buffer.append(item)
        if len(buffer) >= size:
            yield buffer
            buffer = []
    if buffer:
        yield buffer


# ---------------------------------------------------------------------------
# Sync log helpers
# ---------------------------------------------------------------------------

def _log_start(action: str) -> SamianSyncLog:
    return SamianSyncLog.objects.create(action=action, status=SamianSyncLog.Status.STARTED)


def _log_finish(
    log: SamianSyncLog,
    *,
    total: int,
    synced: int,
    details: dict[str, Any] | None = None,
    error: Exception | None = None,
) -> dict[str, Any]:
    now = timezone.now()
    payload = {
        "total": total,
        "synced": synced,
        "duration_seconds": round((now - log.started_at).total_seconds(), 2),
    }
    payload.update(details or {})

    log.status = SamianSyncLog.Status.FAILED if error else SamianSyncLog.Status.SUCCESS
    log.finished_at = now
    log.records_read = total
    log.records_upserted = synced
    log.details = payload
    if error:
        log.error_message = f"{type(error).__name__}: {error}"[:4000]
    log.save()
    return payload


def _warehouse_pks() -> dict[int, int]:
    return dict(SamianWarehouse.objects.values_list("samian_id", "pk"))


# ---------------------------------------------------------------------------
# 0. Barcode sync — prerequisite for inventory
# ---------------------------------------------------------------------------

def sync_barcodes(
    client: SamianClient | None = None,
    *,
    take_count: int = 500,
    max_records: int | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    stdout=None,
) -> dict[str, Any]:
    """Sync barcodes from /v2/product/barcodemain into SamianBarcode."""
    client = client or get_samian_client()
    log = _log_start(SamianSyncLog.Action.SYNC_BARCODES)
    try:
        product_pk_by_id = dict(SamianProduct.objects.values_list("samian_id", "pk"))
        total = synced = requests_made = 0
        skip = 0

        while True:
            remaining = None if max_records is None else max_records - total
            if remaining is not None and remaining <= 0:
                break
            actual_take = take_count if remaining is None else min(take_count, remaining)

            page = extract_records(
                client.manual_request(
                    "product/barcodemain",
                    params={
                        "skip": skip,
                        "takeCount": actual_take,
                        "sort": "barcodemain_id",
                        "sortType": "asc",
                    },
                )
            )
            requests_made += 1
            if not page:
                break
            total += len(page)

            instances = []
            for item in page:
                sid = _int(item.get("barcodemain_id") or item.get("id"))
                if not sid:
                    continue
                pmid = _int(item.get("productmain_id"))
                instances.append(
                    SamianBarcode(
                        samian_id=sid,
                        barcode=_s(item.get("kbarcode"), 255),
                        subcode=_s(item.get("k_bar_code"), 128),
                        samian_product_id=product_pk_by_id.get(pmid),
                        productmain_id=pmid,
                        color=_s(item.get("__colorinfo_id_value") or item.get("colornew"), 255),
                        color_en=_s(item.get("colornewen"), 255),
                        size=_s(item.get("__sizeinfo_id_value") or item.get("sizenew"), 128),
                        season_code=_s(item.get("seasoncodenew"), 64),
                        material_desc=_s(item.get("materialdesc"), 255),
                        sku_code=_s(item.get("skucode"), 128),
                        buy_price=_money(item.get("barcodebuyprice")),
                        sale_price=_money(item.get("barcodesaleprice")),
                        end_user_price=_money_or_none(item.get("enduserprice")),
                        is_active=bool(item.get("isactive", True)),
                        sale_status_id=_int(item.get("salestatus_id")),
                        sale_status=_s(item.get("__salestatus_id_value"), 128),
                    )
                )

            if instances:
                for batch in _chunks(instances, batch_size):
                    SamianBarcode.objects.bulk_create(
                        batch,
                        update_conflicts=True,
                        unique_fields=["samian_id"],
                        update_fields=[
                            "barcode", "subcode", "samian_product", "productmain_id",
                            "color", "color_en", "size", "season_code",
                            "material_desc", "sku_code", "buy_price", "sale_price",
                            "end_user_price", "is_active", "sale_status_id",
                            "sale_status", "updated_at",
                        ],
                    )
            synced += len(instances)

            if stdout and requests_made % 20 == 0:
                stdout.write(f"  بارکد: {requests_made} درخواست، {synced} ردیف...")

            if len(page) < actual_take:
                break
            skip += actual_take

        return _log_finish(log, total=total, synced=synced, details={"requests": requests_made})

    except Exception as exc:
        logger.exception("sync_barcodes failed")
        _log_finish(log, total=total, synced=synced, error=exc)
        raise


# ---------------------------------------------------------------------------
# 1. Price sync — Samian report «کنترل قیمت کالا»
# ---------------------------------------------------------------------------

def sync_prices(
    client: SamianClient | None = None,
    *,
    take_count: int = 1000,
    max_records: int | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    stdout=None,
) -> dict[str, Any]:
    """
    Read buy/sale prices from the Samian price report and update SamianProduct.
    Only rows where the price actually changed are written to the DB.
    """
    client = client or get_samian_client()
    log = _log_start(SamianSyncLog.Action.SYNC_PRICES)
    try:
        cols = PRICE_REPORT_COLUMNS
        now = timezone.now()
        seen: set[int] = set()
        total = synced = unchanged = unknown = requests_made = 0
        skip = 0

        while True:
            take = take_count if max_records is None else min(take_count, max_records - (total + len(seen) - len(seen)))
            remaining = None if max_records is None else max_records - total
            if remaining is not None and remaining <= 0:
                break
            actual_take = take_count if remaining is None else min(take_count, remaining)

            page = extract_records(
                client.manual_request(
                    PRICE_REPORT_PATH,
                    params={
                        "skip": skip,
                        "takeCount": actual_take,
                        "sort": cols["productmain_id"],
                        "sortType": "asc",
                    },
                    timeout=180,
                )
            )
            requests_made += 1
            if not page:
                break

            if requests_made == 1:
                missing = [name for name, key in cols.items() if key not in page[0]]
                if missing:
                    raise RuntimeError(
                        f"Samian price report columns changed; missing {missing}. "
                        f"Columns now: {sorted(page[0].keys())}"
                    )

            by_product: dict[int, tuple[int | None, int | None]] = {}
            for row in page:
                pid = _int(row.get(cols["productmain_id"]))
                if pid is None or pid in seen:
                    continue
                seen.add(pid)
                buy = _money_or_none(row.get(cols["buy_price"]))
                sale = _money_or_none(row.get(cols["sale_price"]))
                by_product[pid] = (buy, sale)
            total += len(by_product)

            to_update = []
            for product in SamianProduct.objects.filter(samian_id__in=by_product).only(
                "pk", "samian_id", "buy_price", "sale_price", "price_synced_at"
            ):
                new_buy, new_sale = by_product[product.samian_id]
                if product.buy_price == new_buy and product.sale_price == new_sale:
                    unchanged += 1
                    product.price_synced_at = now
                    to_update.append(product)
                    continue
                product.buy_price = new_buy
                product.sale_price = new_sale
                product.price_synced_at = now
                to_update.append(product)

            if to_update:
                SamianProduct.objects.bulk_update(
                    to_update, ["buy_price", "sale_price", "price_synced_at"], batch_size=batch_size
                )
            synced += len(to_update)
            unknown += len(by_product) - len(to_update)

            if stdout and requests_made % 10 == 0:
                stdout.write(f"  قیمت: {requests_made} درخواست، {synced} محصول بروزرسانی شد...")

            if len(page) < actual_take:
                break
            skip += actual_take

        result = _log_finish(
            log, total=total, synced=synced,
            details={
                "unchanged": unchanged,
                "unknown_products": unknown,
                "requests": requests_made,
            },
        )
        return result

    except Exception as exc:
        logger.exception("sync_prices failed")
        _log_finish(log, total=total, synced=synced, error=exc)
        raise


# ---------------------------------------------------------------------------
# 2. Inventory sync — /v2/wm/stock
# ---------------------------------------------------------------------------

def sync_inventory(
    client: SamianClient | None = None,
    *,
    full: bool = False,
    take_count: int = 5000,
    max_records: int | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    stdout=None,
) -> dict[str, Any]:
    """
    Refresh SamianInventory from /v2/wm/stock.
    Incremental by default: only rows changed since last sync.
    """
    client = client or get_samian_client()
    log = _log_start(SamianSyncLog.Action.SYNC_INVENTORY)
    try:
        filters = None
        mark = None
        if not full:
            newest = SamianInventory.objects.aggregate(m=models.Max("source_updated_at"))["m"]
            if newest:
                mark = newest - INVENTORY_SAFETY_MARGIN
                filters = samian_filters(("updatedate", ">=", mark))
            else:
                full = True

        warehouse_pks = _warehouse_pks()
        barcode_pk_cache: dict[int, int] = {}
        seen_keys: set[tuple[int, int]] = set()
        total = synced = skipped = requests_made = 0
        skip = 0

        while True:
            remaining = None if max_records is None else max_records - total
            if remaining is not None and remaining <= 0:
                break
            actual_take = take_count if remaining is None else min(take_count, remaining)

            params: dict[str, Any] = {
                "skip": skip,
                "takeCount": actual_take,
                "sort": "barcodemain_id",
                "sortType": "asc",
            }
            if filters:
                params["filters"] = filters

            page = extract_records(
                client.manual_request("wm/stock", params=params, timeout=120)
            )
            requests_made += 1
            if not page:
                break
            total += len(page)

            needed_barcode_ids = {_int(i.get("barcodemain_id")) for i in page} - {None}
            missing_ids = needed_barcode_ids - barcode_pk_cache.keys()
            if missing_ids:
                barcode_pk_cache.update(
                    SamianBarcode.objects.filter(samian_id__in=missing_ids).values_list("samian_id", "pk")
                )

            instances: list[SamianInventory] = []
            for item in page:
                barcodemain_id = _int(item.get("barcodemain_id"))
                warehouse_id = _int(item.get("warehouse_id"))
                if barcodemain_id is None or warehouse_id is None:
                    skipped += 1
                    continue

                barcode_pk = barcode_pk_cache.get(barcodemain_id)
                if not barcode_pk:
                    skipped += 1
                    continue

                key = (barcodemain_id, warehouse_id)
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                instances.append(
                    SamianInventory(
                        samian_barcode_id=barcode_pk,
                        barcodemain_id=barcodemain_id,
                        samian_warehouse_id=warehouse_pks.get(warehouse_id),
                        warehouse_id=warehouse_id,
                        warehouse=_s(item.get("__warehouse_id_value"), 255),
                        qty=_dec(item.get("mojodi")),
                        qty_reserved=_dec(item.get("mojodireserve")),
                        source_updated_at=_dt(item.get("updatedate")),
                    )
                )

            if instances:
                for batch in _chunks(instances, batch_size):
                    SamianInventory.objects.bulk_create(
                        batch,
                        update_conflicts=True,
                        unique_fields=["samian_barcode", "warehouse_id"],
                        update_fields=[
                            "barcodemain_id", "warehouse",
                            "samian_warehouse", "qty", "qty_reserved",
                            "source_updated_at",
                        ],
                    )
            synced += len(instances)

            if stdout and requests_made % 5 == 0:
                stdout.write(f"  موجودی: {requests_made} درخواست، {synced} ردیف بروزرسانی شد...")

            if len(page) < actual_take:
                break
            skip += actual_take

        result = _log_finish(
            log, total=total, synced=synced,
            details={
                "skipped_unknown_barcode": skipped,
                "requests": requests_made,
                "mode": "full" if full else "incremental",
                "since": timezone.localtime(mark).isoformat() if mark else None,
            },
        )
        return result

    except Exception as exc:
        logger.exception("sync_inventory failed")
        _log_finish(log, total=total, synced=synced, error=exc)
        raise


# ---------------------------------------------------------------------------
# 3. Combined price + inventory sync
# ---------------------------------------------------------------------------

def sync_prices_and_inventory(
    client: SamianClient | None = None,
    *,
    full: bool = False,
    price_take_count: int = 1000,
    inventory_take_count: int = 5000,
    max_records: int | None = None,
    stdout=None,
) -> dict[str, Any]:
    """
    Run price and inventory sync together in one pass.
    This is the default mode requested by the user.
    """
    client = client or get_samian_client()
    log = _log_start(SamianSyncLog.Action.SYNC_PRICES_INVENTORY)
    t0 = time.time()
    try:
        if stdout:
            stdout.write("شروع سینک قیمت‌ها...")
        price_result = sync_prices(
            client, take_count=price_take_count, max_records=max_records, stdout=stdout,
        )

        if stdout:
            stdout.write("شروع سینک بارکدها (پیش‌نیاز موجودی)...")
        barcode_result = sync_barcodes(
            client, max_records=max_records, stdout=stdout,
        )

        if stdout:
            stdout.write("شروع سینک موجودی...")
        inv_result = sync_inventory(
            client, full=full, take_count=inventory_take_count, max_records=max_records, stdout=stdout,
        )

        duration = round(time.time() - t0, 2)
        combined = {
            "prices": price_result,
            "barcodes": barcode_result,
            "inventory": inv_result,
            "duration_seconds": duration,
        }

        log.status = SamianSyncLog.Status.SUCCESS
        log.finished_at = timezone.now()
        log.records_read = price_result.get("total", 0) + inv_result.get("total", 0)
        log.records_upserted = price_result.get("synced", 0) + inv_result.get("synced", 0)
        log.details = combined
        log.save()
        return combined

    except Exception as exc:
        logger.exception("sync_prices_and_inventory failed")
        log.status = SamianSyncLog.Status.FAILED
        log.finished_at = timezone.now()
        log.error_message = f"{type(exc).__name__}: {exc}"[:4000]
        log.save()
        raise
