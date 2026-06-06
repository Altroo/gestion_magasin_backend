from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from gestion_magasin_backend.admin_history import register_history_admin
from sales.models import (
    Customer,
    CustomerCreditLedger,
    PaymentMode,
    Promotion,
    PromotionLine,
    Sale,
    SaleLine,
    SalePromotionLine,
)


class SaleLineInline(admin.TabularInline):
    model = SaleLine
    extra = 0
    readonly_fields = ("total", "unit_cost")


@admin.register(SaleLine)
class SaleLineAdmin(SimpleHistoryAdmin):
    list_display = ("sale", "product", "quantity", "unit_price", "unit_cost", "total")
    list_filter = ("sale__store", "product__category")
    search_fields = ("sale__idempotency_key", "product__name", "product__reference", "product__barcode")
    readonly_fields = ("total", "unit_cost")


class SalePromotionLineInline(admin.TabularInline):
    model = SalePromotionLine
    extra = 0
    readonly_fields = ("total",)


@admin.register(SalePromotionLine)
class SalePromotionLineAdmin(SimpleHistoryAdmin):
    list_display = ("sale", "promotion", "quantity", "unit_price", "total")
    list_filter = ("sale__store", "promotion__status")
    search_fields = ("promotion__name", "sale__idempotency_key")
    readonly_fields = ("total",)


@admin.register(Sale)
class SaleAdmin(SimpleHistoryAdmin):
    list_display = ("id", "store", "seller", "status", "payment_status", "total", "date_created")
    list_filter = ("store", "status", "payment_status", "date_created")
    search_fields = ("seller__email", "customer__full_name", "idempotency_key")
    inlines = [SaleLineInline, SalePromotionLineInline]
    readonly_fields = ("date_created", "date_updated", "subtotal", "total", "change_amount")


class PromotionLineInline(admin.TabularInline):
    model = PromotionLine
    extra = 0


@admin.register(PromotionLine)
class PromotionLineAdmin(SimpleHistoryAdmin):
    list_display = ("promotion", "product", "quantity")
    list_filter = ("promotion__store", "product__category")
    search_fields = ("promotion__name", "product__name", "product__reference", "product__barcode")


@admin.register(Promotion)
class PromotionAdmin(SimpleHistoryAdmin):
    list_display = ("name", "store", "selling_price", "status", "start_date", "end_date")
    list_filter = ("store", "status", "start_date", "end_date")
    search_fields = ("name", "note", "lines__product__name", "lines__product__reference")
    readonly_fields = ("created_by", "date_created", "date_updated")
    inlines = [PromotionLineInline]


@admin.register(Customer)
class CustomerAdmin(SimpleHistoryAdmin):
    list_display = ("full_name", "store", "phone", "credit_limit", "is_active")
    list_filter = ("store", "is_active")
    search_fields = ("full_name", "phone", "email")


@admin.register(PaymentMode)
class PaymentModeAdmin(SimpleHistoryAdmin):
    list_display = ("code", "name", "is_credit", "is_active")
    list_filter = ("is_credit", "is_active")
    search_fields = ("code", "name")


@admin.register(CustomerCreditLedger)
class CustomerCreditLedgerAdmin(SimpleHistoryAdmin):
    list_display = ("customer", "sale", "amount", "date_created")
    list_filter = ("date_created",)
    search_fields = ("customer__full_name", "note")


register_history_admin(
    Customer,
    display_fields=("id", "full_name", "store", "phone", "credit_limit", "is_active"),
    list_filter=("store", "is_active"),
    search_fields=("full_name", "phone", "email", "store__name"),
)
register_history_admin(
    PaymentMode,
    display_fields=("id", "code", "name", "is_credit", "is_active"),
    list_filter=("is_credit", "is_active"),
    search_fields=("code", "name"),
)
register_history_admin(
    Promotion,
    display_fields=("id", "name", "store", "selling_price", "status", "start_date", "end_date"),
    list_filter=("store", "status", "start_date", "end_date"),
    search_fields=("name", "note", "store__name"),
)
register_history_admin(
    PromotionLine,
    display_fields=("id", "promotion", "product", "quantity"),
    list_filter=("promotion__store",),
    search_fields=("promotion__name", "product__name", "product__reference", "product__barcode"),
)
register_history_admin(
    Sale,
    display_fields=("id", "store", "seller", "status", "payment_status", "total", "date_created"),
    list_filter=("store", "status", "payment_status", "date_created"),
    search_fields=("seller__email", "customer__full_name", "idempotency_key"),
)
register_history_admin(
    SaleLine,
    display_fields=("id", "sale", "product", "quantity", "unit_price", "unit_cost", "total"),
    list_filter=("sale__store",),
    search_fields=("sale__idempotency_key", "product__name", "product__reference", "product__barcode"),
)
register_history_admin(
    SalePromotionLine,
    display_fields=("id", "sale", "promotion", "quantity", "unit_price", "total"),
    list_filter=("sale__store",),
    search_fields=("promotion__name", "sale__idempotency_key"),
)
register_history_admin(
    CustomerCreditLedger,
    display_fields=("id", "customer", "sale", "amount", "date_created"),
    list_filter=("date_created",),
    search_fields=("customer__full_name", "note"),
)
