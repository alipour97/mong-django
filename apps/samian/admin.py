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
    SamianSalesTransaction,
    SamianSalesRow,
    SamianSyncLog,
)


@admin.register(SamianBrand)
class SamianBrandAdmin(admin.ModelAdmin):
    list_display = ("samian_id", "title", "title_en", "brand_code", "erp_code")
    search_fields = ("title", "title_en", "brand_code")
    list_filter = ("parent",)


@admin.register(SamianDepartment)
class SamianDepartmentAdmin(admin.ModelAdmin):
    list_display = ("samian_id", "title", "current_level", "department1", "department2", "department3")
    search_fields = ("title", "department1", "department2", "department3")
    list_filter = ("current_level",)


@admin.register(SamianWarehouse)
class SamianWarehouseAdmin(admin.ModelAdmin):
    list_display = ("samian_id", "title", "department_id", "is_active")
    search_fields = ("title",)
    list_filter = ("is_active",)


@admin.register(SamianProduct)
class SamianProductAdmin(admin.ModelAdmin):
    list_display = ("samian_id", "subcode", "name", "brand_name", "department_name", "season_code", "is_active", "is_saleable")
    search_fields = ("samian_id", "subcode", "name", "brand_name")
    list_filter = ("is_active", "is_saleable", "season_code")


@admin.register(SamianProductColor)
class SamianProductColorAdmin(admin.ModelAdmin):
    list_display = ("samian_id", "productmain_id", "color_name", "has_gallery", "subcode_hint")
    search_fields = ("samian_id", "productmain_id", "color_name", "subcode_hint")
    list_filter = ("has_gallery",)


@admin.register(SamianBarcode)
class SamianBarcodeAdmin(admin.ModelAdmin):
    list_display = ("samian_id", "barcode", "subcode", "productmain_id", "size_name", "color_name", "sale_price", "is_active")
    search_fields = ("barcode", "subcode", "size_name", "color_name")
    list_filter = ("is_active",)


@admin.register(SamianInventory)
class SamianInventoryAdmin(admin.ModelAdmin):
    list_display = ("samian_id", "barcode", "barcodemain_id", "warehouse_id", "count", "updated_at_samian")
    search_fields = ("barcode", "barcodemain_id")
    list_filter = ("warehouse_id",)


@admin.register(SamianCustomer)
class SamianCustomerAdmin(admin.ModelAdmin):
    list_display = ("samian_id", "first_name", "last_name", "cellphone", "national_code")
    search_fields = ("first_name", "last_name", "cellphone", "national_code")


class SamianSalesRowInline(admin.TabularInline):
    model = SamianSalesRow
    extra = 0
    readonly_fields = ("barcode", "item_name", "quantity", "unit_price", "discount_amount", "line_revenue")


@admin.register(SamianSalesTransaction)
class SamianSalesTransactionAdmin(admin.ModelAdmin):
    list_display = ("samian_id", "transaction_code", "transaction_date", "total_amount", "net_amount", "status", "store_order_id")
    search_fields = ("transaction_code", "transaction_unique_id", "customer_samian_id")
    list_filter = ("status", "warehouse_id")
    inlines = [SamianSalesRowInline]


@admin.register(SamianSalesRow)
class SamianSalesRowAdmin(admin.ModelAdmin):
    list_display = ("samian_id", "transaction_samian_id", "barcode", "item_name", "quantity", "unit_price", "line_revenue")
    search_fields = ("barcode", "item_name", "transaction_samian_id")


@admin.register(SamianSyncLog)
class SamianSyncLogAdmin(admin.ModelAdmin):
    list_display = ("action", "status", "started_at", "finished_at", "records_read", "records_upserted")
    list_filter = ("action", "status")
    readonly_fields = ("started_at", "finished_at", "records_read", "records_upserted", "error_message", "details")
