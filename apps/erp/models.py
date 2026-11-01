"""
What the site sells, in one shape whichever software it comes from. The connectors
(apps/erp/samian.py, apps/erp/dadehfa.py) fill these tables on their schedule; the
storefront and the panel read only these, never a connector's own tables.
"""
from django.db import models

from apps.smsir import normalize_mobile


class ErpProduct(models.Model):
    # db_constraint off: import_dadehfa refreshes products by deleting and re-inserting them.
    product = models.OneToOneField(
        "website.Product", primary_key=True, on_delete=models.DO_NOTHING, db_constraint=False, related_name="erp",
    )
    erp_id = models.BigIntegerField("شناسه در نرم‌افزار", db_index=True)
    base_price = models.BigIntegerField("قیمت (ریال)", default=0)
    reduction = models.DecimalField("درصد تخفیف", max_digits=8, decimal_places=3, default=0)
    sale_price = models.BigIntegerField("قیمت بعد از تخفیف (ریال)", default=0)
    name_en = models.CharField("نام انگلیسی", max_length=512, blank=True, default="")
    subcode = models.CharField("کد فرعی", max_length=255, blank=True, default="")
    attributes = models.JSONField("ویژگی‌ها", default=dict, blank=True)
    size_guide_key = models.CharField("کلید عکس راهنمای سایز", max_length=255, blank=True, default="")
    sold = models.FloatField("فروش اخیر", default=0)
    synced_at = models.DateTimeField("آخرین همگام‌سازی")

    class Meta:
        verbose_name = "کالای فروش"
        verbose_name_plural = "کالاهای فروش"


class ErpVariant(models.Model):
    """A sellable color and size; its id is the site's productVariantId."""

    id = models.BigIntegerField(primary_key=True)
    product = models.ForeignKey(ErpProduct, on_delete=models.CASCADE, related_name="variants")
    erp_ref = models.BigIntegerField("شناسه در فاکتور نرم‌افزار", null=True, blank=True)
    barcode = models.CharField(max_length=255, blank=True, default="")
    color_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    color_name = models.CharField(max_length=255, blank=True, default="")
    color_value = models.CharField(max_length=64, blank=True, default="")
    color_priority = models.IntegerField(default=0)
    color_family = models.CharField(max_length=255, blank=True, default="")
    size_id = models.BigIntegerField(null=True, blank=True)
    size_name = models.CharField(max_length=255, blank=True, default="")
    size_value = models.CharField(max_length=255, blank=True, default="")
    size_priority = models.IntegerField(default=0)

    class Meta:
        verbose_name = "تنوع فروش"
        verbose_name_plural = "تنوع‌های فروش"


class ErpStock(models.Model):
    variant = models.ForeignKey(ErpVariant, on_delete=models.CASCADE, related_name="stock")
    warehouse_id = models.BigIntegerField(db_index=True)
    warehouse_title = models.CharField(max_length=255, blank=True, default="")
    qty = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        verbose_name = "موجودی"
        verbose_name_plural = "موجودی‌ها"
        constraints = [models.UniqueConstraint(fields=["variant", "warehouse_id"], name="erp_stock_per_warehouse")]


class ErpImage(models.Model):
    """One photo or video. The built copy (key) is used when there is one, else source."""

    product = models.ForeignKey(ErpProduct, on_delete=models.CASCADE, related_name="images")
    color_id = models.BigIntegerField(null=True, blank=True)
    source_id = models.BigIntegerField(default=0)  # the image id the site shows
    key = models.CharField(max_length=255, blank=True, default="")
    source = models.CharField(max_length=1024, blank=True, default="")
    is_video = models.BooleanField(default=False)
    alternative = models.CharField(max_length=512, blank=True, default="")
    tooltip_title = models.CharField(max_length=512, blank=True, default="")
    position = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "عکس فروش"
        verbose_name_plural = "عکس‌های فروش"
        ordering = ["position"]


class SiteCoupon(models.Model):
    """A discount code made on this site, in the Django admin. The software's own coupons stay in the software."""

    serial = models.CharField("کد", max_length=100, unique=True)
    reduction = models.DecimalField("درصد تخفیف", max_digits=5, decimal_places=2)
    mobile = models.CharField("موبایل مشتری", max_length=20, blank=True, default="", help_text="خالی: برای همهٔ مشتریان، هر نفر یک بار")
    min_price = models.BigIntegerField("حداقل مبلغ فاکتور (ریال)", default=0)
    max_price = models.BigIntegerField("حداکثر مبلغ فاکتور (ریال)", null=True, blank=True)
    expires = models.DateTimeField("پایان اعتبار", null=True, blank=True)
    is_active = models.BooleanField("فعال", default=True)
    created = models.DateTimeField("ایجاد", auto_now_add=True)

    class Meta:
        verbose_name = "کوپن سایت"
        verbose_name_plural = "کوپن‌های سایت"
        ordering = ["-id"]

    def __str__(self) -> str:
        return self.serial

    def save(self, *args, **kwargs):
        self.mobile = normalize_mobile(self.mobile)
        super().save(*args, **kwargs)


class SiteGiftCard(models.Model):
    """A gift card made on this site, in the Django admin. What is left is the amount less the paid orders."""

    number = models.CharField("شماره کارت", max_length=100, unique=True)
    mobile = models.CharField("موبایل مشتری", max_length=20)
    amount = models.BigIntegerField("مبلغ کارت (ریال)")
    min_price = models.BigIntegerField("حداقل مبلغ فاکتور (ریال)", default=0)
    starts = models.DateTimeField("شروع اعتبار", null=True, blank=True)
    expires = models.DateTimeField("پایان اعتبار", null=True, blank=True)
    use_whole = models.BooleanField("یک‌بار مصرف", default=False, help_text="با اولین خرید، باقی‌ماندهٔ کارت هم از بین می‌رود")
    is_active = models.BooleanField("فعال", default=True)
    created = models.DateTimeField("ایجاد", auto_now_add=True)

    class Meta:
        verbose_name = "کارت هدیهٔ سایت"
        verbose_name_plural = "کارت‌های هدیهٔ سایت"
        ordering = ["-id"]

    def __str__(self) -> str:
        return self.number

    def save(self, *args, **kwargs):
        self.mobile = normalize_mobile(self.mobile)
        super().save(*args, **kwargs)


class LebazaiImage(models.Model):
    """An approved LEBAZAI image of a color, built into the local image store, or one uploaded by hand (key up/...)."""

    product_id = models.BigIntegerField(db_index=True)
    color_id = models.BigIntegerField()
    key = models.CharField(max_length=128)
    source_url = models.URLField(max_length=1000)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "عکس LEBAZAI"
        verbose_name_plural = "عکس‌های LEBAZAI"
        ordering = ["color_id", "position"]
        constraints = [models.UniqueConstraint(fields=["product_id", "color_id", "key"], name="erp_lebazai_image")]


class ManualPhoto(LebazaiImage):
    """A photo uploaded in the Django admin for what LEBAZAI has no photo of. The nightly sync leaves it alone."""

    class Meta:
        proxy = True
        verbose_name = "عکس دستی"
        verbose_name_plural = "عکس‌های دستی"
