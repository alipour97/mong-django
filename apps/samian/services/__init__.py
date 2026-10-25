"""
Services for interacting with specific Samian ERP functional modules:
- catalog: Products, colors, brands, departments
- inventory: Stock levels, warehouses, pricing
- media: Photo uploads, gallery binding/unbinding
- orders: Sales transactions, pos invoices, customers
"""
from .catalog import CatalogService
from .inventory import InventoryService
from .media import MediaService
from .orders import OrderService

__all__ = [
    "CatalogService",
    "InventoryService",
    "MediaService",
    "OrderService",
]
