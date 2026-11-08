"""
User/* — panel accounts and roles (AdminUser, AdminRole).

As before, any signed-in admin can manage accounts; nobody can deactivate or
delete their own account.

    GET  User/GetUsers | User/GetDashboardUsers | User/ValidationUserName?userName= | User/SoftDelete?userId=
    POST User/Add {username, password, email, cellPhone, firstName, lastName, roleId}
    POST User/Upadate {id, ...}     POST User/UpadateUser?userId=&firstName=&lastName=
    POST User/ChangeSmsState/<id>?sendSms=      POST User/GetAllRole      POST User/AddRole {roleTitle}
"""
from __future__ import annotations

from django.db import transaction
from django.db.models import Max, Q

from apps.smsir import normalize_mobile

from ..envelope import fail, ok
from ..models import AdminRole, AdminUser
from ..passwords import problems
from ..paging import to_bool, to_int
from .auth import AdminView, author_photo


def _author_fields(user: AdminUser, d) -> None:
    """The blog author's job title, bio and photo (a URL from Cdn/upload), when sent."""
    for field, key in (("job_title", "jobTitle"), ("bio", "bio"), ("photo", "photo")):
        if d.get(key) is not None:
            setattr(user, field, str(d[key]).strip())

NOT_FOUND = "کاربر یافت نشد."
SELF = "نمی‌توانید حساب خودتان را غیرفعال یا حذف کنید."


def _users():
    return AdminUser.objects.filter(is_deleted=False).select_related("role")


def _mobile(value) -> str | None:
    mobile = normalize_mobile("".join(ch for ch in str(value or "") if ch.isdigit() or ch == "+"))
    return mobile if len(mobile) == 11 and mobile.startswith("09") else None


def _role(role_id) -> AdminRole | None:
    return AdminRole.objects.filter(id=to_int(role_id), is_deleted=False).first() if role_id not in (None, "") else None


class ListView(AdminView):
    writer_ok = True  # the blog's author filter

    def get(self, request):
        return ok({"result": [
            {"id": u.id, "fullName": f"{u.first_name} {u.last_name}", "isActive": u.is_active} for u in _users()
        ]})


class DashboardUsersView(AdminView):
    def get(self, request):
        return ok({"result": [
            {
                "id": u.id, "firstName": u.first_name, "lastName": u.last_name, "cellPhone": u.cellphone,
                "userName": u.username, "email": u.email, "isActive": u.is_active, "sendInvoiceSms": u.send_invoice_sms,
                "roleId": u.role_id, "roleTitle": u.role.title if u.role else None,
                "roleType": u.role.role_type if u.role else None,
                "jobTitle": u.job_title, "bio": u.bio, "photo": author_photo(u),
            }
            for u in _users()
        ]})


class AddView(AdminView):
    def post(self, request):
        d = request.data
        username = (d.get("username") or d.get("userName") or "").strip()
        mobile = _mobile(d.get("cellPhone"))
        password = d.get("password") or ""
        if not username or not mobile:
            return fail("نام کاربری و موبایل معتبر الزامی است", 400)
        if bad := problems(password, AdminUser(username=username, cellphone=mobile or "")):
            return fail(bad[0], 400)
        matches = list(AdminUser.objects.filter(Q(username__iexact=username) | Q(cellphone=mobile)))
        taken = matches[0] if matches else None
        if len(matches) > 1 or (taken and not taken.is_deleted):  # two rows: one's username, the other's mobile
            return fail("کاربری با این اطلاعات قبلا ثبت نام کرده است.", 400)
        with transaction.atomic():
            if taken:  # a deleted account with the same mobile or username: reuse it
                user = taken
                user.is_deleted, user.is_active = False, True
            else:
                user = AdminUser()
            user.username, user.cellphone = username, mobile
            user.email = (d.get("email") or "").strip()
            user.first_name, user.last_name = (d.get("firstName") or "").strip(), (d.get("lastName") or "").strip()
            user.role = _role(d.get("roleId"))
            _author_fields(user, d)
            user.set_password(password)
            user.refresh_token_hash = ""
            user.save()
        return ok({"result": True})


class UpdateView(AdminView):
    def post(self, request):
        d = request.data
        user = _users().filter(id=to_int(d.get("id"))).first()
        if not user:
            return fail(NOT_FOUND, 404)
        if d.get("cellPhone") is not None:
            mobile = _mobile(d["cellPhone"])
            if not mobile:
                return fail("شماره موبایل نامعتبر است", 400)
            if AdminUser.objects.filter(cellphone=mobile).exclude(id=user.id).exists():
                return fail("این موبایل برای کاربر دیگری ثبت شده است", 400)
            user.cellphone = mobile
        if d.get("userName") is not None:
            username = d["userName"].strip()
            if not username or AdminUser.objects.filter(username__iexact=username).exclude(id=user.id).exists():
                return fail("نام کاربری تکراری یا خالی است", 400)
            user.username = username
        for field, key in (("first_name", "firstName"), ("last_name", "lastName"), ("email", "email")):
            if d.get(key) is not None:
                setattr(user, field, str(d[key]).strip())
        active = to_bool(d.get("isActive"))
        if active is not None and user.id != request.user.id:
            user.is_active = active
        if d.get("password"):
            if bad := problems(d["password"], user):
                return fail(bad[0], 400)
            user.set_password(d["password"])
            user.refresh_token_hash = ""  # signs the account out elsewhere
        if (role := _role(d.get("roleId"))) is not None:
            user.role = role
        _author_fields(user, d)
        user.save()
        return ok({"result": True})


class UpdateNameView(AdminView):
    def post(self, request):
        q = request.query_params
        n = _users().filter(id=to_int(q.get("userId"))).update(
            first_name=(q.get("firstName") or "").strip(), last_name=(q.get("lastName") or "").strip()
        )
        return ok({"result": True}) if n else fail(NOT_FOUND, 404)


class SmsStateView(AdminView):
    def post(self, request, user_id: int):
        n = _users().filter(id=user_id).update(send_invoice_sms=bool(to_bool(request.query_params.get("sendSms"))))
        return ok({"result": True}) if n else fail(NOT_FOUND, 404)


class ValidateUsernameView(AdminView):
    def get(self, request):
        username = (request.query_params.get("userName") or "").strip()
        return ok({"result": bool(username) and not _users().filter(Q(username__iexact=username) | Q(cellphone=username)).exists()})


class DeleteView(AdminView):
    def get(self, request):
        uid = to_int(request.query_params.get("userId"))
        if uid == request.user.id:
            return fail(SELF, 400)
        n = _users().filter(id=uid).update(is_deleted=True, refresh_token_hash="")
        return ok({"result": True}) if n else fail("کاربر مورد نظر یافت نشد.", 404)


class RolesView(AdminView):
    def post(self, request):
        roles = AdminRole.objects.filter(is_deleted=False).order_by("id")
        return ok({"result": [{"id": r.id, "roleTitle": r.title, "roleType": r.role_type} for r in roles]})


class AddRoleView(AdminView):
    def post(self, request):
        title = (request.data.get("roleTitle") or "").strip()
        if not title:
            return fail("عنوان نقش الزامی است", 400)
        with transaction.atomic():
            next_id = (AdminRole.objects.select_for_update().aggregate(m=Max("id"))["m"] or 0) + 1
            role = AdminRole.objects.create(id=next_id, title=title, role_type=AdminRole.Type.USER)
        return ok({"result": role.id})
