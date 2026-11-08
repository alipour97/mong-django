from __future__ import annotations

from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.permissions import BasePermission

from . import tokens
from .models import AdminUser


class AdminTokenAuthentication(BaseAuthentication):
    """Authorization: Bearer <admin token> -> request.user is the AdminUser."""

    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if len(parts) != 2 or parts[0].lower() != b"bearer":
            return None
        uid = tokens.user_id(parts[1].decode(errors="ignore"))
        if uid is None:
            return None
        user = AdminUser.objects.select_related("role").filter(pk=uid, is_active=True, is_deleted=False).first()
        return (user, None) if user else None

    def authenticate_header(self, request):
        return "Bearer"


class IsAdmin(BasePermission):
    """Any panel account; a blog writer only on views marked writer_ok (the blog and their own account)."""

    message = "شما به این بخش دسترسی ندارید."

    def has_permission(self, request, view):
        user = request.user
        if not isinstance(user, AdminUser):
            return False
        return not user.is_writer or getattr(view, "writer_ok", False)
