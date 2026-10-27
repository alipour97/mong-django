from django.contrib import admin

from .models import AdminRole, AdminUser


@admin.register(AdminRole)
class AdminRoleAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "role_type", "is_deleted")


@admin.register(AdminUser)
class AdminUserAdmin(admin.ModelAdmin):
    list_display = ("id", "first_name", "last_name", "cellphone", "role", "is_active", "is_deleted", "last_login")
    list_filter = ("is_active", "is_deleted", "role")
    search_fields = ("first_name", "last_name", "cellphone", "username")
    readonly_fields = ("created", "last_login")
