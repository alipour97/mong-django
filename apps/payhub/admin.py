from django.contrib import admin

from .models import PayRecord, SnappLog


@admin.register(PayRecord)
class PayRecordAdmin(admin.ModelAdmin):
    list_display = ("id", "gateway", "source", "transaction_id", "gateway_transaction_id", "amount", "state", "created")
    list_filter = ("state", "gateway", "source")
    search_fields = ("token", "transaction_id", "gateway_transaction_id", "authority", "payment_token", "cell_phone")
    readonly_fields = [f.name for f in PayRecord._meta.fields]


@admin.register(SnappLog)
class SnappLogAdmin(admin.ModelAdmin):
    list_display = ("id", "created", "method", "path", "http_status", "successful", "error", "duration_ms", "transaction_id")
    list_filter = ("successful", "path", "http_status")
    search_fields = ("payment_token", "transaction_id")
    date_hierarchy = "created"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
