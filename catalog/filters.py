import django_filters

from catalog.models import Category, Product, ProductUnit
from gestion_magasin_backend.filter_utils import (
    BoolCSVInFilter,
    IntCSVInFilter,
    NotEqualFilter,
    SearchFilter,
    numeric_lookup_filter,
    text_lookup_filter,
)


class CategoryFilter(django_filters.FilterSet):
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
        model = Category
        fields = []


class ProductUnitFilter(django_filters.FilterSet):
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
        model = ProductUnit
        fields = []


class ProductFilter(django_filters.FilterSet):
    search = SearchFilter(fields=("reference", "barcode", "name"))
    category = django_filters.CharFilter(field_name="category_id")
    category_ids = IntCSVInFilter(field_name="category_id")
    unit = django_filters.CharFilter(field_name="unit_id")
    unit_ids = IntCSVInFilter(field_name="unit_id")
    is_active = BoolCSVInFilter(field_name="is_active")
    expiration_date_after = django_filters.CharFilter(
        field_name="expiration_date", lookup_expr="gte"
    )
    expiration_date_before = django_filters.CharFilter(
        field_name="expiration_date", lookup_expr="lte"
    )

    reference = text_lookup_filter("reference", "exact")
    reference__icontains = text_lookup_filter("reference", "icontains")
    reference__istartswith = text_lookup_filter("reference", "istartswith")
    reference__iendswith = text_lookup_filter("reference", "iendswith")
    barcode = text_lookup_filter("barcode", "exact")
    barcode__icontains = text_lookup_filter("barcode", "icontains")
    barcode__istartswith = text_lookup_filter("barcode", "istartswith")
    barcode__iendswith = text_lookup_filter("barcode", "iendswith")
    name = text_lookup_filter("name", "exact")
    name__icontains = text_lookup_filter("name", "icontains")
    name__istartswith = text_lookup_filter("name", "istartswith")
    name__iendswith = text_lookup_filter("name", "iendswith")
    category_name = text_lookup_filter("category__name", "exact")
    category_name__icontains = text_lookup_filter("category__name", "icontains")
    category_name__istartswith = text_lookup_filter("category__name", "istartswith")
    category_name__iendswith = text_lookup_filter("category__name", "iendswith")
    unit_name = text_lookup_filter("unit__name", "exact")
    unit_name__icontains = text_lookup_filter("unit__name", "icontains")
    unit_name__istartswith = text_lookup_filter("unit__name", "istartswith")
    unit_name__iendswith = text_lookup_filter("unit__name", "iendswith")

    purchase_price = numeric_lookup_filter("purchase_price", "exact")
    purchase_price__gt = numeric_lookup_filter("purchase_price", "gt")
    purchase_price__gte = numeric_lookup_filter("purchase_price", "gte")
    purchase_price__lt = numeric_lookup_filter("purchase_price", "lt")
    purchase_price__lte = numeric_lookup_filter("purchase_price", "lte")
    purchase_price__ne = NotEqualFilter(field_name="purchase_price")
    wholesale_price = numeric_lookup_filter("wholesale_price", "exact")
    wholesale_price__gt = numeric_lookup_filter("wholesale_price", "gt")
    wholesale_price__gte = numeric_lookup_filter("wholesale_price", "gte")
    wholesale_price__lt = numeric_lookup_filter("wholesale_price", "lt")
    wholesale_price__lte = numeric_lookup_filter("wholesale_price", "lte")
    wholesale_price__ne = NotEqualFilter(field_name="wholesale_price")
    detail_price = numeric_lookup_filter("detail_price", "exact")
    detail_price__gt = numeric_lookup_filter("detail_price", "gt")
    detail_price__gte = numeric_lookup_filter("detail_price", "gte")
    detail_price__lt = numeric_lookup_filter("detail_price", "lt")
    detail_price__lte = numeric_lookup_filter("detail_price", "lte")
    detail_price__ne = NotEqualFilter(field_name="detail_price")
    counter_price = numeric_lookup_filter("counter_price", "exact")
    counter_price__gt = numeric_lookup_filter("counter_price", "gt")
    counter_price__gte = numeric_lookup_filter("counter_price", "gte")
    counter_price__lt = numeric_lookup_filter("counter_price", "lt")
    counter_price__lte = numeric_lookup_filter("counter_price", "lte")
    counter_price__ne = NotEqualFilter(field_name="counter_price")
    default_stock_alert = numeric_lookup_filter("default_stock_alert", "exact")
    default_stock_alert__gt = numeric_lookup_filter("default_stock_alert", "gt")
    default_stock_alert__gte = numeric_lookup_filter("default_stock_alert", "gte")
    default_stock_alert__lt = numeric_lookup_filter("default_stock_alert", "lt")
    default_stock_alert__lte = numeric_lookup_filter("default_stock_alert", "lte")
    default_stock_alert__ne = NotEqualFilter(field_name="default_stock_alert")

    class Meta:
        model = Product
        fields = []
