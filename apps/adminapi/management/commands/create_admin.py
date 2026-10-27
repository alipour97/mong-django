"""
Management command: create or update an admin panel account.

The admin signs in with this mobile number and an SMS code; with --password
(asked interactively) also with a password.

    python manage.py create_admin 09121234567 --first-name علی --last-name پوراستاد
    python manage.py create_admin 09121234567 --password
"""
from __future__ import annotations

from getpass import getpass

from django.core.management.base import BaseCommand, CommandError

from apps.adminapi.models import AdminRole, AdminUser
from apps.smsir import normalize_mobile


class Command(BaseCommand):
    help = "ساخت یا ویرایش کاربر پنل ادمین"

    def add_arguments(self, parser):
        parser.add_argument("cellphone")
        parser.add_argument("--first-name", default=None)
        parser.add_argument("--last-name", default=None)
        parser.add_argument("--password", action="store_true", help="تعیین رمز عبور (پرسیده می‌شود)")

    def handle(self, *args, **opts):
        mobile = normalize_mobile(opts["cellphone"])
        if not (mobile.isdigit() and len(mobile) == 11 and mobile.startswith("09")):
            raise CommandError("شماره موبایل معتبر نیست")
        role = AdminRole.objects.filter(role_type=AdminRole.Type.ADMIN, is_deleted=False).first()
        user, created = AdminUser.objects.get_or_create(
            cellphone=mobile, defaults={"username": mobile, "role": role},
        )
        user.is_active, user.is_deleted = True, False
        if opts["first_name"] is not None:
            user.first_name = opts["first_name"]
        if opts["last_name"] is not None:
            user.last_name = opts["last_name"]
        if opts["password"]:
            raw = getpass("رمز عبور: ")
            if len(raw) < 8 or raw != getpass("تکرار رمز عبور: "):
                raise CommandError("رمز کوتاه‌تر از ۸ حرف است یا تکرارش یکی نیست")
            user.set_password(raw)
        user.save()
        self.stdout.write(self.style.SUCCESS(f"{'ساخته' if created else 'به‌روز'} شد: {user}"))
