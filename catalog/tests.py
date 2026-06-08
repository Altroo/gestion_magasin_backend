from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from catalog.models import Category, Product, ProductUnit
from stock.models import StockBalance
from store.models import Role, Store, StoreMembership

pytestmark = pytest.mark.django_db

User = get_user_model()


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def create_store_setup(role_code=Role.Codes.RESPONSABLE):
    user = User.objects.create_user(
        email="catalog@example.com", password="securepass123"
    )
    role, _ = Role.objects.get_or_create(
        code=role_code,
        defaults={"name": role_code.title(), "rank": 1},
    )
    store = Store.objects.create(
        code="catalog-store", name="CATALOG STORE", is_active=True
    )
    StoreMembership.objects.create(user=user, store=store, role=role)
    category = Category.objects.create(code="catalog-family", name="Catalogue Famille")
    return user, store, category


def create_product(
    reference,
    name,
    category,
    counter_price="25.00",
    is_active=True,
    unit=None,
):
    return Product.objects.create(
        reference=reference,
        barcode=reference,
        name=name,
        category=category,
        unit=unit or ProductUnit.default(),
        purchase_price=Decimal("10.00"),
        counter_price=Decimal(counter_price),
        default_stock_alert=Decimal("2.000"),
        is_active=is_active,
    )


def test_product_list_filters_by_text_boolean_and_numeric_fields():
    user, store, category = create_store_setup()
    unit = ProductUnit.objects.create(code="piece-test", name="Pièce test")
    matching = create_product(
        "ART-LOW", "Article stock bas", category, counter_price="18.00", unit=unit
    )
    other = create_product(
        "ART-HIGH", "Article reserve", category, counter_price="40.00", is_active=False
    )
    StockBalance.objects.create(
        store=store,
        product=matching,
        quantity=Decimal("1.000"),
        min_stock=Decimal("2.000"),
    )
    StockBalance.objects.create(
        store=store,
        product=other,
        quantity=Decimal("12.000"),
        min_stock=Decimal("4.000"),
    )
    client = authenticated_client(user)

    response = client.get(
        "/api/catalog/products/",
        {
            "store": store.pk,
            "name__icontains": "stock",
            "is_active": "true",
            "counter_price__lt": "20",
            "category_ids": str(category.pk),
            "unit_ids": str(unit.pk),
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["count"] == 1
    assert response.data["results"][0]["id"] == matching.pk


def test_product_list_accepts_comma_separated_boolean_filters():
    user, store, category = create_store_setup()
    active = create_product("ART-ACTIVE", "Article actif", category, is_active=True)
    inactive = create_product(
        "ART-INACTIVE", "Article inactif", category, is_active=False
    )
    client = authenticated_client(user)

    response = client.get(
        "/api/catalog/products/",
        {
            "store": store.pk,
            "is_active": "true,false",
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert {item["id"] for item in response.data["results"]} == {active.pk, inactive.pk}


def test_product_bulk_delete_requires_store_management_role():
    user, store, category = create_store_setup(role_code=Role.Codes.LECTURE)
    product = create_product("ART-DELETE", "Article delete", category)
    client = authenticated_client(user)

    response = client.delete(
        "/api/catalog/products/bulk-delete/",
        {"ids": [product.pk]},
        format="json",
        QUERY_STRING=f"store={store.pk}",
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert Product.objects.filter(pk=product.pk).exists()


def test_product_bulk_delete_removes_selected_products_for_responsable():
    user, store, category = create_store_setup()
    product = create_product("ART-BULK", "Article bulk", category)
    client = authenticated_client(user)

    response = client.delete(
        "/api/catalog/products/bulk-delete/",
        {"ids": [product.pk]},
        format="json",
        QUERY_STRING=f"store={store.pk}",
    )

    assert response.status_code == status.HTTP_200_OK
    assert not Product.objects.filter(pk=product.pk).exists()


def test_product_create_requires_barcode_for_caisse_scan():
    user, store, category = create_store_setup()
    unit = ProductUnit.default()
    client = authenticated_client(user)

    response = client.post(
        f"/api/catalog/products/?store={store.pk}",
        {
            "reference": "NO-BARCODE",
            "barcode": "",
            "name": "Article sans code barre",
            "category": category.pk,
            "unit": unit.pk,
            "purchase_price": "10.00",
            "wholesale_price": "12.00",
            "detail_price": "14.00",
            "counter_price": "15.00",
            "default_stock_alert": "2.000",
            "is_active": True,
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "barcode" in response.data["details"]


def test_product_create_requires_expiration_date_when_tracking_is_enabled():
    user, store, category = create_store_setup()
    unit = ProductUnit.default()
    client = authenticated_client(user)

    response = client.post(
        f"/api/catalog/products/?store={store.pk}",
        {
            "reference": "EXP-REQUIRED",
            "barcode": "EXP-REQUIRED",
            "name": "Article expiration",
            "category": category.pk,
            "unit": unit.pk,
            "purchase_price": "10.00",
            "wholesale_price": "12.00",
            "detail_price": "14.00",
            "counter_price": "15.00",
            "default_stock_alert": "2.000",
            "requires_expiration_date": True,
            "is_active": True,
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "expiration_date" in response.data["details"]


def test_product_scan_unknown_barcode_returns_barcode_error():
    user, store, _category = create_store_setup()
    client = authenticated_client(user)

    response = client.get(
        "/api/catalog/products/scan/",
        {"store": store.pk, "code": "ABC"},
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.data["status_code"] == status.HTTP_404_NOT_FOUND
    assert response.data["details"]["barcode"] == ["Article introuvable."]


def test_product_import_guide_email_requires_management_role():
    user, store, _category = create_store_setup(role_code=Role.Codes.LECTURE)
    client = authenticated_client(user)

    response = client.post(
        "/api/catalog/products/send-csv-example-email/",
        {"store": store.pk},
        format="json",
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_product_import_guide_email_schedules_email_for_responsable():
    user, store, _category = create_store_setup()
    client = authenticated_client(user)

    with patch("account.tasks.send_csv_example_email.apply_async") as mocked_task:
        response = client.post(
            "/api/catalog/products/send-csv-example-email/",
            {"store": store.pk},
            format="json",
        )

    assert response.status_code == status.HTTP_200_OK
    mocked_task.assert_called_once_with((user.pk, user.email))
