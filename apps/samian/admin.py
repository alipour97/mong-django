"""
Django Admin registration for Samian ERP models.
"""
from django.contrib import admin
from .models import (
    SamianBrand,
    SamianDepartment,
    SamianWarehouse,
    SamianProduct,
    SamianProductColor,
    SamianBarcode,
    SamianInventory,
    SamianCustomer,
    SamianCustomerAddress,
    SamianSalesTransaction,
    SamianSalesRow,
    SamianPriceList,
    SamianPriceListItem,
    SamianSyncLog,
)


@admin.register(SamianBrand)
class SamianBrandAdmin(admin.ModelAdmin):
    list_display = ("samian_id", "title", "title_en", "brand_code", "erp_code")
    search_fields = ("title", "title_en", "brand_code")
    list_filter = ("parent",)


@admin.register(SamianDepartment)
class SamianDepartmentAdmin(admin.ModelAdmin):
    list_display = ("samian_id", "title", "level", "department1", "department2", "department3")
    search_fields = ("title", "department1", "department2", "department3")
    list_filter = ("level",)


@admin.register(SamianWarehouse)
class SamianWarehouseAdmin(admin.ModelAdmin):
    list_display = ("samian_id", "title", "department_name", "is_active", "is_commercial")
    search_fields = ("title", "department_name")
    list_filter = ("is_active", "is_commercial")


@admin.register(SamianProduct)
class SamianProductAdmin(admin.ModelAdmin):
    list_display = ("samian_id", "subcode", "name", "brand_name", "department_name", "season_code", "sale_price", "is_active")
    search_fields = ("samian_id", "subcode", "name", "brand_name")
    list_filter = ("is_active", "is_saleable", "season_code", "sex")


@admin.register(SamianProductColor)
class SamianProductColorAdmin(admin.ModelAdmin):
    list_display = ("samian_id", "productmain_id", "color_name", "has_gallery", "subcode_hint")
    search_fields = ("samian_id", "productmain_id", "color_name", "subcode_hint")
    list_filter = ("has_gallery",)


@admin.register(SamianBarcode)
class SamianBarcodeAdmin(admin.ModelAdmin):
    list_display = ("samian_id", "barcode", "subcode", "productmain_id", "size", "color", "sale_price", "is_active")
    search_fields = ("barcode", "subcode", "size", "color")
    list_filter = ("is_active",)


@admin.register(SamianInventory)
class SamianInventoryAdmin(admin.ModelAdmin):
    list_display = ("barcodemain_id", "warehouse_id", "warehouse", "qty", "qty_reserved", "source_updated_at")
    search_fields = ("barcodemain_id",)
    list_filter = ("warehouse_id",)


class SamianCustomerAddressInline(admin.TabularInline):
    model = SamianCustomerAddress
    extra = 0
    fields = ("title", "address", "town", "postal_code", "receiver_name", "mobile", "is_default")
    readonly_fields = fields
    can_delete = False


@admin.register(SamianCustomer)
class SamianCustomerAdmin(admin.ModelAdmin):
    list_display = ("samian_id", "first_name", "last_name", "mobile", "club_level", "wallet_balance")
    search_fields = ("first_name", "last_name", "mobile", "national_code")
    list_filter = ("club_level", "is_active")
    inlines = [SamianCustomerAddressInline]


@admin.register(SamianCustomerAddress)
class SamianCustomerAddressAdmin(admin.ModelAdmin):
    list_display = ("samian_id", "customer", "title", "town", "postal_code", "is_default")
    search_fields = ("address", "mobile", "postal_code", "customer_samian_id")
    raw_id_fields = ("customer",)


class SamianSalesRowInline(admin.TabularInline):
    model = SamianSalesRow
    extra = 0
    readonly_fields = ("barcode", "item_name", "quantity", "unit_price", "discount_amount", "line_revenue")


@admin.register(SamianSalesTransaction)
class SamianSalesTransactionAdmin(admin.ModelAdmin):
    list_display = ("samian_id", "transaction_code", "transaction_date", "report_date", "total_amount", "net_amount", "status", "store_order_id")
    search_fields = ("transaction_code", "transaction_unique_id", "customer_samian_id")
    list_filter = ("status", "warehouse")
    raw_id_fields = ("samian_customer", "samian_warehouse")
    inlines = [SamianSalesRowInline]


@admin.register(SamianSalesRow)
class SamianSalesRowAdmin(admin.ModelAdmin):
    list_display = ("samian_id", "transaction_samian_id", "barcode", "item_name", "quantity", "unit_price", "line_revenue", "report_date")
    search_fields = ("barcode", "item_name", "transaction_samian_id")
    list_filter = ("is_return",)


@admin.register(SamianPriceList)
class SamianPriceListAdmin(admin.ModelAdmin):
    list_display = ("samian_id", "name", "is_active", "valid_from", "valid_to")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(SamianPriceListItem)
class SamianPriceListItemAdmin(admin.ModelAdmin):
    list_display = ("samian_product", "price_list_name", "list_price", "discount_percent", "final_price")
    search_fields = ("price_list_name",)
    raw_id_fields = ("samian_product", "price_list")


@admin.register(SamianSyncLog)
class SamianSyncLogAdmin(admin.ModelAdmin):
    list_display = ("action", "status", "started_at", "finished_at", "records_read", "records_upserted")
    list_filter = ("action", "status")
    readonly_fields = ("started_at", "finished_at", "records_read", "records_upserted", "error_message", "details")
