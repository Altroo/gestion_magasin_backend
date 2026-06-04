from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from sales.models import Customer, CustomerCreditLedger, PaymentMode, Sale, SaleLine


class SaleLineInline(admin.TabularInline):
    model = SaleLine
    extra = 0
    readonly_fields = ("total", "unit_cost")


@admin.register(Sale)
class SaleAdmin(SimpleHistoryAdmin):
    list_display = ("id", "store", "seller", "status", "payment_status", "total", "date_created")
    list_filter = ("store", "status", "payment_status", "date_created")
    search_fields = ("seller__email", "customer__full_name", "idempotency_key")
    inlines = [SaleLineInline]
    readonly_fields = ("date_created", "date_updated", "subtotal", "total", "change_amount")


@admin.register(Customer)
class CustomerAdmin(SimpleHistoryAdmin):
    list_display = ("full_name", "store", "phone", "credit_limit", "is_active")
    list_filter = ("store", "is_active")
    search_fields = ("full_name", "phone", "email")


@admin.register(PaymentMode)
class PaymentModeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_credit", "is_active")
    list_filter = ("is_credit", "is_active")
    search_fields = ("code", "name")


@admin.register(CustomerCreditLedger)
class CustomerCreditLedgerAdmin(admin.ModelAdmin):
    list_display = ("customer", "sale", "amount", "date_created")
    list_filter = ("date_created",)
    search_fields = ("customer__full_name", "note")
