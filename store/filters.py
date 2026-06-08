import django_filters

from gestion_magasin_backend.filter_utils import (
    BoolCSVInFilter,
    QueryParamAliasMixin,
    SearchFilter,
    text_lookup_filter,
)
from store.models import Store, StoreMembership


class StoreFilter(django_filters.FilterSet):
    search = SearchFilter(fields=("name", "code", "address", "phone"))
    is_active = BoolCSVInFilter(field_name="is_active")
    is_global_stock = BoolCSVInFilter(field_name="is_global_stock")
    name = text_lookup_filter("name", "exact")
    name__icontains = text_lookup_filter("name", "icontains")
    name__istartswith = text_lookup_filter("name", "istartswith")
    name__iendswith = text_lookup_filter("name", "iendswith")
    code = text_lookup_filter("code", "exact")
    code__icontains = text_lookup_filter("code", "icontains")
    code__istartswith = text_lookup_filter("code", "istartswith")
    code__iendswith = text_lookup_filter("code", "iendswith")
    address = text_lookup_filter("address", "exact")
    address__icontains = text_lookup_filter("address", "icontains")
    address__istartswith = text_lookup_filter("address", "istartswith")
    address__iendswith = text_lookup_filter("address", "iendswith")
    phone = text_lookup_filter("phone", "exact")
    phone__icontains = text_lookup_filter("phone", "icontains")
    phone__istartswith = text_lookup_filter("phone", "istartswith")
    phone__iendswith = text_lookup_filter("phone", "iendswith")

    class Meta:
        model = Store
        fields = []


class StoreMembershipFilter(QueryParamAliasMixin, django_filters.FilterSet):
    filter_aliases = {"store": ("store", "store_id"), "role": ("role", "role_id")}

    search = SearchFilter(fields=("user__email", "store__name", "role__name"))
    store = django_filters.CharFilter(field_name="store_id")
    user = django_filters.CharFilter(field_name="user_id")
    role = django_filters.CharFilter(field_name="role_id")
    role_code = text_lookup_filter("role__code", "exact")
    is_active = BoolCSVInFilter(field_name="is_active")
    user_email = text_lookup_filter("user__email", "exact")
    user_email__icontains = text_lookup_filter("user__email", "icontains")
    store_name = text_lookup_filter("store__name", "exact")
    store_name__icontains = text_lookup_filter("store__name", "icontains")

    class Meta:
        model = StoreMembership
        fields = []
