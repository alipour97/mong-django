"""
Inventory & Pricing Service for Samian ERP.

Handles:
- Warehouse inventory levels (/v2/wm/stock)
- Warehouse definitions (/v2/accounting/warehouse)
- Price lists and real-time inventory queries (/v2/pricing/pricelist)
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Iterator

from ..client import SamianClient, extract_records, get_samian_client, samian_filters

logger = logging.getLogger(__name__)


class InventoryService:
    """
    High-level service for querying stock and warehouse data from Samian ERP.
    """

    def __init__(self, client: SamianClient | None = None) -> None:
        self.client = client or get_samian_client()

    # -------------------------------------------------------------------------
    # 1. Stock (/v2/wm/stock)
    # -------------------------------------------------------------------------
    def get_stock_page(
        self,
        skip: int = 0,
        take_count: int = 5000,
        warehouse_id: int | None = None,
        updated_since: datetime | str | None = None,
        filters: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Fetch a single page of inventory stock records.
        """
        params: dict[str, Any] = {
            "skip": skip,
            "takeCount": take_count,
            "sort": "barcodemain_id",
            "sortType": "asc",
        }

        # Build composite filters if not passed directly
        if not filters:
            conds: list[tuple[str, str, Any]] = []
            if warehouse_id is not None:
                conds.append(("warehouse_id", "=", int(warehouse_id)))
            if updated_since is not None:
                conds.append(("updatedate", ">=", updated_since))
            if conds:
                filters = samian_filters(*conds)

        if filters:
            params["filters"] = filters

        payload = self.client.manual_request("wm/stock", params=params)
        return extract_records(payload)

    def iter_stock(
        self,
        take_count: int = 5000,
        warehouse_id: int | None = None,
        updated_since: datetime | str | None = None,
        max_records: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """
        Stream inventory stock rows page by page.
        """
        conds: list[tuple[str, str, Any]] = []
        if warehouse_id is not None:
            conds.append(("warehouse_id", "=", int(warehouse_id)))
        if updated_since is not None:
            conds.append(("updatedate", ">=", updated_since))

        filters = samian_filters(*conds) if conds else None
        extra_params = {"filters": filters} if filters else None

        return self.client.iter_paginated(
            "wm/stock",
            take_count=take_count,
            max_records=max_records,
            sort="barcodemain_id",
            sort_type="asc",
            extra_params=extra_params,
        )

    def get_stock_for_barcode(
        self,
        barcodemain_id: int,
        warehouse_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get all stock entries for a specific barcodemain_id across warehouses.
        """
        conds: list[tuple[str, str, Any]] = [("barcodemain_id", "=", int(barcodemain_id))]
        if warehouse_id is not None:
            conds.append(("warehouse_id", "=", int(warehouse_id)))

        filters = samian_filters(*conds)
        return self.get_stock_page(skip=0, take_count=100, filters=filters)

    def get_total_stock_for_barcode(
        self,
        barcodemain_id: int,
        warehouse_id: int | None = None,
    ) -> int:
        """
        Calculate total available stock quantity for a barcode.
        """
        rows = self.get_stock_for_barcode(barcodemain_id, warehouse_id=warehouse_id)
        total = 0
        for row in rows:
            qty = row.get("count") or row.get("qty") or row.get("stock") or 0
            try:
                total += int(float(qty))
            except (ValueError, TypeError):
                pass
        return max(0, total)

    # -------------------------------------------------------------------------
    # 2. Warehouses (/v2/accounting/warehouse)
    # -------------------------------------------------------------------------
    def get_warehouses(self, page_size: int = 500) -> list[dict[str, Any]]:
        """
        Fetch all warehouses from Samian ERP.
        """
        payload = self.client.manual_request(
            "accounting/warehouse",
            params={"skip": 0, "takeCount": page_size, "sort": "warehouse_id", "sortType": "asc"},
        )
        return extract_records(payload)

    # -------------------------------------------------------------------------
    # 3. Price Lists (/v2/pricing/pricelist)
    # -------------------------------------------------------------------------
    def get_price_lists(self, page_size: int = 500) -> list[dict[str, Any]]:
        """
        Fetch active price lists from Samian ERP.
        """
        payload = self.client.manual_request(
            "pricing/pricelist",
            params={"skip": 0, "takeCount": page_size},
        )
        return extract_records(payload)

    def get_price_list_items(
        self,
        pricelist_id: int,
        skip: int = 0,
        take_count: int = 1000,
    ) -> list[dict[str, Any]]:
        """
        Fetch items and discounts belonging to a price list.
        """
        filters = samian_filters(("pricelist_id", "=", int(pricelist_id)))
        payload = self.client.manual_request(
            "pricing/pricelistitems",
            params={"skip": skip, "takeCount": take_count, "filters": filters},
        )
        return extract_records(payload)
