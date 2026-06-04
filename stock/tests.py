from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from catalog.models import Category, Product
from stock.models import StockBalance
from store.models import Role, Store, StoreMembership

pytestmark = pytest.mark.django_db

User = get_user_model()


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def create_store_setup(role_code=Role.Codes.RESPONSABLE):
    user = User.objects.create_user(email="stock@example.com", password="securepass123")
    role, _ = Role.objects.get_or_create(
        code=role_code,
        defaults={"name": role_code.title(), "rank": 1},
    )
    store = Store.objects.create(code="stock-store", name="STOCK STORE", is_active=True)
    StoreMembership.objects.create(user=user, store=store, role=role)
    category = Category.objects.create(code="stock-family", name="Stock Famille")
    return user, store, category


def create_balance(store, category, reference, name, quantity, min_stock):
    product = Product.objects.create(
        reference=reference,
        barcode=reference,
        name=name,
        category=category,
        purchase_price=Decimal("10.00"),
        counter_price=Decimal("25.00"),
        default_stock_alert=Decimal("2.000"),
    )
    return StockBalance.objects.create(
        store=store,
        product=product,
        quantity=Decimal(quantity),
        min_stock=Decimal(min_stock),
        average_cost=Decimal("10.00"),
    )


def test_stock_list_filters_low_stock_and_numeric_quantity():
    user, store, category = create_store_setup()
    low_balance = create_balance(store, category, "STK-LOW", "Article stock bas", "1.000", "2.000")
    create_balance(store, category, "STK-OK", "Article reserve", "12.000", "4.000")
    client = authenticated_client(user)

    response = client.get(
        "/api/stock/balances/",
        {
            "store": store.pk,
            "low": "true",
            "quantity__lte": "2",
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["count"] == 1
    assert response.data["results"][0]["id"] == low_balance.pk


def test_stock_list_accepts_comma_separated_low_filter_values():
    user, store, category = create_store_setup()
    low_balance = create_balance(store, category, "STK-CSV-LOW", "Article stock bas", "1.000", "2.000")
    ok_balance = create_balance(store, category, "STK-CSV-OK", "Article reserve", "12.000", "4.000")
    client = authenticated_client(user)

    response = client.get(
        "/api/stock/balances/",
        {
            "store": store.pk,
            "low": "true,false",
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert {item["id"] for item in response.data["results"]} == {low_balance.pk, ok_balance.pk}


def test_stock_threshold_update_requires_management_role():
    user, store, category = create_store_setup(role_code=Role.Codes.LECTURE)
    balance = create_balance(store, category, "STK-READ", "Article lecture", "5.000", "2.000")
    client = authenticated_client(user)

    response = client.patch(
        f"/api/stock/balances/{balance.pk}/threshold/",
        {"min_stock": "7.000"},
        format="json",
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    balance.refresh_from_db()
    assert balance.min_stock == Decimal("2.000")


def test_stock_threshold_update_for_responsable():
    user, store, category = create_store_setup()
    balance = create_balance(store, category, "STK-EDIT", "Article edit", "5.000", "2.000")
    client = authenticated_client(user)

    response = client.patch(
        f"/api/stock/balances/{balance.pk}/threshold/",
        {"min_stock": "7.000"},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    balance.refresh_from_db()
    assert balance.min_stock == Decimal("7.000")


def test_stock_bulk_delete_removes_selected_balance_for_responsable():
    user, store, category = create_store_setup()
    balance = create_balance(store, category, "STK-BULK", "Article bulk", "5.000", "2.000")
    client = authenticated_client(user)

    response = client.delete(
        "/api/stock/balances/bulk-delete/",
        {"ids": [balance.pk]},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert not StockBalance.objects.filter(pk=balance.pk).exists()
