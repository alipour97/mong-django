"""
Auth/* — admin sign-in, as the old AdminApi's AuthController.

    POST Auth/login        {"username", "password", "isOtp"} -> token payload
    GET  Auth/otp?cellPhone=                                  -> sends a 4-digit code by SMS
    POST Auth/refresh      "<refresh token>" (+ Bearer token) -> new token payload
    POST Auth/GetProfile?Username=                            -> {"result": profile}
    POST Auth/ChangePassword {"currentPassword", "newPassword"} -> {"result": true}

ChangePassword is the signed-in admin's own password. The current one is asked
for unless the admin has none yet (signs in by SMS code). Afterwards every
refresh token is void, so other devices are signed out when their access token
expires; the panel signs the admin out and asks for the new password.

username is the admin's mobile number (or username). OTP codes last 5 minutes,
allow 5 tries, and a new one can be requested once a minute.
"""
from __future__ import annotations

import secrets
from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.db.models import Q
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from apps import smsir

from .. import tokens
from ..authentication import AdminTokenAuthentication, IsAdmin
from ..envelope import fail, ok, unauthorized
from ..models import AdminOtp, AdminUser
from ..passwords import problems

WRONG_CREDENTIALS = "نام کاربری یا رمز عبور اشتباه است."
BLOCKED = "دسترسی شما مسدود شده است"
OTP_MINUTES = 5
OTP_RESEND_SECONDS = 60
OTP_MAX_ATTEMPTS = 5


def _find(username: str) -> AdminUser | None:
    username = (username or "").strip()
    if not username:
        return None
    mobile = smsir.normalize_mobile(username)
    return (
        AdminUser.objects.select_related("role")
        .filter(Q(cellphone=mobile) | Q(username=username), is_deleted=False)
        .first()
    )


def _token_payload(user: AdminUser) -> dict:
    payload = tokens.issue(user)
    payload["refreshToken"] = user.new_refresh_token()
    user.last_login = timezone.now()
    user.save(update_fields=["refresh_token_hash", "last_login"])
    return payload


def _check_otp(cellphone: str, code: str) -> bool:
    otp = AdminOtp.objects.filter(cellphone=cellphone, used=False, expires__gt=timezone.now()).first()
    if not otp or otp.attempts >= OTP_MAX_ATTEMPTS:
        return False
    if not check_password((code or "").strip(), otp.code_hash):
        otp.attempts += 1
        otp.save(update_fields=["attempts"])
        return False
    otp.used = True
    otp.save(update_fields=["used"])
    return True


class PublicView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []


class AdminView(APIView):
    authentication_classes = [AdminTokenAuthentication]
    permission_classes = [IsAdmin]


class LoginView(PublicView):
    def post(self, request):
        user = _find(request.data.get("username"))
        if user is None:
            return unauthorized(WRONG_CREDENTIALS)
        if not user.is_active:
            return fail(BLOCKED, 403)
        password = request.data.get("password") or ""
        valid = _check_otp(user.cellphone, password) if request.data.get("isOtp") else user.check_password(password)
        if not valid:
            return unauthorized(WRONG_CREDENTIALS)
        return ok(_token_payload(user))


class OtpView(PublicView):
    def get(self, request):
        user = _find(request.query_params.get("cellPhone"))
        if user is None:
            return fail("شما دسترسی ادمین ندارید.", 400)
        if not user.is_active:
            return fail(BLOCKED, 403)
        now = timezone.now()
        last = AdminOtp.objects.filter(cellphone=user.cellphone).first()
        if last and (now - last.created).total_seconds() < OTP_RESEND_SECONDS:
            wait = OTP_RESEND_SECONDS - int((now - last.created).total_seconds())
            return fail(f"برای ارسال دوباره‌ی کد {wait} ثانیه صبر کنید.", 429)

        code = f"{secrets.randbelow(10_000):04d}"
        AdminOtp.objects.filter(cellphone=user.cellphone, used=False).update(used=True)
        AdminOtp.objects.create(
            cellphone=user.cellphone, code_hash=make_password(code), expires=now + timedelta(minutes=OTP_MINUTES),
        )
        AdminOtp.objects.filter(created__lt=now - timedelta(days=1)).delete()
        if not smsir.send_otp(user.cellphone, code):
            return fail("سامانه پیامکی پاسخ نمی دهد", 502)
        return ok({"result": True})


class RefreshView(PublicView):
    authentication_classes = [AdminTokenAuthentication]

    def post(self, request):
        user = request.user if isinstance(request.user, AdminUser) else None
        # The panel posts the bare token with a JSON content type, quoted or not.
        refresh = request._request.body.decode(errors="ignore").strip().strip('"')
        if user is None or not user.check_refresh_token(refresh):
            return unauthorized("تایم رفرش منقضی شده است.")
        payload = tokens.issue(user)
        payload["refreshToken"] = refresh
        return ok(payload)


class ProfileView(AdminView):
    def post(self, request):
        user = _find(request.query_params.get("Username")) or request.user
        if user.pk != request.user.pk and not (request.user.role and request.user.role.role_type == 1):
            user = request.user
        return ok({"result": profile(user)})


class ChangePasswordView(AdminView):
    def post(self, request):
        user = request.user
        current = request.data.get("currentPassword") or ""
        new = request.data.get("newPassword") or ""
        if user.has_password and not user.check_password(current):
            return fail("رمز عبور فعلی اشتباه است.", 400)
        if bad := problems(new, user):
            return fail(bad[0], 400)
        user.set_password(new)
        user.refresh_token_hash = ""
        user.save(update_fields=["password", "legacy_password", "legacy_public_key", "legacy_secret_key",
                                 "refresh_token_hash"])
        return ok({"result": True})


def profile(user: AdminUser) -> dict:
    return {
        "username": user.username,
        "email": user.email,
        "cellPhone": user.cellphone,
        "firstName": user.first_name,
        "lastName": user.last_name,
        "isActive": user.is_active,
        "hasPassword": user.has_password,
        "roleId": user.role_id,
        "id": user.id,
        "created": user.created.isoformat() if user.created else None,
        "roleTitle": user.role.title if user.role else None,
        "roleType": user.role.role_type if user.role else None,
    }
