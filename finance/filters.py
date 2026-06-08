import django_filters

from finance.models import Expense, ExpenseCategory
from gestion_magasin_backend.filter_utils import (
    BoolCSVInFilter,
    CSVInFilter,
    IntCSVInFilter,
    QueryParamAliasMixin,
    SearchFilter,
    numeric_lookup_filter,
    text_lookup_filter,
)


class ExpenseCategoryFilter(django_filters.FilterSet):
    search = SearchFilter(fields=("code", "name"))
    is_active = BoolCSVInFilter(field_name="is_active")
    code = text_lookup_filter("code", "exact")
    code__icontains = text_lookup_filter("code", "icontains")
    code__istartswith = text_lookup_filter("code", "istartswith")
    code__iendswith = text_lookup_filter("code", "iendswith")
    name = text_lookup_filter("name", "exact")
    name__icontains = text_lookup_filter("name", "icontains")
    name__istartswith = text_lookup_filter("name", "istartswith")
    name__iendswith = text_lookup_filter("name", "iendswith")

    class Meta:
        model = ExpenseCategory
        fields = []


class ExpenseFilter(QueryParamAliasMixin, django_filters.FilterSet):
    filter_aliases = {"store": ("store", "store_id")}

    search = SearchFilter(fields=("label", "category__name", "note"))
    store = django_filters.CharFilter(field_name="store_id")
    store_ids = IntCSVInFilter(field_name="store_id")
    category = django_filters.CharFilter(field_name="category_id")
    category_ids = IntCSVInFilter(field_name="category_id")
    payment_status = CSVInFilter(field_name="payment_status")
    payment_mode = CSVInFilter(field_name="payment_mode")
    expense_date_after = django_filters.CharFilter(
        field_name="expense_date", lookup_expr="gte"
    )
    expense_date_before = django_filters.CharFilter(
        field_name="expense_date", lookup_expr="lte"
    )
    label = text_lookup_filter("label", "exact")
    label__icontains = text_lookup_filter("label", "icontains")
    label__istartswith = text_lookup_filter("label", "istartswith")
    label__iendswith = text_lookup_filter("label", "iendswith")
    category_name = text_lookup_filter("category__name", "exact")
    category_name__icontains = text_lookup_filter("category__name", "icontains")
    note = text_lookup_filter("note", "exact")
    note__icontains = text_lookup_filter("note", "icontains")
    amount = numeric_lookup_filter("amount", "exact")
    amount__gt = numeric_lookup_filter("amount", "gt")
    amount__gte = numeric_lookup_filter("amount", "gte")
    amount__lt = numeric_lookup_filter("amount", "lt")
    amount__lte = numeric_lookup_filter("amount", "lte")

    class Meta:
        model = Expense
        fields = []
