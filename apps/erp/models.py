"""
What the sales software hands the site beyond products (those are website.Product and friends):
its coupons and gift cards as the last sync read them, and the record of what the site wrote there.
Also the site's own vouchers and the photos from LEBAZAI.
"""
from django.db import models

from apps.smsir import normalize_mobile


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


class ErpCoupon(models.Model):
    """The software's coupon as the last sync read it; the id is the software's. Checked here, never there."""

    id = models.BigIntegerField(primary_key=True)
    customer_erp_id = models.BigIntegerField("مشتری در نرم‌افزار", null=True, blank=True, db_index=True)  # empty: a general coupon
    serial = models.CharField("کد", max_length=100, db_index=True)
    reduction = models.DecimalField("درصد تخفیف", max_digits=8, decimal_places=2, default=0)
    min_price = models.BigIntegerField("حداقل مبلغ فاکتور (ریال)", default=0)
    max_price = models.BigIntegerField("حداکثر مبلغ فاکتور (ریال)", null=True, blank=True)
    expires = models.DateTimeField("پایان اعتبار", null=True, blank=True)
    is_used = models.BooleanField("استفاده شده", default=False)
    used_at = models.DateTimeField("زمان استفاده", null=True, blank=True)
    is_active = models.BooleanField("فعال", default=True)
    held_until = models.DateTimeField("تعلیق تا", null=True, blank=True)
    created = models.DateTimeField("ایجاد", null=True, blank=True)
    first_name = models.CharField(max_length=128, blank=True, default="")
    last_name = models.CharField(max_length=128, blank=True, default="")
    listed = models.BooleanField("در لیست پنل", default=True)  # a general coupon stands for its customers' copies
    search_text = models.TextField(blank=True, default="", editable=False)  # catalog.norm of what the panel searches

    class Meta:
        verbose_name = "کوپن نرم‌افزار"
        verbose_name_plural = "کوپن‌های نرم‌افزار"
        ordering = ["-id"]

    def __str__(self) -> str:
        return self.serial


class ErpGiftCard(models.Model):
    """The software's gift card as the last sync read it; the id is the software's. Checked here, never there."""

    id = models.BigIntegerField(primary_key=True)
    number = models.CharField("شماره کارت", max_length=100, db_index=True)
    customer_erp_id = models.BigIntegerField("مشتری در نرم‌افزار", null=True, blank=True, db_index=True)
    mobile = models.CharField("موبایل مشتری", max_length=20, blank=True, default="", db_index=True)
    balance = models.BigIntegerField("مانده (ریال)", default=0)
    min_price = models.BigIntegerField("حداقل مبلغ فاکتور (ریال)", default=0)
    starts = models.DateTimeField("شروع اعتبار", null=True, blank=True)
    expires = models.DateTimeField("پایان اعتبار", null=True, blank=True)
    is_active = models.BooleanField("فعال", default=True)
    use_whole = models.BooleanField("یک‌بار مصرف", default=False)
    use_dep_code = models.BooleanField(default=False)
    held_until = models.DateTimeField("تعلیق تا", null=True, blank=True)
    created = models.DateTimeField("ایجاد", null=True, blank=True)
    gift_group_map_id = models.CharField(max_length=64, blank=True, default="")
    customer_map_id = models.CharField(max_length=64, blank=True, default="")
    first_name = models.CharField(max_length=128, blank=True, default="")
    last_name = models.CharField(max_length=128, blank=True, default="")
    invoice_count = models.IntegerField("تعداد فاکتور", default=0)
    search_text = models.TextField(blank=True, default="", editable=False)  # catalog.norm of what the panel searches

    class Meta:
        verbose_name = "کارت هدیهٔ نرم‌افزار"
        verbose_name_plural = "کارت‌های هدیهٔ نرم‌افزار"
        ordering = ["-created", "-id"]

    def __str__(self) -> str:
        return self.number


class ErpWriteLog(models.Model):
    """One statement this site sent to write in the sales software, and how its transaction ended."""

    invoice_id = models.BigIntegerField("فاکتور سایت", db_index=True)
    software = models.CharField("نرم‌افزار", max_length=32)
    action = models.CharField("عمل", max_length=128, blank=True, default="")  # INSERT Invoices, UPDATE GiftCards...
    statement = models.TextField("دستور", blank=True, default="")
    params = models.JSONField("مقادیر", default=dict, blank=True)
    result = models.CharField("شناسهٔ برگشتی", max_length=64, blank=True, default="")
    ok = models.BooleanField("ثبت شد", default=False)
    error = models.TextField("خطا", blank=True, default="")
    created = models.DateTimeField("زمان", auto_now_add=True)

    class Meta:
        verbose_name = "لاگ نوشتن در نرم‌افزار"
        verbose_name_plural = "لاگ‌های نوشتن در نرم‌افزار"
        ordering = ["-id"]

    def __str__(self) -> str:
        return f"{self.invoice_id}: {self.action}"


class SyncState(models.Model):
    """When a sync last finished well."""

    name = models.CharField(max_length=64, unique=True)
    at = models.DateTimeField()

    class Meta:
        verbose_name = "وضعیت همگام‌سازی"
        verbose_name_plural = "وضعیت همگام‌سازی"

    def __str__(self) -> str:
        return self.name


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
