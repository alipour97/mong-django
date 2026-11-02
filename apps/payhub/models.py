from django.db import models
from django.utils.translation import gettext_lazy as _


class PayRecord(models.Model):
    """One payment through the hub, for the new site (in process) or the old one (over HTTP)."""

    class State(models.TextChoices):
        CREATED = "created", _("ساخته شده")
        STARTING = "starting", _("در حال اتصال به درگاه")
        REDIRECTED = "redirected", _("منتقل شده به درگاه")
        VERIFYING = "verifying", _("در حال تایید")
        RETURNED = "returned", _("برگشته از درگاه")  # SnappPay: already verified
        CONFIRMING = "confirming", _("در حال نهایی کردن")
        CONSUMED = "consumed", _("نهایی شده")  # Zarinpal verified / SnappPay settled, and handed over once
        FAILED = "failed", _("ناموفق")
        REVERTED = "reverted", _("برگشت داده شده")
        UNKNOWN = "unknown", _("نامشخص، در انتظار استعلام")  # asked again after 40 minutes
        REVIEW = "review", _("نیازمند بررسی کارشناس")

    class Source(models.TextChoices):
        SITE = "site", _("سایت جدید")
        LEGACY = "legacy", _("سایت قدیم")

    token = models.CharField(max_length=32, unique=True)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.LEGACY, db_index=True)
    gateway = models.CharField(max_length=32)  # zarinpal, snapppay
    amount = models.BigIntegerField()  # rial
    success_callback = models.CharField(max_length=2000)
    failed_callback = models.CharField(max_length=2000)
    cell_phone = models.CharField(max_length=32, blank=True, default="")
    customer_key = models.CharField(max_length=64, blank=True, default="")
    company_id = models.BigIntegerField(default=0)
    merchant_id = models.CharField(max_length=64, blank=True, default="")
    transaction_id = models.CharField(max_length=64, blank=True, default="", db_index=True)  # the caller's invoice id
    authority = models.CharField(max_length=255, blank=True, default="", db_index=True)  # Zarinpal
    ref_id = models.CharField(max_length=64, blank=True, default="")  # Zarinpal
    card_pan = models.CharField(max_length=64, blank=True, default="")
    payment_token = models.CharField(max_length=255, blank=True, default="", db_index=True)  # SnappPay
    payment_page_url = models.CharField(max_length=2000, blank=True, default="")  # SnappPay
    gateway_transaction_id = models.CharField(max_length=32, blank=True, default="", db_index=True)  # SnappPay, 5-10 digits
    state = models.CharField(max_length=16, choices=State.choices, default=State.CREATED, db_index=True)
    error = models.TextField(blank=True, default="")
    events = models.JSONField(default=list, blank=True)  # what happened, with the gateway's replies
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("پرداخت هاب")
        verbose_name_plural = _("پرداخت‌های هاب")
        ordering = ("-id",)

    def __str__(self) -> str:
        return f"{self.gateway} #{self.id} ({self.get_state_display()})"


class SnappLog(models.Model):
    """One call to SnappPay, whatever came of it. Passwords and access tokens are never stored."""

    created = models.DateTimeField(_("زمان"), auto_now_add=True, db_index=True)
    method = models.CharField(_("روش"), max_length=8)
    path = models.CharField(_("مسیر"), max_length=128, db_index=True)
    request = models.JSONField(_("درخواست"), default=dict, blank=True)
    http_status = models.IntegerField(_("کد HTTP"), null=True, blank=True)  # empty: no answer
    response = models.TextField(_("پاسخ"), blank=True, default="")
    successful = models.BooleanField(_("موفق"), default=False, db_index=True)
    error = models.CharField(_("خطای ارتباط"), max_length=128, blank=True, default="")
    duration_ms = models.IntegerField(_("مدت (میلی‌ثانیه)"), default=0)
    payment_token = models.CharField(_("توکن پرداخت"), max_length=255, blank=True, default="", db_index=True)
    transaction_id = models.CharField(_("شناسه تراکنش"), max_length=64, blank=True, default="", db_index=True)

    class Meta:
        verbose_name = _("لاگ اسنپ‌پی")
        verbose_name_plural = _("لاگ‌های اسنپ‌پی")
        ordering = ("-id",)

    def __str__(self) -> str:
        return f"{self.method} {self.path} ({self.http_status or self.error})"
