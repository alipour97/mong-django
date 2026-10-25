"""
Django ORM Models for storing Samian ERP synchronized data.

Mirroring Samian ERP core entities:
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
- SamianSyncLog: Audit and history of synchronization jobs
"""
from __future__ import annotations

import logging
from typing import Any
from django.db import models
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)


class SamianBrand(models.Model):
    """
    Brand entity from Samian ERP (GET /v2/product/codingbrand).
    """
    samian_id = models.BigIntegerField(_("شناسه برند در سامیان"), unique=True, db_index=True)
    title = models.CharField(_("نام برند"), max_length=255, db_index=True)
    title_en = models.CharField(_("نام انگلیسی"), max_length=255, blank=True, default="")
    brand_code = models.CharField(_("کد برند"), max_length=64, blank=True, default="")
    erp_code = models.CharField(_("کد ERP"), max_length=64, blank=True, default="")
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
        verbose_name=_("برند والد"),
    )
    supplier_name = models.CharField(_("تأمین‌کننده"), max_length=255, blank=True, default="")
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
    """
    Department tree node from Samian ERP (GET /v2/product/codingdepartment).
    """
    samian_id = models.BigIntegerField(_("شناسه دپارتمان در سامیان"), unique=True, db_index=True)
    title = models.CharField(_("عنوان دپارتمان"), max_length=255, db_index=True)
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
        verbose_name=_("دپارتمان والد"),
    )
    current_level = models.IntegerField(_("سطح در درخت"), null=True, blank=True)
    department1 = models.CharField(_("دپارتمان سطح ۱ (ریشه)"), max_length=255, blank=True, default="")
    department2 = models.CharField(_("دپارتمان سطح ۲"), max_length=255, blank=True, default="")
    department3 = models.CharField(_("دپارتمان سطح ۳ (برگ)"), max_length=255, blank=True, default="")
    raw_data = models.JSONField(_("داده خام سامیان"), default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("دپارتمان سامیان")
        verbose_name_plural = _("دپارتمان‌های سامیان")
        ordering = ("samian_id",)

    def __str__(self) -> str:
        return self.title or str(self.samian_id)


class SamianWarehouse(models.Model):
    """
    Warehouse definition from Samian ERP (GET /v2/accounting/warehouse).
    """
    samian_id = models.BigIntegerField(_("شناسه انبار در سامیان"), unique=True, db_index=True)
    title = models.CharField(_("نام انبار"), max_length=255, db_index=True)
    department_id = models.BigIntegerField(_("شناسه دپارتمان متصل"), null=True, blank=True)
    is_active = models.BooleanField(_("فعال"), default=True)
    raw_data = models.JSONField(_("داده خام سامیان"), default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("انبار سامیان")
        verbose_name_plural = _("انبارهای سامیان")
        ordering = ("samian_id",)

    def __str__(self) -> str:
        return self.title or f"انبار {self.samian_id}"


class SamianProduct(models.Model):
    """
    Product Master record from Samian ERP (GET /v2/product/productmain).
    """
    samian_id = models.BigIntegerField(
        _("شناسه محصول در سامیان"),
        unique=True,
        db_index=True,
        help_text=_("فیلد productmain_id در سامیان"),
    )
    subcode = models.CharField(
        _("کد فرعی (subcode)"),
        max_length=128,
        blank=True,
        db_index=True,
        help_text=_("فیلد k_bar_code در سامیان"),
    )
    name = models.CharField(_("نام کالا"), max_length=255, blank=True, default="")
    name_en = models.CharField(_("نام انگلیسی"), max_length=512, blank=True, default="")
    description = models.TextField(_("توضیحات"), blank=True, default="")

    brand_name = models.CharField(_("نام برند"), max_length=255, blank=True, default="")
    samian_brand = models.ForeignKey(
        SamianBrand,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
        verbose_name=_("برند سامیان"),
    )
    department_name = models.CharField(_("نام دپارتمان"), max_length=255, blank=True, default="")
    samian_department = models.ForeignKey(
        SamianDepartment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
        verbose_name=_("دپارتمان سامیان"),
    )

    category = models.CharField(_("دسته‌بندی"), max_length=255, blank=True, default="")
    season = models.CharField(_("فصل"), max_length=255, blank=True, default="")
    season_code = models.CharField(_("کد فصل"), max_length=64, blank=True, default="", db_index=True)
    style = models.CharField(_("استایل"), max_length=255, blank=True, default="")
    material = models.CharField(_("جنس / متریال"), max_length=255, blank=True, default="")

    is_active = models.BooleanField(_("فعال"), default=True)
    is_saleable = models.BooleanField(_("قابل فروش"), default=True)

    raw_data = models.JSONField(_("داده خام سامیان"), default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("محصول سامیان")
        verbose_name_plural = _("محصولات سامیان")
        ordering = ("-samian_id",)

    def __str__(self) -> str:
        return f"{self.subcode} - {self.name}" if self.subcode else (self.name or str(self.samian_id))


class SamianProductColor(models.Model):
    """
    Color record from Samian ERP (GET /v2/product/colors).
    Target for binding uploaded images in `colorsgalery`.
    """
    samian_id = models.BigIntegerField(_("شناسه رکورد رنگ در سامیان"), unique=True, db_index=True)
    samian_product = models.ForeignKey(
        SamianProduct,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="colors",
        verbose_name=_("محصول متناظر"),
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

    def __str__(self) -> str:
        return f"{self.productmain_id} - {self.color_name} (ID: {self.samian_id})"


class SamianBarcode(models.Model):
    """
    Barcode / SKU record from Samian ERP (GET /v2/product/barcodemain).
    """
    samian_id = models.BigIntegerField(_("شناسه بارکد در سامیان"), unique=True, db_index=True)
    barcode = models.CharField(_("بارکد (kbarcode)"), max_length=128, db_index=True)
    subcode = models.CharField(_("کد فرعی کالا"), max_length=128, blank=True, default="", db_index=True)
    samian_product = models.ForeignKey(
        SamianProduct,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="barcodes",
        verbose_name=_("محصول مرتبط"),
    )
    productmain_id = models.BigIntegerField(_("شناسه محصول"), null=True, blank=True, db_index=True)
    color_name = models.CharField(_("نام رنگ"), max_length=128, blank=True, default="")
    size_name = models.CharField(_("سایز"), max_length=64, blank=True, default="")

    buy_price = models.BigIntegerField(_("قیمت خرید (ریال)"), default=0)
    sale_price = models.BigIntegerField(_("قیمت فروش (ریال)"), default=0)
    discount_percent = models.DecimalField(_("درصد تخفیف"), max_digits=5, decimal_places=2, default=0)
    is_active = models.BooleanField(_("فعال"), default=True)

    raw_data = models.JSONField(_("داده خام سامیان"), default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("بارکد سامیان")
        verbose_name_plural = _("بارکدهای سامیان")
        ordering = ("-samian_id",)

    def __str__(self) -> str:
        return f"{self.barcode} ({self.size_name} - {self.color_name})"


class SamianInventory(models.Model):
    """
    Stock levels per barcode & warehouse from Samian ERP (GET /v2/wm/stock).
    """
    samian_id = models.BigIntegerField(_("شناسه موجودی در سامیان"), unique=True, db_index=True)
    samian_barcode = models.ForeignKey(
        SamianBarcode,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="inventory_rows",
        verbose_name=_("بارکد"),
    )
    barcode = models.CharField(_("بارکد"), max_length=128, blank=True, default="", db_index=True)
    barcodemain_id = models.BigIntegerField(_("شناسه بارکد در سامیان"), db_index=True)
    samian_warehouse = models.ForeignKey(
        SamianWarehouse,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="stocks",
        verbose_name=_("انبار"),
    )
    warehouse_id = models.BigIntegerField(_("شناسه انبار"), db_index=True)
    count = models.IntegerField(_("تعداد موجودی"), default=0)
    updated_at_samian = models.DateTimeField(_("تاریخ بروزرسانی در سامیان"), null=True, blank=True)

    raw_data = models.JSONField(_("داده خام سامیان"), default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("موجودی انبار سامیان")
        verbose_name_plural = _("موجودی‌های انبار سامیان")
        unique_together = ("barcodemain_id", "warehouse_id")

    def __str__(self) -> str:
        return f"بارکد {self.barcodemain_id} | انبار {self.warehouse_id}: {self.count}"


class SamianCustomer(models.Model):
    """
    Customer entity from Samian ERP (GET /v2/retail/poscustomer).
    """
    samian_id = models.BigIntegerField(_("شناسه مشتری در سامیان"), unique=True, db_index=True)
    first_name = models.CharField(_("نام"), max_length=128, blank=True, default="")
    last_name = models.CharField(_("نام خانوادگی"), max_length=128, blank=True, default="")
    cellphone = models.CharField(_("شماره موبایل"), max_length=32, blank=True, default="", db_index=True)
    national_code = models.CharField(_("کد ملی"), max_length=32, blank=True, default="")
    raw_data = models.JSONField(_("داده خام سامیان"), default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("مشتری سامیان")
        verbose_name_plural = _("مشتریان سامیان")

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name} ({self.cellphone})"


class SamianSalesTransaction(models.Model):
    """
    Retail sales transaction from Samian ERP (GET /v2/retail/postransaction).
    """
    samian_id = models.BigIntegerField(_("شناسه فاکتور در سامیان"), unique=True, db_index=True)
    transaction_code = models.CharField(_("کد فاکتور"), max_length=128, blank=True, default="", db_index=True)
    transaction_unique_id = models.CharField(_("شناسه یکتای تراکنش"), max_length=64, blank=True, default="", db_index=True)
    transaction_date = models.DateTimeField(_("تاریخ فاکتور"), null=True, blank=True)
    customer_samian_id = models.BigIntegerField(_("شناسه مشتری"), null=True, blank=True)
    samian_customer = models.ForeignKey(
        SamianCustomer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
        verbose_name=_("مشتری"),
    )
    warehouse_id = models.BigIntegerField(_("شناسه انبار"), null=True, blank=True)
    total_amount = models.BigIntegerField(_("مبلغ کل (ریال)"), default=0)
    total_discount = models.BigIntegerField(_("مجموع تخفیف (ریال)"), default=0)
    net_amount = models.BigIntegerField(_("مبلغ نهایی پرداختی (ریال)"), default=0)
    status = models.CharField(_("وضعیت"), max_length=128, blank=True, default="")
    store_order_id = models.BigIntegerField(_("شناسه سفارش وبسایت"), null=True, blank=True, db_index=True)
    delivery_address = models.TextField(_("آدرس تحویل"), blank=True, default="")

    raw_data = models.JSONField(_("داده خام سامیان"), default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("فاکتور فروش سامیان")
        verbose_name_plural = _("فاکتورهای فروش سامیان")
        ordering = ("-transaction_date",)

    def __str__(self) -> str:
        return f"فاکتور {self.transaction_code or self.samian_id} ({self.net_amount:,} ریال)"


class SamianSalesRow(models.Model):
    """
    Sold line item from Samian ERP (GET /v2/retail/postransactionitems).
    """
    samian_id = models.BigIntegerField(_("شناسه ردیف فروش"), unique=True, db_index=True)
    transaction = models.ForeignKey(
        SamianSalesTransaction,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="rows",
        verbose_name=_("فاکتور"),
    )
    transaction_samian_id = models.BigIntegerField(_("شناسه فاکتور در سامیان"), db_index=True)
    barcode = models.CharField(_("بارکد کالا"), max_length=128, blank=True, default="")
    item_name = models.CharField(_("نام کالا"), max_length=255, blank=True, default="")
    quantity = models.DecimalField(_("تعداد / مقدار"), max_digits=10, decimal_places=2, default=1)
    unit_price = models.BigIntegerField(_("قیمت واحد (ریال)"), default=0)
    discount_amount = models.BigIntegerField(_("مبلغ تخفیف (ریال)"), default=0)
    line_revenue = models.BigIntegerField(_("مبلغ ردیف (ریال)"), default=0)

    raw_data = models.JSONField(_("داده خام سامیان"), default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("ردیف فروش سامیان")
        verbose_name_plural = _("ردیف‌های فروش سامیان")

    def __str__(self) -> str:
        return f"{self.item_name} x {self.quantity} (فاکتور {self.transaction_samian_id})"


class SamianSyncLog(models.Model):
    """
    Audit log for tracking background synchronization tasks with Samian ERP.
    """
    class Action(models.TextChoices):
        SYNC_PRODUCTS = "sync_products", _("سینک محصولات")
        SYNC_COLORS = "sync_colors", _("سینک رنگ‌ها و تصاویر")
        SYNC_BARCODES = "sync_barcodes", _("سینک بارکدها")
        SYNC_INVENTORY = "sync_inventory", _("سینک موجودی")
        SYNC_SALES = "sync_sales", _("سینک فروش")
        SYNC_ALL = "sync_all", _("سینک کامل ERP")

    class Status(models.TextChoices):
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
