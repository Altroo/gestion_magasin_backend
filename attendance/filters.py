import django_filters

from attendance.models import AttendanceRecord, Employee
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


class EmployeeFilter(QueryParamAliasMixin, django_filters.FilterSet):
    filter_aliases = {"store": ("store", "store_id")}

    search = SearchFilter(fields=("full_name", "position", "store__name"))
    store = django_filters.CharFilter(field_name="store_id")
    store_ids = IntCSVInFilter(field_name="store_id")
    is_active = BoolCSVInFilter(field_name="is_active")
    full_name = text_lookup_filter("full_name", "exact")
    full_name__icontains = text_lookup_filter("full_name", "icontains")
    full_name__istartswith = text_lookup_filter("full_name", "istartswith")
    full_name__iendswith = text_lookup_filter("full_name", "iendswith")
    position = text_lookup_filter("position", "exact")
    position__icontains = text_lookup_filter("position", "icontains")
    store_name = text_lookup_filter("store__name", "exact")
    store_name__icontains = text_lookup_filter("store__name", "icontains")

    class Meta:
        model = Employee
        fields = []


class AttendanceRecordFilter(QueryParamAliasMixin, django_filters.FilterSet):
    filter_aliases = {"store": ("store", "store_id")}

    search = SearchFilter(
        fields=("employee__full_name", "responsible", "observations", "store__name")
    )
    store = django_filters.CharFilter(field_name="store_id")
    store_ids = IntCSVInFilter(field_name="store_id")
    employee = django_filters.CharFilter(field_name="employee_id")
    employee_ids = IntCSVInFilter(field_name="employee_id")
    date_from = django_filters.CharFilter(field_name="date", lookup_expr="gte")
    date_to = django_filters.CharFilter(field_name="date", lookup_expr="lte")
    date_after = django_filters.CharFilter(field_name="date", lookup_expr="gte")
    date_before = django_filters.CharFilter(field_name="date", lookup_expr="lte")
    status = CSVInFilter(field_name="status")
    shift = CSVInFilter(field_name="shift")
    store_name = text_lookup_filter("store__name", "exact")
    store_name__icontains = text_lookup_filter("store__name", "icontains")
    store_name__istartswith = text_lookup_filter("store__name", "istartswith")
    store_name__iendswith = text_lookup_filter("store__name", "iendswith")
    employee_name = text_lookup_filter("employee__full_name", "exact")
    employee_name__icontains = text_lookup_filter("employee__full_name", "icontains")
    employee_name__istartswith = text_lookup_filter(
        "employee__full_name", "istartswith"
    )
    employee_name__iendswith = text_lookup_filter("employee__full_name", "iendswith")
    responsible = text_lookup_filter("responsible", "exact")
    responsible__icontains = text_lookup_filter("responsible", "icontains")
    responsible__istartswith = text_lookup_filter("responsible", "istartswith")
    responsible__iendswith = text_lookup_filter("responsible", "iendswith")
    observations = text_lookup_filter("observations", "exact")
    observations__icontains = text_lookup_filter("observations", "icontains")
    observations__istartswith = text_lookup_filter("observations", "istartswith")
    observations__iendswith = text_lookup_filter("observations", "iendswith")
    created_by_email = text_lookup_filter("created_by__email", "exact")
    created_by_email__icontains = text_lookup_filter("created_by__email", "icontains")
    created_by_email__istartswith = text_lookup_filter(
        "created_by__email", "istartswith"
    )
    created_by_email__iendswith = text_lookup_filter("created_by__email", "iendswith")
    hours_worked = numeric_lookup_filter("hours_worked", "exact")
    hours_worked__gt = numeric_lookup_filter("hours_worked", "gt")
    hours_worked__gte = numeric_lookup_filter("hours_worked", "gte")
    hours_worked__lt = numeric_lookup_filter("hours_worked", "lt")
    hours_worked__lte = numeric_lookup_filter("hours_worked", "lte")
    hours_worked__ne = NotEqualFilter(field_name="hours_worked")
    delay_minutes = numeric_lookup_filter("delay_minutes", "exact")
    delay_minutes__gt = numeric_lookup_filter("delay_minutes", "gt")
    delay_minutes__gte = numeric_lookup_filter("delay_minutes", "gte")
    delay_minutes__lt = numeric_lookup_filter("delay_minutes", "lt")
    delay_minutes__lte = numeric_lookup_filter("delay_minutes", "lte")
    delay_minutes__ne = NotEqualFilter(field_name="delay_minutes")

    class Meta:
        model = AttendanceRecord
        fields = []
