from django.urls import path

from finance.views import (
    BulkDeleteExpensesView,
    ExpenseCategoryDetailEditDeleteView,
    ExpenseCategoryListCreateView,
    ExpenseDetailEditDeleteView,
    ExpenseListCreateView,
)

app_name = "finance"

urlpatterns = [
    path("categories/", ExpenseCategoryListCreateView.as_view(), name="expense-categories-list"),
    path("categories/<int:pk>/", ExpenseCategoryDetailEditDeleteView.as_view(), name="expense-categories-detail"),
    path("bulk-delete/", BulkDeleteExpensesView.as_view(), name="expenses-bulk-delete"),
    path("<int:pk>/", ExpenseDetailEditDeleteView.as_view(), name="expenses-detail"),
    path("", ExpenseListCreateView.as_view(), name="expenses-list"),
]
