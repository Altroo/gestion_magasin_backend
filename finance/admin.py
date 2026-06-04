from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from finance.models import Expense, ExpenseCategory


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

