from datetime import UTC, date, datetime, time, timedelta

import pytest
from django.utils import timezone

from account.models import CustomUser
from catalog.models import Product, ProductUnit
from notification.filters import NotificationFilter
from notification.models import Notification
from stock.filters import StockMovementFilter
from stock.models import StockMovement
from store.models import Store

pytestmark = pytest.mark.django_db

CALENDAR_DAYS = [
    ["UTC", "2026-10-21", 24],
    ["Africa/Casablanca", "2026-10-21", 24],
    ["Europe/Paris", "2026-03-29", 23],
    ["Europe/Paris", "2026-10-25", 25],
    ["Africa/Casablanca", "2026-02-15", 25],
    ["Africa/Casablanca", "2026-03-22", 23],
]


@pytest.fixture(params=["notification", "stock_movement"])
def timestamp_record(request):
    if request.param == "notification":
        user = CustomUser.objects.create(email="notification-boundary@example.test")
        record = Notification.objects.create(
            user=user, title="Calendar boundary", message="Test"
        )
        return record, NotificationFilter
    store = Store.objects.create(code="CALENDAR", name="Calendar boundary")
    unit = ProductUnit.objects.create(code="calendar-unit", name="Calendar unit")
    product = Product.objects.create(name="Calendar boundary", unit=unit)
    record = StockMovement.objects.create(
        store=store,
        product=product,
        movement_type=StockMovement.Types.ADJUSTMENT,
        quantity=1,
        balance_after=1,
    )
    return record, StockMovementFilter


@pytest.mark.parametrize("zone,selected_day,hours", CALENDAR_DAYS)
@pytest.mark.parametrize("bounds", ["after", "before", "range"])
def test_timestamp_calendar_bounds(timestamp_record, zone, selected_day, hours, bounds):
    record, filterset = timestamp_record
    model = type(record)
    with timezone.override(zone):
        day = date.fromisoformat(selected_day)
        start = timezone.make_aware(datetime.combine(day, time.min))
        end = timezone.make_aware(datetime.combine(day + timedelta(days=1), time.min))
        assert end.astimezone(UTC) - start.astimezone(UTC) == timedelta(hours=hours)
        params = {}
        if bounds in ("after", "range"):
            params["date_created_after"] = selected_day
        if bounds in ("before", "range"):
            params["date_created_before"] = selected_day
        moments = [
            start.astimezone(UTC) - timedelta(microseconds=1),
            start,
            timezone.make_aware(datetime.combine(day, time(12))),
            end.astimezone(UTC) - timedelta(microseconds=1),
            end,
        ]
        included = {"after": {1, 2, 3, 4}, "before": {0, 1, 2, 3}, "range": {1, 2, 3}}[
            bounds
        ]
        for index, moment in enumerate(moments):
            model.objects.filter(pk=record.pk).update(date_created=moment)
            filters = filterset(params, queryset=model.objects.filter(pk=record.pk))
            assert filters.is_valid(), filters.errors
            assert filters.qs.exists() is (index in included), (zone, moment)


def test_empty_calendar_bounds_preserve_records(timestamp_record):
    record, filterset = timestamp_record
    filters = filterset(
        {"date_created_after": "", "date_created_before": ""},
        queryset=type(record).objects.filter(pk=record.pk),
    )
    assert filters.is_valid(), filters.errors
    assert list(filters.qs) == [record]
