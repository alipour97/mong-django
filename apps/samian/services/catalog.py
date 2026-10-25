"""
Catalog Service for Samian ERP.

Handles:
- Product master records (/v2/product/productmain)
- Color definitions and gallery links (/v2/product/colors)
- Brands (/v2/product/codingbrand)
- Department hierarchy and 3-tier paths (/v2/product/codingdepartment)
- Barcodes and SKU mapping (/v2/product/barcodemain)
"""
from __future__ import annotations

import logging
from typing import Any, Iterator

from ..client import SamianClient, extract_records, get_samian_client, samian_filters

logger = logging.getLogger(__name__)


class CatalogService:
    """
    High-level service for interacting with Samian ERP Catalog endpoints.
    """

    def __init__(self, client: SamianClient | None = None) -> None:
        self.client = client or get_samian_client()

    # -------------------------------------------------------------------------
    # 1. Product Master (productmain)
    # -------------------------------------------------------------------------
    def get_products_page(
        self,
        skip: int = 0,
        take_count: int = 100,
        sort: str = "createdate",
        sort_type: str = "desc",
        filters: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Fetch a single page of product master records from /v2/product/productmain.
        """
        params: dict[str, Any] = {"skip": skip, "takeCount": take_count}
        if sort:
            params["sort"] = sort
            params["sortType"] = sort_type
        if filters:
            params["filters"] = filters

        payload = self.client.manual_request("product/productmain", params=params)
        return extract_records(payload)

    def iter_products(
        self,
        take_count: int = 100,
        max_records: int | None = None,
        filters: str | None = None,
        sort: str = "createdate",
        sort_type: str = "desc",
    ) -> Iterator[dict[str, Any]]:
        """
        Stream all product master records page by page.
        """
        extra_params = {"filters": filters} if filters else None
        return self.client.iter_paginated(
            "product/productmain",
            take_count=take_count,
            max_records=max_records,
            sort=sort,
            sort_type=sort_type,
            extra_params=extra_params,
        )

    def get_product(self, product_id: int) -> dict[str, Any]:
        """
        Fetch a single product master record by productmain_id.
        """
        payload = self.client.manual_request(f"product/productmain/{product_id}")
        records = extract_records(payload)
        return records[0] if records else (payload if isinstance(payload, dict) else {})

    # -------------------------------------------------------------------------
    # 2. Product Colors (colors)
    # -------------------------------------------------------------------------
    def get_colors_page(
        self,
        skip: int = 0,
        take_count: int = 100,
        sort: str = "id",
        sort_type: str = "desc",
        filters: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Fetch a single page of product color records from /v2/product/colors.
        """
        params: dict[str, Any] = {"skip": skip, "takeCount": take_count}
        if sort:
            params["sort"] = sort
            params["sortType"] = sort_type
        if filters:
            params["filters"] = filters

        payload = self.client.manual_request("product/colors", params=params)
        return extract_records(payload)

    def iter_colors(
        self,
        take_count: int = 100,
        max_records: int | None = None,
        filters: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """
        Stream all product color records page by page.
        """
        extra_params = {"filters": filters} if filters else None
        return self.client.iter_paginated(
            "product/colors",
            take_count=take_count,
            max_records=max_records,
            sort="id",
            sort_type="desc",
            extra_params=extra_params,
        )

    def get_color(self, color_id: int) -> dict[str, Any]:
        """
        Fetch a single product color record by color ID.
        """
        payload = self.client.manual_request(f"product/colors/{color_id}")
        records = extract_records(payload)
        return records[0] if records else (payload if isinstance(payload, dict) else {})

    def get_colors_for_product(self, productmain_id: int) -> list[dict[str, Any]]:
        """
        Fetch all color records associated with a specific productmain_id.
        """
        filters = samian_filters(("productmain_id", "=", productmain_id))
        return self.get_colors_page(skip=0, take_count=500, filters=filters)

    # -------------------------------------------------------------------------
    # 3. Barcodes (barcodemain)
    # -------------------------------------------------------------------------
    def get_barcodes_page(
        self,
        skip: int = 0,
        take_count: int = 100,
        filters: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Fetch a page of barcode records from /v2/product/barcodemain.
        """
        params: dict[str, Any] = {"skip": skip, "takeCount": take_count}
        if filters:
            params["filters"] = filters
        payload = self.client.manual_request("product/barcodemain", params=params)
        return extract_records(payload)

    def iter_barcodes(
        self,
        take_count: int = 100,
        max_records: int | None = None,
        filters: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """
        Stream all barcodes page by page.
        """
        extra_params = {"filters": filters} if filters else None
        return self.client.iter_paginated(
            "product/barcodemain",
            take_count=take_count,
            max_records=max_records,
            sort="barcodemain_id",
            sort_type="asc",
            extra_params=extra_params,
        )

    def get_barcode_by_code(self, barcode: str) -> dict[str, Any] | None:
        """
        Look up a barcode by its exact string code (kbarcode).
        """
        filters = samian_filters(("kbarcode", "=", str(barcode).strip()))
        results = self.get_barcodes_page(take_count=5, filters=filters)
        return results[0] if results else None

    # -------------------------------------------------------------------------
    # 4. Brands & Departments
    # -------------------------------------------------------------------------
    def get_brands(self, page_size: int = 5000) -> list[dict[str, Any]]:
        """
        Fetch all brand definitions from /v2/product/codingbrand.
        """
        payload = self.client.manual_request(
            "product/codingbrand",
            params={"skip": 0, "takeCount": page_size, "sort": "codingbrand_id", "sortType": "asc"},
        )
        return extract_records(payload)

    def get_departments(self, page_size: int = 5000) -> list[dict[str, Any]]:
        """
        Fetch all department nodes from /v2/product/codingdepartment.
        """
        payload = self.client.manual_request(
            "product/codingdepartment",
            params={"skip": 0, "takeCount": page_size, "sort": "codingdepartment_id", "sortType": "asc"},
        )
        return extract_records(payload)

    def get_department_paths(self) -> dict[int, tuple[str, str, str]]:
        """
        Build a map: department_id -> (department1, department2, department3).
        
        Walking ancestors in Samian's tree:
        - level 0: root category (e.g. زنانه) -> department1
        - level 1: sub category (e.g. پایین تنه) -> department2
        - level 2: leaf title (e.g. شلوار) -> department3
        """
        nodes = self.get_departments()
        by_id: dict[int, dict[str, Any]] = {}
        for node in nodes:
            nid = node.get("codingdepartment_id") or node.get("id")
            if nid:
                by_id[int(nid)] = node

        paths: dict[int, tuple[str, str, str]] = {}
        for nid, node in by_id.items():
            chain: list[str] = [str(node.get("title") or "").strip()]
            curr = node
            while True:
                parent_id = curr.get("codingparentdepartment_id")
                if not parent_id or int(parent_id) not in by_id:
                    break
                curr = by_id[int(parent_id)]
                chain.insert(0, str(curr.get("title") or "").strip())

            d1 = chain[0] if len(chain) > 0 else ""
            d2 = chain[1] if len(chain) > 1 else ""
            d3 = chain[-1] if len(chain) > 2 else (chain[1] if len(chain) == 2 else "")
            paths[nid] = (d1, d2, d3)

        return paths
