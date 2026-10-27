"""
Django ORM Models for storing Samian ERP synchronized data.

Mirroring Samian ERP core entities — enriched to match LEBAZAI's level:
- SamianBrand: codingbrand (/v2/product/codingbrand)
- SamianDepartment: codingdepartment (/v2/product/codingdepartment)
- SamianWarehouse: warehouse (/v2/accounting/warehouse)
- SamianProduct: productmain (/v2/product/productmain)
- SamianProductColor: colors (/v2/product/colors)
- SamianBarcode: barcodemain (/v2/product/barcodemain)
- SamianInventory: wm/stock (/v2/wm/stock)
- SamianCustomer: poscustomer (/v2/retail/poscustomer)
- SamianSalesTransaction: postransaction (/v2/retail/postransaction)
- SamianSalesRow: postransactionitems (/v2/retail/postransactionitems)
- SamianPriceList: pricinglistinfo (/v2/product/pricinglistinfo)
- SamianPriceListItem: per-product price in a price list
- SamianSyncLog: Audit and history of synchronization jobs
"""
from __future__ import annotations

import logging
from django.db import models
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Reference tables
# ---------------------------------------------------------------------------

class SamianBrand(models.Model):
    samian_id = models.BigIntegerField(_("شناسه برند در سامیان"), unique=True, db_index=True)
    title = models.CharField(_("نام برند"), max_length=255, db_index=True)
    title_en = models.CharField(_("نام انگلیسی"), max_length=255, blank=True, default="")
    brand_code = models.CharField(_("کد برند"), max_length=64, blank=True, default="")
    erp_code = models.CharField(_("کد ERP"), max_length=64, blank=True, default="")
    brand_origin = models.CharField(_("مبدأ برند"), max_length=128, blank=True, default="")
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="children", verbose_name=_("برند والد"),
    )
    supplier_account_id = models.BigIntegerField(_("شناسه حساب تأمین‌کننده"), null=True, blank=True)
    supplier_name = models.CharField(_("تأمین‌کننده"), max_length=255, blank=True, default="")
    commission_percent = models.DecimalField(
        _("درصد کمیسیون"), max_digits=6, decimal_places=2, null=True, blank=True,
    )
    max_display_stock = models.IntegerField(_("حداکثر موجودی نمایش"), null=True, blank=True)

    raw_data = models.JSONField(_("داده خام سامیان"), default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("برند سامیان")
        verbose_name_plural = _("برندهای سامیان")
        ordering = ("title",)

    def __str__(self) -> str:
        return self.title or str(self.samian_id)


class SamianDepartment(models.Model):
    samian_id = models.BigIntegerField(_("شناسه دپارتمان در سامیان"), unique=True, db_index=True)
    title = models.CharField(_("عنوان دپارتمان"), max_length=255, db_index=True)
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="children", verbose_name=_("دپارتمان والد"),
    )
    level = models.PositiveSmallIntegerField(_("سطح"), default=0)
    department_code = models.CharField(_("کد دپارتمان"), max_length=64, blank=True, default="")
    erp_code = models.CharField(_("کد ERP"), max_length=64, blank=True, default="")
    department1 = models.CharField(_("دپارتمان سطح ۱ (ریشه)"), max_length=255, blank=True, default="", db_index=True)
    department2 = models.CharField(_("دپارتمان سطح ۲"), max_length=255, blank=True, default="")
    department3 = models.CharField(_("دپارتمان سطح ۳ (برگ)"), max_length=255, blank=True, default="")
    raw_data = models.JSONField(_("داده خام سامیان"), default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("دپارتمان سامیان")
        verbose_name_plural = _("دپارتمان‌های سامیان")
        ordering = ("department1", "department2", "department3")

    def __str__(self) -> str:
        return self.path or str(self.samian_id)

    @property
    def path(self) -> str:
        parts = [x for x in (self.department1, self.department2, self.department3) if x]
        if len(parts) == 2 and parts[0] == parts[1]:
            parts = parts[:1]
        return " / ".join(parts)


class SamianWarehouse(models.Model):
    samian_id = models.IntegerField(_("شناسه انبار در سامیان"), unique=True, db_index=True)
    title = models.CharField(_("نام انبار"), max_length=255, db_index=True)
    department_id = models.IntegerField(_("شناسه شعبه/دپارتمان"), null=True, blank=True, db_index=True)
    department_name = models.CharField(_("شعبه/دپارتمان"), max_length=255, blank=True, default="")
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="children", verbose_name=_("انبار والد"),
    )
    in_way_warehouse_id = models.IntegerField(_("شناسه انبار در راه"), null=True, blank=True)
    pricing_list_id = models.BigIntegerField(_("شناسه لیست قیمت"), null=True, blank=True)
    pricing_list_name = models.CharField(_("لیست قیمت"), max_length=255, blank=True, default="")

    is_active = models.BooleanField(_("فعال"), default=True, db_index=True)
    is_commercial = models.BooleanField(_("تجاری (قابل فروش)"), default=True)
    is_negative_sale = models.BooleanField(_("فروش منفی مجاز"), default=False)
    is_return_active = models.BooleanField(_("مرجوعی فعال"), default=False)
    is_quarantine = models.BooleanField(_("قرنطینه"), default=False)

    address = models.TextField(_("آدرس"), blank=True, default="")
    postal_code = models.CharField(_("کد پستی"), max_length=32, blank=True, default="")
    erp_code = models.CharField(_("کد ERP"), max_length=64, blank=True, default="")
    notes = models.TextField(_("یادداشت"), blank=True, default="")

    raw_data = models.JSONField(_("داده خام سامیان"), default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("انبار سامیان")
        verbose_name_plural = _("انبارهای سامیان")
        ordering = ("samian_id",)

    def __str__(self) -> str:
        return f"{self.title} ({self.samian_id})"


# ---------------------------------------------------------------------------
# Product catalog
# ---------------------------------------------------------------------------

class SamianProduct(models.Model):
    samian_id = models.BigIntegerField(
        _("شناسه محصول در سامیان"), unique=True, db_index=True,
    )
    subcode = models.CharField(
        _("کد فرعی (subcode)"), max_length=128, blank=True, db_index=True,
    )
    name = models.CharField(_("نام کالا"), max_length=255, blank=True, default="")
    name_en = models.CharField(_("نام انگلیسی"), max_length=512, blank=True, default="")
    description = models.TextField(_("توضیحات"), blank=True, default="")

    brand_id = models.BigIntegerField(_("شناسه برند در سامیان"), null=True, blank=True)
    brand_name = models.CharField(_("نام برند"), max_length=255, blank=True, default="")
    samian_brand = models.ForeignKey(
        SamianBrand, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="products", verbose_name=_("برند سامیان"),
    )

    department_id = models.BigIntegerField(_("شناسه دپارتمان"), null=True, blank=True)
    department_name = models.CharField(_("نام دپارتمان"), max_length=255, blank=True, default="")
    samian_department = models.ForeignKey(
        SamianDepartment, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="products", verbose_name=_("دپارتمان سامیان"),
    )
    provider_id = models.BigIntegerField(_("شناسه تأمین‌کننده"), null=True, blank=True)
    provider_name = models.CharField(_("تأمین‌کننده"), max_length=255, blank=True, default="")

    category_id = models.BigIntegerField(_("شناسه دسته‌بندی"), null=True, blank=True)
    category = models.CharField(_("دسته‌بندی"), max_length=255, blank=True, default="")

    season_id = models.BigIntegerField(_("شناسه فصل"), null=True, blank=True)
    season = models.CharField(_("فصل"), max_length=255, blank=True, default="")
    season_code = models.CharField(_("کد فصل"), max_length=64, blank=True, default="", db_index=True)

    style = models.CharField(_("استایل"), max_length=255, blank=True, default="")
    material = models.CharField(_("جنس / متریال"), max_length=255, blank=True, default="")
    fit = models.CharField(_("فیت"), max_length=255, blank=True, default="")

    height_id = models.BigIntegerField(_("شناسه قد"), null=True, blank=True)
    height = models.CharField(_("قد"), max_length=255, blank=True, default="")

    age_id = models.BigIntegerField(_("شناسه رده سنی"), null=True, blank=True)
    age = models.CharField(_("رده سنی"), max_length=255, blank=True, default="")

    sex_id = models.BigIntegerField(_("شناسه جنسیت"), null=True, blank=True)
    sex = models.CharField(_("جنسیت"), max_length=128, blank=True, default="")

    product_tag = models.CharField(_("تگ کالا"), max_length=255, blank=True, default="")
    supplier_code = models.CharField(_("کد تأمین‌کننده"), max_length=128, blank=True, default="")
    designer_model = models.CharField(_("مدل طراح"), max_length=255, blank=True, default="")
    unit_name = models.CharField(_("واحد شمارش"), max_length=64, blank=True, default="")

    product_status_id = models.IntegerField(_("شناسه وضعیت کالا"), null=True, blank=True)
    product_status = models.CharField(_("وضعیت کالا"), max_length=128, blank=True, default="")
    sale_status_id = models.IntegerField(_("شناسه وضعیت فروش"), null=True, blank=True)
    sale_status = models.CharField(_("وضعیت فروش"), max_length=128, blank=True, default="")

    is_active = models.BooleanField(_("فعال"), default=True)
    is_saleable = models.BooleanField(_("قابل فروش"), default=True)
    online_store_published = models.BooleanField(_("منتشر شده در فروشگاه آنلاین"), default=False)

    buy_price = models.BigIntegerField(_("قیمت خرید (ریال)"), null=True, blank=True)
    sale_price = models.BigIntegerField(_("قیمت فروش (ریال)"), null=True, blank=True, db_index=True)
    price_synced_at = models.DateTimeField(_("آخرین سینک قیمت"), null=True, blank=True)

    create_date = models.DateTimeField(_("تاریخ ایجاد در سامیان"), null=True, blank=True, db_index=True)

    raw_data = models.JSONField(_("داده خام سامیان"), default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("محصول سامیان")
        verbose_name_plural = _("محصولات سامیان")
        ordering = ("-samian_id",)
        indexes = [
            models.Index(fields=["subcode", "is_active"]),
        ]

    @property
    def margin_percent(self) -> float | None:
        if not self.buy_price or not self.sale_price:
            return None
        return round((self.sale_price - self.buy_price) * 100 / self.sale_price, 2)

    def current_list_price(self, at=None) -> "SamianPriceListItem | None":
        from django.db.models import Q
        from django.utils import timezone
        at = at or timezone.now()
        return (
            self.price_list_items.filter(
                Q(price_list__isnull=True)
                | Q(
                    price_list__is_active=True,
                    price_list__valid_from__lte=at,
                    price_list__valid_to__gte=at,
                )
            )
            .order_by("final_price")
            .first()
        )

    def __str__(self) -> str:
        code_str = f" [{self.subcode}]" if self.subcode else ""
        return f"{self.name or 'محصول'}{code_str} (ID: {self.samian_id})"


class SamianProductColor(models.Model):
    samian_id = models.BigIntegerField(_("شناسه رکورد رنگ در سامیان"), unique=True, db_index=True)
    samian_product = models.ForeignKey(
        SamianProduct, on_delete=models.CASCADE, null=True, blank=True,
        related_name="colors", verbose_name=_("محصول متناظر"),
    )
    productmain_id = models.BigIntegerField(_("شناسه محصول در سامیان"), db_index=True)
    colorinfo_id = models.BigIntegerField(_("شناسه رنگ پایه"), null=True, blank=True, db_index=True)
    color_name = models.CharField(_("نام رنگ"), max_length=128, blank=True, default="")
    colorsgalery = models.JSONField(_("گالری تصاویر سامیان"), default=list, blank=True)
    has_gallery = models.BooleanField(_("دارای تصویر"), default=False, db_index=True)
    subcode_hint = models.CharField(_("کد فرعی استخراج‌شده"), max_length=128, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("رنگ محصول سامیان")
        verbose_name_plural = _("رنگ‌های محصولات سامیان")
        ordering = ("-samian_id",)
        indexes = [
            models.Index(fields=["productmain_id", "color_name"]),
            models.Index(fields=["subcode_hint"]),
        ]

    def __str__(self) -> str:
        return f"{self.productmain_id} - {self.color_name} (ID: {self.samian_id})"


class SamianBarcode(models.Model):
    samian_id = models.BigIntegerField(_("شناسه بارکد در سامیان"), unique=True, db_index=True)
    # Not unique: Samian has the same kbarcode on more than one barcodemain record.
    barcode = models.CharField(_("بارکد (kbarcode)"), max_length=255, db_index=True)
    subcode = models.CharField(_("کد فرعی کالا"), max_length=128, blank=True, default="", db_index=True)
    samian_product = models.ForeignKey(
        SamianProduct, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="barcodes", verbose_name=_("محصول مرتبط"),
    )
    productmain_id = models.BigIntegerField(_("شناسه محصول"), null=True, blank=True, db_index=True)

    color = models.CharField(_("رنگ"), max_length=255, blank=True, default="", db_index=True)
    color_en = models.CharField(_("رنگ انگلیسی"), max_length=255, blank=True, default="")
    size = models.CharField(_("سایز"), max_length=128, blank=True, default="")
    season_code = models.CharField(_("کد فصل"), max_length=64, blank=True, default="", db_index=True)
    material_desc = models.CharField(_("شرح جنس"), max_length=255, blank=True, default="")
    sku_code = models.CharField(_("کد SKU سامیان"), max_length=128, blank=True, default="")

    buy_price = models.BigIntegerField(_("قیمت خرید (ریال)"), default=0)
    sale_price = models.BigIntegerField(_("قیمت فروش (ریال)"), default=0)
    end_user_price = models.BigIntegerField(_("قیمت مصرف‌کننده (ریال)"), null=True, blank=True)
    discount_percent = models.DecimalField(_("درصد تخفیف"), max_digits=5, decimal_places=2, default=0)

    is_active = models.BooleanField(_("فعال"), default=True, db_index=True)
    sale_status_id = models.IntegerField(_("شناسه وضعیت فروش"), null=True, blank=True)
    sale_status = models.CharField(_("وضعیت فروش"), max_length=128, blank=True, default="")

    raw_data = models.JSONField(_("داده خام سامیان"), default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("بارکد سامیان")
        verbose_name_plural = _("بارکدهای سامیان")
        ordering = ("-samian_id",)
        indexes = [
            models.Index(fields=["samian_product", "color"]),
            models.Index(fields=["season_code", "is_active"]),
        ]

    def __str__(self) -> str:
        bits = " / ".join(x for x in (self.color, self.size) if x)
        return f"{self.barcode} ({bits})" if bits else self.barcode


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

class SamianInventory(models.Model):
    samian_barcode = models.ForeignKey(
        SamianBarcode, on_delete=models.CASCADE,
        related_name="inventory_rows", verbose_name=_("بارکد سامیان"),
    )
    barcodemain_id = models.BigIntegerField(_("شناسه بارکد در سامیان"), db_index=True)
    warehouse_id = models.IntegerField(_("شناسه انبار"), db_index=True)
    warehouse = models.CharField(_("نام انبار"), max_length=255, blank=True, default="")
    samian_warehouse = models.ForeignKey(
        SamianWarehouse, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="inventory_rows", verbose_name=_("انبار سامیان"),
    )

    qty = models.DecimalField(_("موجودی"), max_digits=14, decimal_places=2, default=0)
    qty_reserved = models.DecimalField(_("موجودی رزرو"), max_digits=14, decimal_places=2, default=0)

    source_updated_at = models.DateTimeField(_("زمان بروزرسانی در سامیان"), null=True, blank=True)
    last_updated = models.DateTimeField(_("آخرین بروزرسانی"), auto_now=True, db_index=True)

    class Meta:
        verbose_name = _("موجودی سامیان")
        verbose_name_plural = _("موجودی‌های سامیان")
        ordering = ("samian_barcode_id", "warehouse_id")
        constraints = [
            models.UniqueConstraint(
                fields=("samian_barcode", "warehouse_id"),
                name="samian_unique_barcode_warehouse_stock",
            ),
        ]
        indexes = [
            models.Index(fields=["warehouse_id", "qty"], name="samian_inv_wh_qty_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.barcodemain_id} @ {self.warehouse or self.warehouse_id}: {self.qty}"


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

class SamianCustomer(models.Model):
    samian_id = models.BigIntegerField(_("شناسه مشتری در سامیان"), unique=True, db_index=True)
    first_name = models.CharField(_("نام"), max_length=150, blank=True, default="")
    last_name = models.CharField(_("نام خانوادگی"), max_length=150, blank=True, default="")
    display_name = models.CharField(_("نام نمایشی"), max_length=255, blank=True, default="")
    mobile = models.CharField(_("موبایل"), max_length=50, blank=True, default="", db_index=True)
    phone = models.CharField(_("تلفن"), max_length=50, blank=True, default="")
    email = models.EmailField(_("ایمیل"), blank=True, default="")
    national_code = models.CharField(_("کد ملی"), max_length=32, blank=True, default="")

    gender_id = models.IntegerField(_("شناسه جنسیت"), null=True, blank=True)
    gender = models.CharField(_("جنسیت"), max_length=32, blank=True, default="")

    club_level_id = models.IntegerField(_("شناسه سطح باشگاه"), null=True, blank=True, db_index=True)
    club_level = models.CharField(_("سطح باشگاه"), max_length=128, blank=True, default="")
    customer_type_id = models.IntegerField(_("شناسه نوع مشتری"), null=True, blank=True)
    customer_type = models.CharField(_("نوع مشتری"), max_length=128, blank=True, default="")
    customer_status_id = models.IntegerField(_("شناسه وضعیت مشتری"), null=True, blank=True)
    customer_status = models.CharField(_("وضعیت مشتری"), max_length=128, blank=True, default="")

    subscription_code = models.CharField(_("کد عضویت"), max_length=128, blank=True, default="")
    customer_card_num = models.CharField(_("شماره کارت مشتری"), max_length=128, blank=True, default="")

    birthdate = models.DateField(_("تاریخ تولد"), null=True, blank=True)
    subscription_date = models.DateTimeField(_("تاریخ عضویت"), null=True, blank=True)

    wallet_balance = models.BigIntegerField(_("موجودی کیف پول (ریال)"), default=0)
    club_point_score = models.DecimalField(_("امتیاز باشگاه"), max_digits=18, decimal_places=2, default=0)
    club_price_score = models.BigIntegerField(_("امتیاز ریالی باشگاه"), default=0)

    address = models.TextField(_("آدرس"), blank=True, default="")
    postal_code = models.CharField(_("کد پستی"), max_length=32, blank=True, default="")

    is_active = models.BooleanField(_("فعال"), default=True)

    raw_data = models.JSONField(_("داده خام سامیان"), default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("مشتری سامیان")
        verbose_name_plural = _("مشتریان سامیان")
        ordering = ("-samian_id",)
        indexes = [
            models.Index(fields=["mobile"]),
            models.Index(fields=["club_level_id"]),
        ]

    @property
    def fullname(self) -> str:
        name = f"{self.first_name} {self.last_name}".strip()
        return name or self.display_name

    def __str__(self) -> str:
        return f"{self.fullname} ({self.samian_id})"


class SamianCustomerAddress(models.Model):
    """A customer's address in Samian (accounts/contactinfo)."""

    samian_id = models.BigIntegerField(_("شناسه آدرس در سامیان"), unique=True, db_index=True)
    customer = models.ForeignKey(
        SamianCustomer, on_delete=models.CASCADE, null=True, blank=True,
        related_name="addresses", verbose_name=_("مشتری"),
    )
    customer_samian_id = models.BigIntegerField(_("شناسه مشتری"), null=True, blank=True, db_index=True)
    title = models.CharField(_("عنوان"), max_length=255, blank=True, default="")
    address = models.TextField(_("آدرس"), blank=True, default="")
    receiver_name = models.CharField(_("نام گیرنده"), max_length=255, blank=True, default="")
    mobile = models.CharField(_("موبایل"), max_length=50, blank=True, default="")
    phone = models.CharField(_("تلفن"), max_length=50, blank=True, default="")
    postal_code = models.CharField(_("کد پستی"), max_length=32, blank=True, default="")
    province_id = models.BigIntegerField(_("شناسه استان"), null=True, blank=True)
    province = models.CharField(_("استان"), max_length=128, blank=True, default="")
    town_id = models.BigIntegerField(_("شناسه شهر"), null=True, blank=True)
    town = models.CharField(_("شهر"), max_length=128, blank=True, default="")
    is_default = models.BooleanField(_("پیش‌فرض"), default=False)

    raw_data = models.JSONField(_("داده خام سامیان"), default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("آدرس مشتری سامیان")
        verbose_name_plural = _("آدرس‌های مشتریان سامیان")
        ordering = ("-is_default", "samian_id")

    def __str__(self) -> str:
        return f"{self.title or self.address[:40]} ({self.samian_id})"


# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------

class SamianSalesTransaction(models.Model):
    samian_id = models.BigIntegerField(_("شناسه فاکتور در سامیان"), unique=True, db_index=True)
    transaction_code = models.CharField(
        _("کد فاکتور"), max_length=128, blank=True, default="", db_index=True,
    )
    transaction_unique_id = models.CharField(
        _("شناسه یکتای تراکنش"), max_length=64, blank=True, default="", db_index=True,
    )

    transaction_date = models.DateTimeField(_("تاریخ فاکتور"), null=True, blank=True, db_index=True)
    report_date = models.DateField(_("تاریخ فاکتور (روزانه)"), null=True, blank=True, db_index=True)
    order_date = models.DateTimeField(_("تاریخ سفارش"), null=True, blank=True)

    customer_samian_id = models.BigIntegerField(_("شناسه مشتری"), null=True, blank=True, db_index=True)
    samian_customer = models.ForeignKey(
        SamianCustomer, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="transactions", verbose_name=_("مشتری"),
    )

    warehouse_id = models.IntegerField(_("شناسه انبار"), null=True, blank=True, db_index=True)
    warehouse = models.CharField(_("نام انبار / شعبه"), max_length=255, blank=True, default="")
    samian_warehouse = models.ForeignKey(
        SamianWarehouse, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="transactions", verbose_name=_("انبار سامیان"),
    )
    department_id = models.IntegerField(_("شناسه دپارتمان"), null=True, blank=True)
    department = models.CharField(_("دپارتمان"), max_length=255, blank=True, default="")
    cash_id = models.IntegerField(_("شناسه صندوق"), null=True, blank=True)
    cash_name = models.CharField(_("نام صندوق"), max_length=255, blank=True, default="")

    cashier_person_id = models.BigIntegerField(_("شناسه صندوقدار"), null=True, blank=True, db_index=True)
    cashier_name = models.CharField(_("نام صندوقدار"), max_length=255, blank=True, default="")

    status_id = models.IntegerField(_("شناسه وضعیت فاکتور"), null=True, blank=True, db_index=True)
    status = models.CharField(_("وضعیت"), max_length=128, blank=True, default="")

    total_amount = models.BigIntegerField(_("مبلغ کل (ریال)"), default=0)
    total_discount = models.BigIntegerField(_("مجموع تخفیف (ریال)"), default=0)
    total_vat = models.BigIntegerField(_("مالیات (ریال)"), default=0)
    net_amount = models.BigIntegerField(_("مبلغ نهایی پرداختی (ریال)"), default=0)
    rounding_discount = models.BigIntegerField(_("تخفیف رند کردن (ریال)"), default=0)
    transaction_score = models.BigIntegerField(_("امتیاز فاکتور"), default=0)

    is_first_buy = models.BooleanField(_("اولین خرید مشتری"), default=False)
    year_info_id = models.IntegerField(_("سال مالی"), null=True, blank=True, db_index=True)
    store_order_id = models.BigIntegerField(_("شناسه سفارش وبسایت"), null=True, blank=True, db_index=True)
    delivery_address = models.TextField(_("آدرس تحویل"), blank=True, default="")

    raw_data = models.JSONField(_("داده خام سامیان"), default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("فاکتور فروش سامیان")
        verbose_name_plural = _("فاکتورهای فروش سامیان")
        ordering = ("-transaction_date", "-samian_id")
        indexes = [
            models.Index(fields=["report_date", "warehouse_id"]),
            models.Index(fields=["samian_customer", "report_date"]),
            models.Index(fields=["transaction_date"]),
            models.Index(fields=["samian_warehouse", "transaction_date"], name="samian_tx_wh_date_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.transaction_code or self.samian_id} ({self.report_date})"


class SamianSalesRow(models.Model):
    samian_id = models.BigIntegerField(_("شناسه ردیف فروش"), unique=True, db_index=True)
    transaction = models.ForeignKey(
        SamianSalesTransaction, on_delete=models.CASCADE, null=True, blank=True,
        related_name="rows", verbose_name=_("فاکتور"),
    )
    transaction_samian_id = models.BigIntegerField(_("شناسه فاکتور در سامیان"), null=True, blank=True, db_index=True)

    samian_barcode = models.ForeignKey(
        SamianBarcode, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="sales_rows", verbose_name=_("بارکد سامیان"), db_index=True,
    )
    samian_product = models.ForeignKey(
        SamianProduct, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="sales_rows", verbose_name=_("محصول سامیان"), db_index=True,
    )
    barcode = models.CharField(_("بارکد کالا"), max_length=255, blank=True, default="", db_index=True)
    barcodemain_id = models.BigIntegerField(_("شناسه بارکد در سامیان"), null=True, blank=True, db_index=True)
    productmain_id = models.BigIntegerField(_("شناسه محصول در سامیان"), null=True, blank=True, db_index=True)
    subcode = models.CharField(_("کد فرعی"), max_length=128, blank=True, default="", db_index=True)
    item_name = models.CharField(_("نام کالا"), max_length=512, blank=True, default="")

    transaction_date = models.DateTimeField(_("تاریخ و زمان فروش"), null=True, blank=True, db_index=True)
    report_date = models.DateField(_("تاریخ فروش"), null=True, blank=True, db_index=True)

    quantity = models.DecimalField(_("تعداد / مقدار"), max_digits=12, decimal_places=2, default=1)
    unit_price_before_discount = models.BigIntegerField(_("قیمت واحد قبل از تخفیف (ریال)"), default=0)
    unit_price = models.BigIntegerField(_("قیمت واحد (ریال)"), default=0)
    discount_percent = models.DecimalField(_("درصد تخفیف"), max_digits=8, decimal_places=2, default=0)
    discount_amount = models.BigIntegerField(_("مبلغ تخفیف (ریال)"), default=0)
    vat_amount = models.BigIntegerField(_("مالیات (ریال)"), default=0)
    gross_amount = models.BigIntegerField(_("مبلغ ناخالص ردیف (ریال)"), default=0)
    line_revenue = models.BigIntegerField(_("مبلغ ردیف (ریال)"), default=0)

    sale_person_id = models.BigIntegerField(_("شناسه فروشنده"), null=True, blank=True, db_index=True)
    sale_person_name = models.CharField(_("نام فروشنده"), max_length=255, blank=True, default="")
    warehouse_id = models.IntegerField(_("شناسه انبار"), null=True, blank=True, db_index=True)
    samian_warehouse = models.ForeignKey(
        SamianWarehouse, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="sales_rows", verbose_name=_("انبار سامیان"),
    )

    is_return = models.BooleanField(_("مرجوعی"), default=False, db_index=True)
    is_gifted = models.BooleanField(_("هدیه"), default=False)

    raw_data = models.JSONField(_("داده خام سامیان"), default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("ردیف فروش سامیان")
        verbose_name_plural = _("ردیف‌های فروش سامیان")
        ordering = ("-transaction_date", "-samian_id")
        indexes = [
            models.Index(fields=["samian_barcode", "report_date"], name="samian_row_bc_date_idx"),
            models.Index(fields=["samian_product", "report_date"], name="samian_row_prod_date_idx"),
            models.Index(fields=["report_date", "warehouse_id"], name="samian_row_date_wh_idx"),
            models.Index(fields=["barcode", "report_date"], name="samian_row_bctext_date_idx"),
            models.Index(fields=["samian_warehouse", "report_date"], name="samian_row_wh_date_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.report_date} {self.barcode} x{self.quantity}"


# ---------------------------------------------------------------------------
# Price lists
# ---------------------------------------------------------------------------

class SamianPriceList(models.Model):
    samian_id = models.BigIntegerField(_("شناسه لیست قیمت در سامیان"), unique=True, db_index=True)
    name = models.CharField(_("نام لیست قیمت"), max_length=255, db_index=True)
    list_type = models.CharField(_("نوع لیست"), max_length=64, blank=True, default="")
    is_active = models.BooleanField(_("فعال"), default=True, db_index=True)
    valid_from = models.DateTimeField(_("از تاریخ"), null=True, blank=True)
    valid_to = models.DateTimeField(_("تا تاریخ"), null=True, blank=True)
    updated_at = models.DateTimeField(_("تاریخ آخرین بروزرسانی"), auto_now=True)

    class Meta:
        verbose_name = _("لیست قیمت سامیان")
        verbose_name_plural = _("لیست‌های قیمت سامیان")
        ordering = ("-valid_from",)

    def __str__(self) -> str:
        return self.name


class SamianPriceListItem(models.Model):
    samian_product = models.ForeignKey(
        SamianProduct, on_delete=models.CASCADE,
        related_name="price_list_items", verbose_name=_("محصول سامیان"),
    )
    price_list = models.ForeignKey(
        SamianPriceList, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="items", verbose_name=_("لیست قیمت"),
    )
    price_list_name = models.CharField(_("نام لیست قیمت"), max_length=255, db_index=True)
    list_price = models.BigIntegerField(_("قیمت در لیست (ریال)"), null=True, blank=True)
    discount_percent = models.DecimalField(_("درصد تخفیف در لیست"), max_digits=6, decimal_places=2, default=0)
    final_price = models.BigIntegerField(_("قیمت نهایی (ریال)"), null=True, blank=True, db_index=True)
    synced_at = models.DateTimeField(_("زمان سینک"), auto_now=True)

    class Meta:
        verbose_name = _("قیمت محصول در لیست")
        verbose_name_plural = _("قیمت‌های محصولات در لیست‌ها")
        constraints = [
            models.UniqueConstraint(
                fields=("samian_product", "price_list_name"),
                name="samian_unique_product_price_list",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.price_list_name}: {self.final_price}"


# ---------------------------------------------------------------------------
# Sync log
# ---------------------------------------------------------------------------

class SamianSyncLog(models.Model):
    class Action(models.TextChoices):
        SYNC_PRODUCTS = "sync_products", _("سینک محصولات")
        SYNC_COLORS = "sync_colors", _("سینک رنگ‌ها و تصاویر")
        SYNC_BARCODES = "sync_barcodes", _("سینک بارکدها")
        SYNC_INVENTORY = "sync_inventory", _("سینک موجودی")
        SYNC_PRICES = "sync_prices", _("سینک قیمت‌ها")
        SYNC_PRICES_INVENTORY = "sync_prices_inventory", _("سینک قیمت و موجودی")
        SYNC_SALES = "sync_sales", _("سینک فروش")
        SYNC_CUSTOMERS = "sync_customers", _("سینک مشتریان")
        SYNC_REFERENCE = "sync_reference", _("سینک برندها و انبارها")
        SYNC_ALL = "sync_all", _("سینک کامل ERP")

    class Status(models.TextChoices):
        STARTED = "started", _("شروع شده")
        RUNNING = "running", _("در حال اجرا")
        SUCCESS = "success", _("موفق")
        FAILED = "failed", _("ناموفق")

    action = models.CharField(_("نوع عملیات"), max_length=32, choices=Action.choices, db_index=True)
    status = models.CharField(_("وضعیت"), max_length=16, choices=Status.choices, default=Status.RUNNING)
    started_at = models.DateTimeField(_("زمان شروع"), auto_now_add=True)
    finished_at = models.DateTimeField(_("زمان پایان"), null=True, blank=True)
    records_read = models.IntegerField(_("تعداد رکورد خوانده‌شده"), default=0)
    records_upserted = models.IntegerField(_("تعداد رکورد ثبت‌شده"), default=0)
    error_message = models.TextField(_("پیام خطا"), blank=True, default="")
    details = models.JSONField(_("جزئیات آماری"), default=dict, blank=True)

    class Meta:
        verbose_name = _("لاگ سینک سامیان")
        verbose_name_plural = _("لاگ‌های سینک سامیان")
        ordering = ("-started_at",)

    def __str__(self) -> str:
        return f"{self.get_action_display()} - {self.get_status_display()} ({self.started_at})"
