from datetime import date
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
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
    assert response.data["payment_mode_name"] == "Virement"


def test_expense_create_accepts_invoice_file():
    user, store, category = create_store_setup()
    client = authenticated_client(user)
    invoice = SimpleUploadedFile(
        "facture.pdf", b"%PDF-1.4 test", content_type="application/pdf"
    )

    response = client.post(
        "/api/finance/",
        {
            "store": store.pk,
            "category": category.pk,
            "label": "Facture eau",
            "amount": "250.00",
            "payment_status": "paid",
            "payment_mode": "cash",
            "expense_date": "2026-06-01",
            "invoice_file": invoice,
        },
        format="multipart",
    )

    assert response.status_code == status.HTTP_201_CREATED, response.data
    expense = Expense.objects.get(pk=response.data["id"])
    assert expense.invoice_file.name.endswith(".pdf")
    assert response.data["invoice_file_url"]


def test_expense_category_crud_is_available_to_authenticated_users():
    user, _store, _category = create_store_setup()
    client = authenticated_client(user)

    create_response = client.post(
        "/api/finance/categories/",
        {"code": "transport", "name": "Transport", "is_active": True},
        format="json",
    )

    assert create_response.status_code == status.HTTP_201_CREATED
    category_id = create_response.data["id"]

    update_response = client.patch(
        f"/api/finance/categories/{category_id}/",
        {"code": "transport-local", "name": "Transport local"},
        format="json",
    )

    assert update_response.status_code == status.HTTP_200_OK
    assert update_response.data["name"] == "Transport local"

    delete_response = client.delete(f"/api/finance/categories/{category_id}/")

    assert delete_response.status_code == status.HTTP_204_NO_CONTENT


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


def test_expense_list_filters_by_store_ids_payment_status_and_payment_mode():
    user, store, category = create_store_setup()
    utility_category = ExpenseCategory.objects.create(code="utility", name="Eau")
    role = StoreMembership.objects.get(user=user, store=store).role
    second_store = Store.objects.create(code="finance-second", name="SECOND STORE", is_active=True)
    StoreMembership.objects.create(user=user, store=second_store, role=role)
    third_store = Store.objects.create(code="finance-third", name="THIRD STORE", is_active=True)

    Expense.objects.create(
        store=store,
        category=category,
        label="Loyer juin",
        amount=Decimal("1500.00"),
        payment_status=Expense.PaymentStatuses.PAID,
        payment_mode=Expense.PaymentModes.TRANSFER,
        expense_date=date(2026, 6, 1),
    )
    Expense.objects.create(
        store=second_store,
        category=utility_category,
        label="Eau magasin",
        amount=Decimal("120.00"),
        payment_status=Expense.PaymentStatuses.PAID,
        payment_mode=Expense.PaymentModes.CASH,
        expense_date=date(2026, 6, 2),
    )
    Expense.objects.create(
        store=third_store,
        category=category,
        label="Autre dépense",
        amount=Decimal("80.00"),
        payment_status=Expense.PaymentStatuses.PAID,
        payment_mode=Expense.PaymentModes.CASH,
        expense_date=date(2026, 6, 3),
    )

    client = authenticated_client(user)

    response = client.get(
        "/api/finance/",
        {
            "store_ids": f"{store.pk},{second_store.pk}",
            "category_ids": str(utility_category.pk),
            "payment_status": "paid",
            "payment_mode": "cash",
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["count"] == 1
    assert response.data["results"][0]["label"] == "Eau magasin"
