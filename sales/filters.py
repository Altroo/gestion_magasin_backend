import django_filters

from gestion_magasin_backend.filter_utils import (
    BoolCSVInFilter,
    CSVInFilter,
    IntCSVInFilter,
    NotEqualFilter,
    QueryParamAliasMixin,
    SearchFilter,
    numeric_lookup_filter,
    text_lookup_filter,
)
from sales.models import Customer, PaymentMode, Promotion, Sale


class CustomerFilter(QueryParamAliasMixin, django_filters.FilterSet):
    filter_aliases = {"store": ("store", "store_id")}

    search = SearchFilter(fields=("full_name", "phone", "email", "store__name"))
    store = django_filters.CharFilter(field_name="store_id")
    store_ids = IntCSVInFilter(field_name="store_id")
    is_active = BoolCSVInFilter(field_name="is_active")
    full_name = text_lookup_filter("full_name", "exact")
    full_name__icontains = text_lookup_filter("full_name", "icontains")
    full_name__istartswith = text_lookup_filter("full_name", "istartswith")
    full_name__iendswith = text_lookup_filter("full_name", "iendswith")
    phone = text_lookup_filter("phone", "exact")
    phone__icontains = text_lookup_filter("phone", "icontains")
    email = text_lookup_filter("email", "exact")
    email__icontains = text_lookup_filter("email", "icontains")
    credit_limit = numeric_lookup_filter("credit_limit", "exact")
    credit_limit__gt = numeric_lookup_filter("credit_limit", "gt")
    credit_limit__gte = numeric_lookup_filter("credit_limit", "gte")
    credit_limit__lt = numeric_lookup_filter("credit_limit", "lt")
    credit_limit__lte = numeric_lookup_filter("credit_limit", "lte")
    credit_limit__ne = NotEqualFilter(field_name="credit_limit")

    class Meta:
        model = Customer
        fields = []


class PaymentModeFilter(django_filters.FilterSet):
    search = SearchFilter(fields=("code", "name"))
    is_active = BoolCSVInFilter(field_name="is_active")
    is_credit = BoolCSVInFilter(field_name="is_credit")
    code = text_lookup_filter("code", "exact")
    code__icontains = text_lookup_filter("code", "icontains")
    code__istartswith = text_lookup_filter("code", "istartswith")
    code__iendswith = text_lookup_filter("code", "iendswith")
    name = text_lookup_filter("name", "exact")
    name__icontains = text_lookup_filter("name", "icontains")
    name__istartswith = text_lookup_filter("name", "istartswith")
    name__iendswith = text_lookup_filter("name", "iendswith")

    class Meta:
        model = PaymentMode
        fields = []


class PromotionFilter(QueryParamAliasMixin, django_filters.FilterSet):
    filter_aliases = {"store": ("store", "store_id")}

    search = SearchFilter(
        fields=("name", "note", "lines__product__name", "lines__product__reference"),
        use_distinct=True,
    )
    store = django_filters.CharFilter(field_name="store_id")
    store_ids = IntCSVInFilter(field_name="store_id")
    status = CSVInFilter(field_name="status")
    start_date_after = django_filters.CharFilter(field_name="start_date", lookup_expr="gte")
    start_date_before = django_filters.CharFilter(field_name="start_date", lookup_expr="lte")
    end_date_after = django_filters.CharFilter(field_name="end_date", lookup_expr="gte")
    end_date_before = django_filters.CharFilter(field_name="end_date", lookup_expr="lte")
    name = text_lookup_filter("name", "exact")
    name__icontains = text_lookup_filter("name", "icontains")
    note = text_lookup_filter("note", "exact")
    note__icontains = text_lookup_filter("note", "icontains")
    store_name = text_lookup_filter("store__name", "exact")
    store_name__icontains = text_lookup_filter("store__name", "icontains")
    selling_price = numeric_lookup_filter("selling_price", "exact")
    selling_price__gt = numeric_lookup_filter("selling_price", "gt")
    selling_price__gte = numeric_lookup_filter("selling_price", "gte")
    selling_price__lt = numeric_lookup_filter("selling_price", "lt")
    selling_price__lte = numeric_lookup_filter("selling_price", "lte")
    selling_price__ne = NotEqualFilter(field_name="selling_price")

    class Meta:
        model = Promotion
        fields = []


class SaleFilter(QueryParamAliasMixin, django_filters.FilterSet):
    filter_aliases = {
        "store": ("store", "store_id"),
        "payment_mode": ("payment_mode", "payment_mode_ids"),
    }

    search = SearchFilter(
        fields=(
            "store__name",
            "seller__email",
            "customer__full_name",
            "lines__product__name",
            "lines__product__reference",
            "lines__product__barcode",
        ),
        use_distinct=True,
    )
    store = django_filters.CharFilter(field_name="store_id")
    store_ids = IntCSVInFilter(field_name="store_id")
    status = CSVInFilter(field_name="status")
    payment_status = CSVInFilter(field_name="payment_status")
    payment_mode = IntCSVInFilter(field_name="payment_mode_id")
    date_created_after = django_filters.CharFilter(
        field_name="date_created__date", lookup_expr="gte"
    )
    date_created_before = django_filters.CharFilter(
        field_name="date_created__date", lookup_expr="lte"
    )
    store_name = text_lookup_filter("store__name", "exact")
    store_name__icontains = text_lookup_filter("store__name", "icontains")
    store_name__istartswith = text_lookup_filter("store__name", "istartswith")
    store_name__iendswith = text_lookup_filter("store__name", "iendswith")
    seller_email = text_lookup_filter("seller__email", "exact")
    seller_email__icontains = text_lookup_filter("seller__email", "icontains")
    seller_email__istartswith = text_lookup_filter("seller__email", "istartswith")
    seller_email__iendswith = text_lookup_filter("seller__email", "iendswith")
    customer_name = text_lookup_filter("customer__full_name", "exact")
    customer_name__icontains = text_lookup_filter("customer__full_name", "icontains")
    customer_name__istartswith = text_lookup_filter(
        "customer__full_name", "istartswith"
    )
    customer_name__iendswith = text_lookup_filter("customer__full_name", "iendswith")
    payment_mode_name = text_lookup_filter("payment_mode__name", "exact")
    payment_mode_name__icontains = text_lookup_filter("payment_mode__name", "icontains")
    payment_mode_name__istartswith = text_lookup_filter(
        "payment_mode__name", "istartswith"
    )
    payment_mode_name__iendswith = text_lookup_filter("payment_mode__name", "iendswith")
    subtotal = numeric_lookup_filter("subtotal", "exact")
    subtotal__gt = numeric_lookup_filter("subtotal", "gt")
    subtotal__gte = numeric_lookup_filter("subtotal", "gte")
    subtotal__lt = numeric_lookup_filter("subtotal", "lt")
    subtotal__lte = numeric_lookup_filter("subtotal", "lte")
    subtotal__ne = NotEqualFilter(field_name="subtotal")
    discount_amount = numeric_lookup_filter("discount_amount", "exact")
    discount_amount__gt = numeric_lookup_filter("discount_amount", "gt")
    discount_amount__gte = numeric_lookup_filter("discount_amount", "gte")
    discount_amount__lt = numeric_lookup_filter("discount_amount", "lt")
    discount_amount__lte = numeric_lookup_filter("discount_amount", "lte")
    discount_amount__ne = NotEqualFilter(field_name="discount_amount")
    total = numeric_lookup_filter("total", "exact")
    total__gt = numeric_lookup_filter("total", "gt")
    total__gte = numeric_lookup_filter("total", "gte")
    total__lt = numeric_lookup_filter("total", "lt")
    total__lte = numeric_lookup_filter("total", "lte")
    total__ne = NotEqualFilter(field_name="total")
    paid_amount = numeric_lookup_filter("paid_amount", "exact")
    paid_amount__gt = numeric_lookup_filter("paid_amount", "gt")
    paid_amount__gte = numeric_lookup_filter("paid_amount", "gte")
    paid_amount__lt = numeric_lookup_filter("paid_amount", "lt")
    paid_amount__lte = numeric_lookup_filter("paid_amount", "lte")
    paid_amount__ne = NotEqualFilter(field_name="paid_amount")
    change_amount = numeric_lookup_filter("change_amount", "exact")
    change_amount__gt = numeric_lookup_filter("change_amount", "gt")
    change_amount__gte = numeric_lookup_filter("change_amount", "gte")
    change_amount__lt = numeric_lookup_filter("change_amount", "lt")
    change_amount__lte = numeric_lookup_filter("change_amount", "lte")
    change_amount__ne = NotEqualFilter(field_name="change_amount")

    class Meta:
        model = Sale
        fields = []
