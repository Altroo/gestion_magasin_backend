import django_filters
from django.db.models import Q

from gestion_magasin_backend.utils import (
    parse_bool_csv_query_value,
    split_csv_query_value,
)


TEXT_LOOKUPS = ("icontains", "istartswith", "iendswith")
NUMERIC_LOOKUPS = ("gt", "gte", "lt", "lte")


def parse_int_csv_query_value(value):
    ids = []
    for item in split_csv_query_value(value):
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids


def first_query_value(data, names):
    for name in names:
        value = data.get(name)
        if value not in (None, ""):
            return value
    return None


class QueryParamAliasMixin:
    filter_aliases = {}

    def __init__(self, data=None, *args, **kwargs):
        if data is not None and self.filter_aliases:
            normalized = data.copy()
            for canonical, aliases in self.filter_aliases.items():
                if normalized.get(canonical) not in (None, ""):
                    continue
                value = first_query_value(data, aliases)
                if value not in (None, ""):
                    normalized[canonical] = value
            data = normalized
        super().__init__(data, *args, **kwargs)


class SearchFilter(django_filters.CharFilter):
    def __init__(self, *args, fields=None, use_distinct=False, **kwargs):
        self.search_fields = tuple(fields or ())
        self.use_distinct = use_distinct
        super().__init__(*args, **kwargs)

    def filter(self, queryset, value):
        if value in (None, "") or not self.search_fields:
            return queryset

        query = Q()
        for field in self.search_fields:
            query |= Q(**{f"{field}__icontains": value})

        queryset = queryset.filter(query)
        if self.use_distinct:
            queryset = queryset.distinct()
        return queryset


class CSVInFilter(django_filters.CharFilter):
    parser = staticmethod(split_csv_query_value)

    def filter(self, queryset, value):
        values = self.parser(value)
        if not values:
            return queryset
        return queryset.filter(**{f"{self.field_name}__in": values})


class IntCSVInFilter(CSVInFilter):
    parser = staticmethod(parse_int_csv_query_value)


class BoolCSVInFilter(CSVInFilter):
    parser = staticmethod(parse_bool_csv_query_value)


class NotEqualFilter(django_filters.CharFilter):
    def filter(self, queryset, value):
        if value in (None, ""):
            return queryset
        return queryset.exclude(**{self.field_name: value})


class IExactCSVOrFilter(django_filters.CharFilter):
    def filter(self, queryset, value):
        values = split_csv_query_value(value)
        if not values:
            return queryset

        query = Q()
        for item in values:
            query |= Q(**{f"{self.field_name}__iexact": item})
        return queryset.filter(query)


class ExcludeGlobalStockFilter(django_filters.CharFilter):
    def filter(self, queryset, value):
        values = set(parse_bool_csv_query_value(value))
        if values == {True}:
            return queryset.filter(store__is_global_stock=False)
        if values == {False}:
            return queryset.filter(store__is_global_stock=True)
        return queryset


def text_lookup_filter(field_name, lookup_expr):
    return django_filters.CharFilter(field_name=field_name, lookup_expr=lookup_expr)


def numeric_lookup_filter(field_name, lookup_expr):
    return django_filters.CharFilter(field_name=field_name, lookup_expr=lookup_expr)
