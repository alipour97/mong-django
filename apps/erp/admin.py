import hashlib

from django import forms
from django.contrib import admin
from django.utils import timezone

from apps.website import images

from . import store, vouchers
from .models import ErpWriteLog, ManualPhoto, SiteCoupon, SiteGiftCard

MANUAL_PREFIX = "up/"


@admin.register(SiteCoupon)
class SiteCouponAdmin(admin.ModelAdmin):
    list_display = ("serial", "reduction", "mobile", "min_price", "max_price", "expires", "is_active", "used")
    list_filter = ("is_active",)
    search_fields = ("serial", "mobile")

    @admin.display(description="تعداد استفاده")
    def used(self, coupon: SiteCoupon) -> int:
        return vouchers.times_used(coupon)


@admin.register(SiteGiftCard)
class SiteGiftCardAdmin(admin.ModelAdmin):
    list_display = ("number", "mobile", "amount", "left", "min_price", "expires", "use_whole", "is_active")
    list_filter = ("is_active",)
    search_fields = ("number", "mobile")

    @admin.display(description="مانده (ریال)")
    def left(self, card: SiteGiftCard) -> int:
        return vouchers.site_card_left(card)


@admin.register(ErpWriteLog)
class ErpWriteLogAdmin(admin.ModelAdmin):
    """Everything this site wrote in the sales software. Read only: it is the record of what happened."""

    list_display = ("id", "invoice_id", "software", "action", "result", "ok", "created")
    list_filter = ("ok", "software", "action")
    search_fields = ("invoice_id", "error")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ManualPhotoForm(forms.ModelForm):
    barcode = forms.CharField(label="بارکد کالا", help_text="بارکد یکی از سایزهای همان رنگ در نرم‌افزار فروش")
    photo = forms.FileField(label="عکس")

    class Meta:
        model = ManualPhoto
        fields = ["position"]

    def clean_barcode(self):
        barcode = self.cleaned_data["barcode"].strip()
        match = next(((pid, color) for code, pid, color in store.barcodes() if code == barcode), None)
        if match is None:
            raise forms.ValidationError("این بارکد در کالاهای قابل فروش (دستهٔ آنلاین فعال) پیدا نشد.")
        self.product_id, self.color_id = match
        return barcode


@admin.register(ManualPhoto)
class ManualPhotoAdmin(admin.ModelAdmin):
    form = ManualPhotoForm
    list_display = ("product_id", "color_id", "key", "position")
    search_fields = ("product_id",)

    def get_queryset(self, request):
        return super().get_queryset(request).filter(key__startswith=MANUAL_PREFIX)

    def has_change_permission(self, request, obj=None):
        return obj is None

    def save_model(self, request, obj, form, change):
        data = form.cleaned_data["photo"].read()
        obj.key = MANUAL_PREFIX + hashlib.sha1(data).hexdigest()
        obj.product_id, obj.color_id, obj.source_url = form.product_id, form.color_id, f"manual:{timezone.now():%Y-%m-%d}"
        images.build(obj.key, data)
        super().save_model(request, obj, form, change)
