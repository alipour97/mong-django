from django.contrib import admin
from django.utils.html import format_html, format_html_join

from . import images as site_images
from . import models as m


def _thumb(url: str, height: int = 48):
    if not url:
        return "—"
    return format_html('<img src="{}" style="height:{}px;border-radius:4px">', site_images.site_media_url(url), height)


class LegacyAdmin(admin.ModelAdmin):
    """Imported rows: soft-deleted ones are hidden unless the filter asks for them."""

    list_per_page = 50

    def get_list_filter(self, request):
        return (*super().get_list_filter(request), "is_deleted")


# -----------------------------------------------------------------------------
# Catalog
# -----------------------------------------------------------------------------
@admin.register(m.Category)
class CategoryAdmin(LegacyAdmin):
    """Categories are Samian departments (sync_site_catalog); a new one arrives switched off."""

    list_display = ("id", "title", "parent", "slug", "samian_department_id", "is_online_active", "in_main_page",
                    "display_priority")
    list_editable = ("is_online_active", "in_main_page", "display_priority")
    list_filter = ("is_online_active", "in_main_page", "group_level")
    search_fields = ("title", "slug", "map_id")
    raw_id_fields = ("parent",)
    readonly_fields = ("samian_department_id",)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        from apps.storefront.catalog import clear_caches

        clear_caches()


@admin.register(m.Brand)
class BrandAdmin(LegacyAdmin):
    list_display = ("id", "title", "group_name")
    search_fields = ("title",)


@admin.register(m.Tag)
class TagAdmin(LegacyAdmin):
    list_display = ("id", "title", "parent")
    search_fields = ("title",)
    raw_id_fields = ("parent",)


class FeatureValueInline(admin.TabularInline):
    model = m.FeatureValue
    extra = 0
    fields = ("name", "value", "display_priority", "is_deleted")


@admin.register(m.Feature)
class FeatureAdmin(LegacyAdmin):
    list_display = ("id", "name", "display_priority")
    inlines = [FeatureValueInline]


@admin.register(m.FeatureValue)
class FeatureValueAdmin(LegacyAdmin):
    list_display = ("id", "name", "value", "feature", "display_priority")
    list_filter = ("feature",)
    search_fields = ("name", "value")


class ProductVariantInline(admin.TabularInline):
    model = m.ProductVariant
    extra = 0
    fields = ("barcode", "color", "size", "legacy_qty", "is_deleted")
    raw_id_fields = ("color", "size")


@admin.register(m.Product)
class ProductAdmin(LegacyAdmin):
    list_display = ("id", "title", "barcode", "category", "brand", "price", "reduction", "is_active")
    list_filter = ("is_active", "is_saleable", "show_torob", "brand")
    search_fields = ("title", "slug", "barcode", "map_id")
    raw_id_fields = ("category", "brand")
    inlines = [ProductVariantInline]


@admin.register(m.ProductSamianLink)
class ProductSamianLinkAdmin(admin.ModelAdmin):
    list_display = ("product", "samian_product_id", "method", "updated_at")
    list_filter = ("method",)
    search_fields = ("product__title", "product__barcode", "samian_product_id")
    raw_id_fields = ("product",)


# -----------------------------------------------------------------------------
# Home page and content
# -----------------------------------------------------------------------------
@admin.register(m.PrimaryConfig)
class PrimaryConfigAdmin(LegacyAdmin):
    list_display = ("id", "key", "short_value")
    search_fields = ("key", "value")

    @admin.display(description="مقدار")
    def short_value(self, obj):
        return (obj.value or "")[:120]


@admin.register(m.Banner)
class BannerAdmin(LegacyAdmin):
    list_display = ("id", "image", "link", "is_banner", "is_active", "display_priority")
    list_editable = ("is_active", "display_priority")
    list_filter = ("is_active", "is_banner")
    search_fields = ("link", "media_url")

    @admin.display(description="تصویر")
    def image(self, obj):
        return _thumb(obj.media_url)


class CollectionCategoryInline(admin.TabularInline):
    model = m.CollectionCategory
    extra = 0
    raw_id_fields = ("category",)


class ProductCollectionInline(admin.TabularInline):
    model = m.ProductCollection
    extra = 0
    raw_id_fields = ("product", "brand")


@admin.register(m.Collection)
class CollectionAdmin(LegacyAdmin):
    list_display = ("id", "title", "parent", "is_active", "in_main_page", "display_priority",
                    "beginning_date", "end_date", "reduction", "product_count")
    list_editable = ("is_active", "in_main_page", "display_priority")
    list_filter = ("is_active", "in_main_page")
    search_fields = ("title",)
    raw_id_fields = ("parent",)
    inlines = [CollectionCategoryInline, ProductCollectionInline]

    @admin.display(description="تعداد محصول")
    def product_count(self, obj):
        return m.ProductCollection.objects.filter(collection=obj, is_deleted=False).count()


class OutfitProductInline(admin.TabularInline):
    model = m.OutfitProduct
    extra = 0
    raw_id_fields = ("product", "feature_value")


@admin.register(m.Outfit)
class OutfitAdmin(LegacyAdmin):
    list_display = ("id", "title", "label_title", "category", "is_active", "start_date", "expiration_date", "product_count")
    list_editable = ("is_active",)
    list_filter = ("is_active",)
    search_fields = ("title", "label_title", "description")
    raw_id_fields = ("category",)
    inlines = [OutfitProductInline]

    @admin.display(description="تعداد محصول")
    def product_count(self, obj):
        return m.OutfitProduct.objects.filter(outfit=obj, is_deleted=False).count()


@admin.register(m.SelectedProduct)
class SelectedProductAdmin(LegacyAdmin):
    list_display = ("id", "product", "product_barcode", "feature_value", "sorting_weight")
    list_editable = ("sorting_weight",)
    search_fields = ("product__title", "product__barcode")
    raw_id_fields = ("product", "feature_value")
    ordering = ("sorting_weight",)

    @admin.display(description="کد کالا")
    def product_barcode(self, obj):
        return obj.product.barcode if obj.product_id else ""


COMMENT_STATUS = {0: "در انتظار تایید", 1: "تایید شده", 2: "رد شده", 3: "مشاهده شده"}


@admin.register(m.ProductComment)
class ProductCommentAdmin(LegacyAdmin):
    list_display = ("id", "product", "commenter", "title", "short_comment", "score", "status_title", "is_buyer", "is_active", "created")
    list_filter = ("status", "is_active", "is_buyer", "is_admin_comment", "score")
    search_fields = ("title", "comment", "product__title")
    raw_id_fields = ("product", "parent", "feature_value")
    date_hierarchy = "created"
    ordering = ("-id",)

    @admin.display(description="نظر")
    def short_comment(self, obj):
        return (obj.comment or "")[:80]

    @admin.display(description="وضعیت", ordering="status")
    def status_title(self, obj):
        return COMMENT_STATUS.get(obj.status, obj.status)

    @admin.display(description="نظردهنده")
    def commenter(self, obj):
        if obj.is_anonymous:
            return "ناشناس"
        c = m.Customer.objects.filter(id=obj.commenter_id).first()
        return f"{c.first_name} {c.last_name} ({c.cellphone})" if c else obj.commenter_id


@admin.register(m.Redirect)
class RedirectAdmin(LegacyAdmin):
    list_display = ("id", "source_url", "destination_url", "permanent", "is_active", "title")
    list_filter = ("is_active", "permanent")
    search_fields = ("source_url", "destination_url", "title")


# -----------------------------------------------------------------------------
# Company, settings, themes
# -----------------------------------------------------------------------------
@admin.register(m.CompanyInfo)
class CompanyInfoAdmin(LegacyAdmin):
    list_display = ("id", "name", "phone_numbers", "postal_code", "address")


@admin.register(m.SiteSetting)
class SiteSettingAdmin(LegacyAdmin):
    list_display = ("id", "website_title", "is_payment", "only_has_media_products", "min_qty",
                    "has_connection_with_snapp_pay", "has_connection_with_torob")


class ThemePageInline(admin.TabularInline):
    model = m.ThemePage
    extra = 0


class CustomThemePageInline(admin.TabularInline):
    model = m.CustomThemePage
    extra = 0


THEME_COLORS = ("primary1_color", "primary2_color", "secondary_color", "cta_color", "highlight_color")


class ThemeAdminBase(LegacyAdmin):
    search_fields = ("lable_title", "description")

    @admin.display(description="رنگ‌ها")
    def colors(self, obj):
        return format_html_join("", '<span title="{0}" style="display:inline-block;width:16px;height:16px;'
                                'margin-left:2px;border:1px solid #ccc;border-radius:3px;background:{0}"></span>',
                                ((getattr(obj, c) or "transparent",) for c in THEME_COLORS))

    @admin.display(description="تصویر")
    def image(self, obj):
        return _thumb(obj.desktop_image or obj.mobile_image)


@admin.register(m.Theme)
class ThemeAdmin(ThemeAdminBase):
    list_display = ("id", "lable_title", "theme_name", "colors", "image", "category_count", "is_editable")
    inlines = [ThemePageInline]


@admin.register(m.CustomTheme)
class CustomThemeAdmin(ThemeAdminBase):
    list_display = ("id", "lable_title", "custom_theme_name", "colors", "image", "category_count", "is_editable")
    inlines = [CustomThemePageInline]


@admin.register(m.Page)
class PageAdmin(LegacyAdmin):
    list_display = ("id", "name", "key", "type", "is_landing_page", "image")
    list_filter = ("type", "key", "is_landing_page")
    search_fields = ("name", "key")

    @admin.display(description="تصویر")
    def image(self, obj):
        return _thumb(obj.image_url)


# -----------------------------------------------------------------------------
# Places and shipping
# -----------------------------------------------------------------------------
class CityInline(admin.TabularInline):
    model = m.City
    extra = 0
    fields = ("name", "latitude", "longitude", "is_deleted")


@admin.register(m.Province)
class ProvinceAdmin(LegacyAdmin):
    list_display = ("id", "name", "city_count", "latitude", "longitude")
    search_fields = ("name",)
    inlines = [CityInline]

    @admin.display(description="تعداد شهر")
    def city_count(self, obj):
        return obj.cities.count()


@admin.register(m.City)
class CityAdmin(LegacyAdmin):
    list_display = ("id", "name", "province")
    list_filter = ("province",)
    search_fields = ("name",)


@admin.register(m.ShippingMethodType)
class ShippingMethodTypeAdmin(LegacyAdmin):
    list_display = ("id", "name", "key", "include_costs", "method_count")

    @admin.display(description="تعداد روش")
    def method_count(self, obj):
        return obj.methods.count()


class ShippingMethodLocationInline(admin.TabularInline):
    model = m.ShippingMethodLocation
    extra = 0
    fields = ("province_id", "city_id", "is_deleted")


@admin.register(m.ShippingMethod)
class ShippingMethodAdmin(LegacyAdmin):
    list_display = ("id", "name", "type", "fixed_cost", "variable_fee", "is_dynamic_pricing",
                    "requires_insurance", "tax_percentage", "icon_image")
    list_filter = ("type", "is_dynamic_pricing", "requires_insurance")
    search_fields = ("name", "description")
    fieldsets = (
        (None, {"fields": ("name", "type", "description", "icon")}),
        ("هزینه", {"fields": (("fixed_cost", "variable_fee", "is_dynamic_pricing"), "source_dependent")}),
        ("بیمه و مالیات", {"fields": (("requires_insurance", "insurance_cost", "insurance_percentage"),
                                      ("tax_percentage", "tax_amount"))}),
        (None, {"fields": ("is_deleted",)}),
    )
    inlines = [ShippingMethodLocationInline]

    @admin.display(description="آیکن")
    def icon_image(self, obj):
        return _thumb(obj.icon, 32)


# -----------------------------------------------------------------------------
# Branches
# -----------------------------------------------------------------------------
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
class CompanyBranchAdmin(LegacyAdmin):
    """The Dadehfa branch list (ids used by old invoices). Shops are edited under Branch."""

    list_display = ("id", "name", "is_active")


# -----------------------------------------------------------------------------
# Customers
# -----------------------------------------------------------------------------
class CustomerAddressInline(admin.StackedInline):
    model = m.CustomerAddress
    extra = 0
    fields = (("title", "is_default"), "address", ("province", "city", "zip_code"),
              ("first_name", "last_name", "mobile"), ("latitude", "longitude"), "is_deleted")
    raw_id_fields = ("province", "city")


class CustomerFavoriteInline(admin.TabularInline):
    model = m.CustomerFavoriteProduct
    extra = 0
    fields = ("product", "color_id", "size_id", "is_deleted")
    raw_id_fields = ("product",)


@admin.register(m.Customer)
class CustomerAdmin(LegacyAdmin):
    list_display = ("id", "first_name", "last_name", "cellphone", "samian_customer", "is_bulletin_enabled", "is_active", "created")
    list_filter = ("is_active", "is_bulletin_enabled")
    search_fields = ("first_name", "last_name", "cellphone", "national_code", "email")
    raw_id_fields = ("samian_customer",)
    readonly_fields = ("samian_checked_at",)
    date_hierarchy = "created"
    inlines = [CustomerAddressInline, CustomerFavoriteInline]


@admin.register(m.Job)
class JobAdmin(LegacyAdmin):
    list_display = ("id", "title")
    search_fields = ("title",)


@admin.register(m.CooperationRequest)
class CooperationRequestAdmin(LegacyAdmin):
    list_display = ("id", "first_name", "last_name", "cellphone", "job_position_title", "state", "created")
    list_filter = ("state",)
    search_fields = ("first_name", "last_name", "cellphone", "email", "job_position_title")
    date_hierarchy = "created"


@admin.register(m.Article)
class ArticleAdmin(LegacyAdmin):
    list_display = ("id", "title", "uniq_url", "show_on_page", "publish_date", "view_count")
    list_filter = ("show_on_page",)
    search_fields = ("title", "uniq_url")


@admin.register(m.BlogCategory)
class BlogCategoryAdmin(LegacyAdmin):
    list_display = ("id", "title", "in_main_page")


@admin.register(m.ArticleTag)
class ArticleTagAdmin(LegacyAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)


@admin.register(m.ArticleComment)
class ArticleCommentAdmin(LegacyAdmin):
    list_display = ("id", "article", "title", "status", "created")
    list_filter = ("status",)


class InvoiceLineInline(admin.TabularInline):
    model = m.InvoiceLine
    extra = 0
    can_delete = False
    readonly_fields = ("product", "variant_id", "barcode", "name", "color_name", "size_name", "qty", "price", "reduction",
                       "price_after_reduction")
    fields = readonly_fields


class InvoicePaymentInline(admin.TabularInline):
    model = m.InvoicePayment
    extra = 0
    can_delete = False
    readonly_fields = ("gateway", "amount", "authority", "transaction_id", "reference", "card_pan", "is_success",
                       "error_message", "created", "verified_at")
    fields = readonly_fields


@admin.register(m.Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    """Site orders; read only here (they change through checkout and, later, Samian)."""

    list_display = ("id", "customer", "state", "payable_amount", "shipping_method", "paid_at", "samian_transaction_id", "created")
    list_filter = ("state", "shipping_method")
    search_fields = ("id", "customer__cellphone", "customer__first_name", "customer__last_name")
    date_hierarchy = "created"
    inlines = [InvoiceLineInline, InvoicePaymentInline]
    readonly_fields = [f.name for f in m.Invoice._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
