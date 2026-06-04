from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from attendance.models import AttendanceRecord, Employee
from store.models import Role, Store, StoreMembership

pytestmark = pytest.mark.django_db

User = get_user_model()


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def create_store_setup():
    user = User.objects.create_user(email="attendance@example.com", password="securepass123")
    role, _ = Role.objects.get_or_create(
        code=Role.Codes.RESPONSABLE,
        defaults={"name": "Responsable", "rank": 1},
    )
    store = Store.objects.create(code="attendance-store", name="ATTENDANCE STORE", is_active=True)
    StoreMembership.objects.create(user=user, store=store, role=role)
    employee = Employee.objects.create(store=store, full_name="Employé test")
    return user, store, employee


def test_attendance_list_accepts_comma_separated_status_filters():
    user, store, employee = create_store_setup()
    present = AttendanceRecord.objects.create(
        store=store,
        employee=employee,
        date=date(2026, 6, 1),
        hours_worked=Decimal("8.00"),
        status=AttendanceRecord.Statuses.PRESENT,
    )
    off = AttendanceRecord.objects.create(
        store=store,
        employee=employee,
        date=date(2026, 6, 2),
        hours_worked=Decimal("0.00"),
        status=AttendanceRecord.Statuses.OFF,
    )
    AttendanceRecord.objects.create(
        store=store,
        employee=employee,
        date=date(2026, 6, 3),
        hours_worked=Decimal("0.00"),
        status=AttendanceRecord.Statuses.ABSENT,
    )
    client = authenticated_client(user)

    response = client.get(
        "/api/attendance/",
        {
            "store": store.pk,
            "status": "present,off",
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert {item["id"] for item in response.data["results"]} == {present.pk, off.pk}
