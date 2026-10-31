from django.contrib import admin

from .models import PayRecord


@admin.register(PayRecord)
class PayRecordAdmin(admin.ModelAdmin):
    list_display = ("id", "gateway", "source", "transaction_id", "gateway_transaction_id", "amount", "state", "created")
    list_filter = ("state", "gateway", "source")
    search_fields = ("token", "transaction_id", "gateway_transaction_id", "authority", "payment_token", "cell_phone")
    readonly_fields = [f.name for f in PayRecord._meta.fields]
