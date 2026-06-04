from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from finance.models import Expense, ExpenseCategory
from store.models import Role, Store, StoreMembership

pytestmark = pytest.mark.django_db

User = get_user_model()


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def create_store_setup():
    user = User.objects.create_user(email="finance@example.com", password="securepass123")
    role, _ = Role.objects.get_or_create(
        code=Role.Codes.RESPONSABLE,
        defaults={"name": "Responsable", "rank": 1},
    )
    store = Store.objects.create(code="finance-store", name="FINANCE STORE", is_active=True)
    StoreMembership.objects.create(user=user, store=store, role=role)
    category = ExpenseCategory.objects.create(code="rent", name="Loyer")
    return user, store, category


def test_expense_create_assigns_current_user_and_store():
    user, store, category = create_store_setup()
    client = authenticated_client(user)

    response = client.post(
        "/api/finance/",
        {
            "store": store.pk,
            "category": category.pk,
            "label": "Loyer juin",
            "amount": "1500.00",
            "payment_status": "paid",
            "payment_mode": "transfer",
            "expense_date": "2026-06-01",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    expense = Expense.objects.get(pk=response.data["id"])
    assert expense.store == store
    assert expense.created_by == user
    assert expense.amount == Decimal("1500.00")


def test_expense_list_is_scoped_to_user_stores():
    user, store, category = create_store_setup()
    Expense.objects.create(
        store=store,
        category=category,
        label="Loyer juin",
        amount=Decimal("1500.00"),
        expense_date=date(2026, 6, 1),
    )
    other_store = Store.objects.create(code="finance-other", name="OTHER STORE", is_active=True)
    Expense.objects.create(
        store=other_store,
        category=category,
        label="Autre loyer",
        amount=Decimal("500.00"),
        expense_date=date(2026, 6, 1),
    )
    client = authenticated_client(user)

    response = client.get("/api/finance/", {"store": store.pk})

    assert response.status_code == status.HTTP_200_OK
    assert response.data["count"] == 1
    assert response.data["results"][0]["label"] == "Loyer juin"
