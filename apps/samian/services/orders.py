"""
Orders & Sales Transactions Service for Samian ERP.

Handles:
- Retail sales transaction headers (/v2/retail/postransaction)
- Transaction line items (/v2/retail/postransactionitems)
- Single invoice details (/v2/retail/postransaction/{id})
- Customer records (/v2/retail/poscustomer)
- Submitting new sales invoices from online orders into Samian ERP
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Iterator
import uuid

from ..client import SamianClient, extract_records, get_samian_client, samian_filters
from ..exceptions import SamianAPIError, SamianValidationError

logger = logging.getLogger(__name__)


def normalize_mobile(value: Any) -> str:
    """Normalize Iranian phone number to 09xxxxxxxxx."""
    if not value:
        return ""
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if digits.startswith("0098"):
        digits = "0" + digits[4:]
    elif digits.startswith("98") and len(digits) == 12:
        digits = "0" + digits[2:]
    elif digits.startswith("9") and len(digits) == 10:
        digits = "0" + digits
    return digits


class OrderService:
    """
    High-level service for handling sales invoices, customer lookups, and order submission in Samian.
    """

    def __init__(self, client: SamianClient | None = None) -> None:
        self.client = client or get_samian_client()

    # -------------------------------------------------------------------------
    # 1. Sales Transactions Listing & Details
    # -------------------------------------------------------------------------
    def get_transactions_page(
        self,
        skip: int = 0,
        take_count: int = 100,
        sort: str = "transactiondate",
        sort_type: str = "desc",
        filters: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Fetch a single page of POS sales transaction headers.
        """
        params: dict[str, Any] = {"skip": skip, "takeCount": take_count}
        if sort:
            params["sort"] = sort
            params["sortType"] = sort_type
        if filters:
            params["filters"] = filters

        payload = self.client.manual_request("retail/postransaction", params=params)
        return extract_records(payload)

    def iter_transactions(
        self,
        take_count: int = 100,
        max_records: int | None = None,
        filters: str | None = None,
        sort: str = "transactiondate",
        sort_type: str = "desc",
    ) -> Iterator[dict[str, Any]]:
        """
        Stream POS transaction headers page by page.
        """
        extra_params = {"filters": filters} if filters else None
        return self.client.iter_paginated(
            "retail/postransaction",
            take_count=take_count,
            max_records=max_records,
            sort=sort,
            sort_type=sort_type,
            extra_params=extra_params,
        )

    def get_transaction(self, transaction_id: int) -> dict[str, Any]:
        """
        Fetch a complete invoice detail from /v2/retail/postransaction/{id}.
        """
        payload = self.client.manual_request(f"retail/postransaction/{transaction_id}")
        data = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
        if isinstance(data, dict):
            return data
        if isinstance(data, list) and data:
            return data[0]
        raise SamianAPIError(f"Transaction {transaction_id} not found: {payload}")

    # -------------------------------------------------------------------------
    # 2. Sales Line Items
    # -------------------------------------------------------------------------
    def get_transaction_items(
        self,
        transaction_id: int | None = None,
        skip: int = 0,
        take_count: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Fetch line items from /v2/retail/postransactionitems.
        """
        params: dict[str, Any] = {"skip": skip, "takeCount": take_count}
        if transaction_id is not None:
            params["filters"] = samian_filters(("postransaction_id", "=", int(transaction_id)))

        payload = self.client.manual_request("retail/postransactionitems", params=params)
        return extract_records(payload)

    def iter_transaction_items(
        self,
        transaction_id: int | None = None,
        take_count: int = 100,
        max_records: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """
        Stream line items page by page.
        """
        extra_params = None
        if transaction_id is not None:
            extra_params = {"filters": samian_filters(("postransaction_id", "=", int(transaction_id)))}

        return self.client.iter_paginated(
            "retail/postransactionitems",
            take_count=take_count,
            max_records=max_records,
            sort="postransactionitems_id",
            sort_type="asc",
            extra_params=extra_params,
        )

    # -------------------------------------------------------------------------
    # 3. Customer Operations
    # -------------------------------------------------------------------------
    def get_customers_page(
        self,
        skip: int = 0,
        take_count: int = 100,
        filters: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Fetch customer records from /v2/retail/poscustomer.
        """
        params: dict[str, Any] = {"skip": skip, "takeCount": take_count}
        if filters:
            params["filters"] = filters
        payload = self.client.manual_request("retail/poscustomer", params=params)
        return extract_records(payload)

    def find_customer_by_mobile(self, mobile: str) -> dict[str, Any] | None:
        """
        Search for a customer by normalized mobile phone.
        """
        clean_mobile = normalize_mobile(mobile)
        if not clean_mobile:
            return None

        # Filter by customer tel or cell
        filters = samian_filters(("cellphone", "=", clean_mobile))
        customers = self.get_customers_page(take_count=5, filters=filters)
        if customers:
            return customers[0]

        # Alternative field: tel1
        filters_tel = samian_filters(("tel1", "=", clean_mobile))
        customers = self.get_customers_page(take_count=5, filters=filters_tel)
        return customers[0] if customers else None

    # -------------------------------------------------------------------------
    # 4. Create Sales Invoice (Online Order Submission)
    # -------------------------------------------------------------------------
    def create_sales_invoice(self, order_data: dict[str, Any]) -> dict[str, Any]:
        """
        Submit a finalized online store order into Samian ERP POS transactions.

        order_data structure:
        {
            "customer_mobile": "09121234567",
            "customer_name": "سارا احمدی",
            "warehouse_id": 1,
            "items": [
                {
                    "barcodemain_id": 1405219911,
                    "barcode": "6260025528313",
                    "item_name": "SPORT PILATES BAND",
                    "qty": 1,
                    "price": 4590000,
                    "discount": 0
                }
            ],
            "shipping_amount": 1490000,
            "delivery_address": "تهران ...",
            "delivery_recipient": "سارا احمدی",
            "delivery_tel": "09121234567",
            "delivery_postal_code": "1938912345",
            "bank_tracking_code": "123456789",
            "web_order_id": 1052,
            "description": "خرید آنلاین از سایت منگ"
        }
        """
        items = order_data.get("items", [])
        if not items:
            raise SamianValidationError("Cannot create sales invoice without order items.")

        mobile = normalize_mobile(order_data.get("customer_mobile"))
        warehouse_id = int(order_data.get("warehouse_id", 1))

        # Look up or use existing customer ID if available
        customer = self.find_customer_by_mobile(mobile) if mobile else None
        pos_customer_id = customer.get("poscustomer_id") or customer.get("id") if customer else None

        # Calculate totals
        total_amount = sum(int(item.get("price", 0)) * int(item.get("qty", 1)) for item in items)
        total_discount = sum(int(item.get("discount", 0)) * int(item.get("qty", 1)) for item in items)
        net_amount = max(0, total_amount - total_discount)
        total_qty = sum(int(item.get("qty", 1)) for item in items)
        shipping_amount = int(order_data.get("shipping_amount", 0))

        tx_unique_id = str(uuid.uuid4()).upper()
        now_dt = datetime.now()
        tx_date_str = now_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]

        transaction_details = []
        for idx, item in enumerate(items, 1):
            unit_price = int(item.get("price", 0))
            qty = int(item.get("qty", 1))
            discount = int(item.get("discount", 0))
            item_net = max(0, (unit_price * qty) - (discount * qty))

            detail = {
                "BarcodeMain_ID": int(item.get("barcodemain_id", 0)),
                "ItemName": str(item.get("item_name", "")),
                "ItemBarcode": str(item.get("barcode", "")),
                "Qty": qty,
                "ItemPrice": unit_price,
                "SalePrice": unit_price,
                "SaleDiscount": discount,
                "VAT": 0,
                "TrItemAmount": unit_price * qty,
                "TrItemNetAmount": item_net,
                "DiscountCost": discount * qty,
                "VATCost": 0,
                "IsReturn": False,
                "IsGifted": False,
            }
            transaction_details.append(detail)

        delivery_info = [
            {
                "ShipmentCost": shipping_amount,
                "DeliveryAddress": str(order_data.get("delivery_address", "")),
                "DeliveryPerson": str(order_data.get("delivery_recipient", order_data.get("customer_name", ""))),
                "DeliveryTel": str(order_data.get("delivery_tel", mobile)),
                "DeliveryPostalCode": str(order_data.get("delivery_postal_code", "")),
                "DeliveryDesc": str(order_data.get("delivery_desc", "")),
            }
        ]

        trans_json = {
            "Cashes_ID": 1,
            "TransactionID": tx_unique_id,
            "TransactionDate": tx_date_str,
            "PosCustomer_ID": pos_customer_id,
            "WareHouse_ID": warehouse_id,
            "DepartmentInfo_ID": 0,
            "TrAmount": total_amount,
            "TrDiscountCost": total_discount,
            "TrNetAmount": net_amount,
            "TrQty": total_qty,
            "TransactionDesc": str(order_data.get("description", "")),
            "TransactionDetails": transaction_details,
            "TransactionDelivery": delivery_info,
            "StoreInformation": [
                {
                    "StoreOrderID": order_data.get("web_order_id"),
                    "StoreOrderType_ID": 1,
                }
            ],
        }

        payload = {
            "transactionuniqueid": tx_unique_id,
            "transactiondate": now_dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "warehouse_id": warehouse_id,
            "poscustomer_id": pos_customer_id,
            "tramount": total_amount,
            "trdiscountcost": total_discount,
            "trnetamount": net_amount,
            "transactiondesc": str(order_data.get("description", "")),
            "transjson": json.dumps(trans_json, ensure_ascii=False),
            "deliveryaddress": str(order_data.get("delivery_address", "")),
            "deliveryperson": str(order_data.get("delivery_recipient", "")),
            "deliverytel": str(order_data.get("delivery_tel", mobile)),
            "deliverypostalcode": str(order_data.get("delivery_postal_code", "")),
            "storeorderid": order_data.get("web_order_id"),
            "shipmentprice": shipping_amount,
        }

        logger.info(
            "Creating sales invoice in Samian ERP: unique_id=%s, total=%d, net=%d, items_count=%d",
            tx_unique_id, total_amount, net_amount, len(transaction_details)
        )

        response = self.client.manual_request(
            "retail/postransaction",
            method="POST",
            json_body=payload,
        )

        return {
            "status": "success",
            "transaction_unique_id": tx_unique_id,
            "response": response,
        }
