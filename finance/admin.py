from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from finance.models import Expense, ExpenseCategory
from gestion_magasin_backend.admin_history import register_history_admin


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(SimpleHistoryAdmin):
    list_display = ("code", "name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")


@admin.register(Expense)
class ExpenseAdmin(SimpleHistoryAdmin):
    list_display = ("expense_date", "store", "category", "label", "amount", "payment_status")
    list_filter = ("store", "category", "payment_status", "payment_mode", "expense_date")
    search_fields = ("label", "note", "category__name", "store__name")
    readonly_fields = ("date_created", "date_updated")


register_history_admin(
    ExpenseCategory,
    display_fields=("id", "code", "name", "is_active"),
    list_filter=("is_active",),
    search_fields=("code", "name"),
)
register_history_admin(
    Expense,
    display_fields=("id", "expense_date", "store", "category", "label", "amount", "payment_status"),
    list_filter=("store", "category", "payment_status", "payment_mode", "expense_date"),
    search_fields=("label", "note", "category__name", "store__name"),
)
