from django.contrib import admin

from . import models as m


@admin.register(m.Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "slug", "parent", "is_online_active", "in_main_page", "display_priority")
    list_filter = ("is_online_active", "in_main_page", "group_level", "is_deleted")
    search_fields = ("title", "slug", "map_id")


@admin.register(m.Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "barcode", "category", "price", "reduction", "is_active", "is_deleted")
    list_filter = ("is_active", "is_saleable", "is_deleted", "show_torob")
    search_fields = ("title", "slug", "barcode", "map_id")
    raw_id_fields = ("category", "brand")


@admin.register(m.ProductSamianLink)
class ProductSamianLinkAdmin(admin.ModelAdmin):
    list_display = ("product", "samian_product_id", "method", "updated_at")
    list_filter = ("method",)
    raw_id_fields = ("product",)


@admin.register(m.PrimaryConfig)
class PrimaryConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "key", "is_deleted")
    search_fields = ("key",)


@admin.register(m.Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ("id", "media_url", "link", "is_active", "display_priority")
    list_filter = ("is_active", "is_banner")


for model in (
    m.Brand, m.Tag, m.Feature, m.FeatureValue, m.Collection, m.Outfit, m.SelectedProduct,
    m.ProductComment, m.Redirect, m.CompanyInfo, m.SiteSetting, m.Theme,
    m.CustomTheme, m.Page, m.ShippingMethod, m.ShippingMethodType, m.Province,
):
    admin.site.register(model)


@admin.register(m.Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("title", "warehouse", "show_on_site", "sells_online", "display_order")
    list_editable = ("show_on_site", "sells_online", "display_order")
    list_filter = ("show_on_site", "sells_online")
    search_fields = ("title", "address", "phones")
    fieldsets = (
        (None, {"fields": ("title", "address", "phones", ("latitude", "longitude"))}),
        ("سایت و موجودی", {"fields": ("show_on_site", "display_order", "warehouse", "sells_online")}),
    )


@admin.register(m.CompanyBranch)
class CompanyBranchAdmin(admin.ModelAdmin):
    """The Dadehfa branch list (ids used by old invoices). Shops are edited under Branch."""

    list_display = ("id", "name", "is_active", "is_deleted")


class CustomerAddressInline(admin.StackedInline):
    model = m.CustomerAddress
    extra = 0
    fields = (("title", "is_default"), "address", ("province", "city", "zip_code"),
              ("first_name", "last_name", "mobile"), ("latitude", "longitude"), "is_deleted")
    raw_id_fields = ("province", "city")


@admin.register(m.Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("id", "first_name", "last_name", "cellphone", "samian_customer", "is_active")
    list_filter = ("is_active", "is_bulletin_enabled", "is_deleted")
    search_fields = ("first_name", "last_name", "cellphone", "national_code", "email")
    raw_id_fields = ("samian_customer",)
    readonly_fields = ("samian_checked_at",)
    inlines = [CustomerAddressInline]
