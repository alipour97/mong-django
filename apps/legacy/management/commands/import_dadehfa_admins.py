"""
Management command: copy admin panel accounts and roles from DadehfaOnlineShop (read only).

Ids are kept. The old Argon2 password hash and its keys are copied so admins
keep their passwords (checked by apps/adminapi/passwords.py, then replaced
with a Django hash on first sign-in). Rows are created or updated by id; an
account whose password was already changed here keeps the new one.

    python manage.py import_dadehfa_admins
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.core.management.color import no_style
from django.db import connection, transaction

from apps.adminapi.models import AdminRole, AdminUser
from apps.legacy.db import fetch_all


def _s(v) -> str:
    return "" if v is None else str(v).strip()


class Command(BaseCommand):
    help = "ورود کاربران و نقش‌های پنل ادمین از داده‌فا (فقط خواندنی)"

    def handle(self, *args, **options):
        with transaction.atomic():
            for r in fetch_all("SELECT Id, RoleTitle, RoleType, IsDeleted FROM Roles"):
                AdminRole.objects.update_or_create(id=r["Id"], defaults={
                    "title": _s(r["RoleTitle"]), "role_type": r["RoleType"] or AdminRole.Type.USER,
                    "is_deleted": bool(r["IsDeleted"]),
                })
            roles = set(AdminRole.objects.values_list("id", flat=True))
            for r in fetch_all("SELECT * FROM Users"):
                existing = AdminUser.objects.filter(id=r["Id"]).first()
                fields = {
                    "username": _s(r["Username"]) or _s(r["CellPhone"]),
                    "cellphone": _s(r["CellPhone"]),
                    "email": _s(r["Email"]),
                    "first_name": _s(r["FirstName"]),
                    "last_name": _s(r["LastName"]),
                    "role_id": r["RoleId"] if r["RoleId"] in roles else None,
                    "is_active": bool(r["IsActive"]),
                    "is_deleted": bool(r["IsDeleted"]),
                    "send_invoice_sms": bool(r["SendInvoiceSms"]),
                }
                if r["Created"]:
                    fields["created"] = r["Created"]
                if not (existing and existing.password):
                    fields.update(
                        legacy_password=_s(r["Password"]),
                        legacy_public_key=_s(r["PublicKey"]),
                        legacy_secret_key=_s(r["SecretKey"]),
                    )
                AdminUser.objects.update_or_create(id=r["Id"], defaults=fields)
            # Rows came with their own ids, so PostgreSQL's counter must move past them or User/Add collides.
            with connection.cursor() as cursor:
                for statement in connection.ops.sequence_reset_sql(no_style(), [AdminUser]):
                    cursor.execute(statement)
        active = AdminUser.objects.filter(is_active=True, is_deleted=False)
        self.stdout.write(self.style.SUCCESS(
            f"{AdminRole.objects.count()} نقش، {AdminUser.objects.count()} کاربر ({active.count()} فعال: "
            + "، ".join(f"{u.first_name} {u.last_name}" for u in active) + ")"
        ))
