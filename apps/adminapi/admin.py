from django import forms
from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import AdminRole, AdminUser
from .passwords import problems


@admin.register(AdminRole)
class AdminRoleAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "role_type", "is_deleted")


class AdminUserForm(forms.ModelForm):
    """The admin's fields plus an optional new password, set only when both boxes are filled."""

    new_password1 = forms.CharField(
        label=_("رمز عبور جدید"), required=False, strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text=_("خالی بماند تا رمز فعلی عوض نشود. با تغییر رمز، ورودهای قبلی این ادمین هم باطل می‌شوند."),
    )
    new_password2 = forms.CharField(
        label=_("تکرار رمز عبور جدید"), required=False, strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    class Meta:
        model = AdminUser
        fields = "__all__"

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("new_password1"), data.get("new_password2")
        if p1 or p2:
            if p1 != p2:
                self.add_error("new_password2", _("دو رمز عبور یکسان نیستند."))
            else:
                for problem in problems(p1, self.instance):
                    self.add_error("new_password1", problem)
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        raw = self.cleaned_data.get("new_password1")
        if raw:
            user.set_password(raw)
            user.refresh_token_hash = ""  # sign out other devices once their access token expires
        if commit:
            user.save()
        return user


@admin.register(AdminUser)
class AdminUserAdmin(admin.ModelAdmin):
    form = AdminUserForm
    list_display = ("id", "first_name", "last_name", "cellphone", "role", "has_password", "is_active", "is_deleted", "last_login")
    list_filter = ("is_active", "is_deleted", "role")
    search_fields = ("first_name", "last_name", "cellphone", "username")
    readonly_fields = ("created", "last_login")
    fieldsets = (
        (None, {"fields": ("username", "cellphone", "email", "first_name", "last_name", "role")}),
        (_("وضعیت"), {"fields": ("is_active", "is_deleted", "send_invoice_sms")}),
        (_("رمز عبور"), {"fields": ("new_password1", "new_password2")}),
        (_("تاریخ‌ها"), {"fields": ("created", "last_login")}),
    )

    @admin.display(boolean=True, description=_("رمز دارد"))
    def has_password(self, obj: AdminUser) -> bool:
        return obj.has_password
