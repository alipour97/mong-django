"""
Admin panel accounts.

Admins sign in with their mobile number and either a password or a one-time
SMS code. Accounts and roles were imported from DadehfaOnlineShop (ids kept);
their old password hashes still work (passwords.py) and are replaced with a
Django hash the first time each admin signs in.
"""
from __future__ import annotations

import hashlib
import secrets

from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class AdminRole(models.Model):
    class Type(models.IntegerChoices):
        ADMIN = 1, _("ادمین")
        USER = 2, _("کاربر")

    id = models.IntegerField(primary_key=True)
    title = models.CharField(_("عنوان"), max_length=128)
    role_type = models.IntegerField(_("نوع"), choices=Type.choices, default=Type.USER)
    is_deleted = models.BooleanField(_("حذف شده"), default=False)

    class Meta:
        verbose_name = _("نقش ادمین")
        verbose_name_plural = _("نقش‌های ادمین")

    def __str__(self) -> str:
        return self.title


class AdminUser(models.Model):
    username = models.CharField(_("نام کاربری"), max_length=150, unique=True)
    cellphone = models.CharField(_("موبایل"), max_length=20, unique=True)
    email = models.CharField(_("ایمیل"), max_length=254, blank=True, default="")
    first_name = models.CharField(_("نام"), max_length=150, blank=True, default="")
    last_name = models.CharField(_("نام خانوادگی"), max_length=150, blank=True, default="")
    role = models.ForeignKey(AdminRole, null=True, blank=True, on_delete=models.SET_NULL, verbose_name=_("نقش"))
    is_active = models.BooleanField(_("فعال"), default=True)
    is_deleted = models.BooleanField(_("حذف شده"), default=False)
    send_invoice_sms = models.BooleanField(_("پیامک فاکتورها"), default=False)

    password = models.CharField(_("رمز عبور"), max_length=256, blank=True, default="", editable=False)
    # Dadehfa's Argon2 hash and its two keys; cleared once the admin signs in here.
    legacy_password = models.CharField(max_length=512, blank=True, default="", editable=False)
    legacy_public_key = models.CharField(max_length=512, blank=True, default="", editable=False)
    legacy_secret_key = models.CharField(max_length=512, blank=True, default="", editable=False)
    refresh_token_hash = models.CharField(max_length=64, blank=True, default="", editable=False)

    created = models.DateTimeField(_("ایجاد"), default=timezone.now)
    last_login = models.DateTimeField(_("آخرین ورود"), null=True, blank=True)

    class Meta:
        verbose_name = _("کاربر ادمین")
        verbose_name_plural = _("کاربران ادمین")
        ordering = ("id",)

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name} ({self.cellphone})".strip()

    # Lets DRF's IsAuthenticated accept an AdminUser as request.user.
    is_authenticated = True

    @property
    def has_password(self) -> bool:
        return bool(self.password or self.legacy_password)

    def set_password(self, raw: str) -> None:
        self.password = make_password(raw)
        self.legacy_password = self.legacy_public_key = self.legacy_secret_key = ""

    def check_password(self, raw: str) -> bool:
        """Django hash, or the Dadehfa one (then upgraded to a Django hash)."""
        if self.password:
            return check_password(raw, self.password)
        if self.legacy_password:
            from .passwords import legacy_hash

            if secrets.compare_digest(legacy_hash(raw, self.legacy_public_key, self.legacy_secret_key), self.legacy_password):
                self.set_password(raw)
                self.save(update_fields=["password", "legacy_password", "legacy_public_key", "legacy_secret_key"])
                return True
        return False

    def new_refresh_token(self) -> str:
        token = secrets.token_hex(32)
        self.refresh_token_hash = hashlib.sha256(token.encode()).hexdigest()
        return token

    def check_refresh_token(self, token: str) -> bool:
        digest = hashlib.sha256((token or "").encode()).hexdigest()
        return bool(self.refresh_token_hash) and secrets.compare_digest(digest, self.refresh_token_hash)


class AdminOtp(models.Model):
    """A one-time sign-in code sent by SMS. Only its hash is stored."""

    cellphone = models.CharField(max_length=20, db_index=True)
    code_hash = models.CharField(max_length=256)
    created = models.DateTimeField(default=timezone.now)
    expires = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used = models.BooleanField(default=False)

    class Meta:
        verbose_name = _("کد ورود ادمین")
        verbose_name_plural = _("کدهای ورود ادمین")
        ordering = ("-created",)
