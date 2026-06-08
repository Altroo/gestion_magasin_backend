import django_filters

from gestion_magasin_backend.filter_utils import (
    BoolCSVInFilter,
    CSVInFilter,
    IntCSVInFilter,
    QueryParamAliasMixin,
    SearchFilter,
    text_lookup_filter,
)
from notification.models import Notification


class NotificationFilter(QueryParamAliasMixin, django_filters.FilterSet):
    filter_aliases = {"store": ("store", "store_id")}

    search = SearchFilter(fields=("title", "message", "store__name", "product__name"))
    is_read = BoolCSVInFilter(field_name="is_read")
    notification_type = CSVInFilter(field_name="notification_type")
    type = CSVInFilter(field_name="notification_type")
    store = django_filters.CharFilter(field_name="store_id")
    store_ids = IntCSVInFilter(field_name="store_id")
    product = django_filters.CharFilter(field_name="product_id")
    product_ids = IntCSVInFilter(field_name="product_id")
    object_id = django_filters.CharFilter(field_name="object_id")
    date_created_after = django_filters.CharFilter(
        field_name="date_created", lookup_expr="gte"
    )
    date_created_before = django_filters.CharFilter(
        field_name="date_created", lookup_expr="lte"
    )
    title = text_lookup_filter("title", "exact")
    title__icontains = text_lookup_filter("title", "icontains")
    message = text_lookup_filter("message", "exact")
    message__icontains = text_lookup_filter("message", "icontains")

    class Meta:
        model = Notification
        fields = []
