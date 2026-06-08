from datetime import timedelta

import django_filters
from django.utils import timezone

from store.models import Store
from store.permissions import get_store_from_request, user_store_ids


class ReportingScopeFilter(django_filters.FilterSet):
    store = django_filters.CharFilter()
    store_id = django_filters.CharFilter()
    date_from = django_filters.CharFilter()
    date_to = django_filters.CharFilter()

    class Meta:
        model = Store
        fields = []

    def __init__(self, data=None, *args, request=None, default_days=30, **kwargs):
        self.default_days = default_days
        super().__init__(
            data=data,
            *args,
            queryset=Store.objects.none(),
            request=request,
            **kwargs,
        )

    def get_date_range(self):
        today = timezone.localdate()
        start = today - timedelta(days=self.default_days - 1)
        end = today

        date_from = self.data.get("date_from")
        date_to = self.data.get("date_to")
        if date_from:
            start = timezone.datetime.fromisoformat(date_from).date()
        if date_to:
            end = timezone.datetime.fromisoformat(date_to).date()
        return start, end

    def get_store_ids(self):
        raw_store = self.data.get("store") or self.data.get("store_id")
        if raw_store and str(raw_store).lower() != "all":
            return [get_store_from_request(self.request).pk]
        if self.request.user.is_staff:
            return None
        return user_store_ids(self.request.user)

    def get_dashboard_store_scope(self):
        raw_store = self.data.get("store") or self.data.get("store_id")
        if raw_store and str(raw_store).lower() != "all":
            store = get_store_from_request(self.request)
            return [store.pk], {"id": store.pk, "name": store.name}
        if self.request.user.is_staff:
            return None, {"id": None, "name": "Tous les magasins"}
        return user_store_ids(self.request.user), {
            "id": None,
            "name": "Tous les magasins",
        }

    @staticmethod
    def apply_store_filter(queryset, store_ids, field_name="store_id"):
        if store_ids is None:
            return queryset
        return queryset.filter(**{f"{field_name}__in": store_ids})
