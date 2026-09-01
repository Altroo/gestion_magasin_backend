from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from catalog.models import Category, Product, ProductStockTrackingItem, ProductUnit
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


def test_product_list_filters_across_all_expiration_dates():
    user, store, category = create_store_setup()
    product = create_product("ART-EXP-FILTER", "Article expirations", category)
    ProductStockTrackingItem.objects.create(
        product=product,
        default_stock_alert=Decimal("2.000"),
        expiration_date="2026-08-01",
        position=0,
    )
    ProductStockTrackingItem.objects.create(
        product=product,
        default_stock_alert=Decimal("2.000"),
        expiration_date="2027-02-01",
        position=1,
    )
    client = authenticated_client(user)

    response = client.get(
        "/api/catalog/products/",
        {
            "store": store.pk,
            "expiration_date_after": "2027-01-01",
            "expiration_date_before": "2027-12-31",
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["count"] == 1
    assert response.data["results"][0]["id"] == product.pk


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


def test_product_create_persists_multiple_stock_tracking_items():
    user, store, category = create_store_setup()
    unit = ProductUnit.default()
    client = authenticated_client(user)

    response = client.post(
        f"/api/catalog/products/?store={store.pk}",
        {
            "reference": "MULTI-EXP",
            "barcode": "MULTI-EXP",
            "name": "Article plusieurs expirations",
            "category": category.pk,
            "unit": unit.pk,
            "purchase_price": "10.00",
            "wholesale_price": "12.00",
            "detail_price": "14.00",
            "counter_price": "15.00",
            "stock_tracking_items": [
                {
                    "default_stock_alert": "2.000",
                    "expiration_date": "2026-10-15",
                    "requires_expiration_date": True,
                    "shelf_life_days": 90,
                },
                {
                    "default_stock_alert": "5.000",
                    "expiration_date": "2027-01-20",
                    "requires_expiration_date": True,
                    "shelf_life_days": 180,
                },
            ],
            "is_active": True,
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert len(response.data["stock_tracking_items"]) == 2
    assert [
        item["expiration_date"] for item in response.data["stock_tracking_items"]
    ] == ["2026-10-15", "2027-01-20"]
    product = Product.objects.get(pk=response.data["id"])
    assert product.stock_tracking_items.count() == 2
    assert product.default_stock_alert == Decimal("2.000")
    assert product.expiration_date.isoformat() == "2026-10-15"


def test_product_update_replaces_stock_tracking_items():
    user, store, category = create_store_setup()
    product = create_product("MULTI-UPDATE", "Article à modifier", category)
    ProductStockTrackingItem.objects.create(
        product=product,
        default_stock_alert=Decimal("2.000"),
        expiration_date="2026-08-01",
        requires_expiration_date=True,
        shelf_life_days=30,
        position=0,
    )
    client = authenticated_client(user)

    response = client.patch(
        f"/api/catalog/products/{product.pk}/?store={store.pk}",
        {
            "stock_tracking_items": [
                {
                    "default_stock_alert": "3.000",
                    "expiration_date": "2026-11-01",
                    "requires_expiration_date": True,
                    "shelf_life_days": 60,
                },
                {
                    "default_stock_alert": "4.000",
                    "expiration_date": None,
                    "requires_expiration_date": False,
                    "shelf_life_days": None,
                },
            ]
        },
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert len(response.data["stock_tracking_items"]) == 2
    assert list(
        product.stock_tracking_items.order_by("position").values_list(
            "position", "default_stock_alert"
        )
    ) == [(0, Decimal("3.000")), (1, Decimal("4.000"))]
    product.refresh_from_db()
    assert product.expiration_date.isoformat() == "2026-11-01"


def test_product_stock_tracking_item_requires_its_expiration_date():
    user, store, category = create_store_setup()
    client = authenticated_client(user)

    response = client.post(
        f"/api/catalog/products/?store={store.pk}",
        {
            "reference": "MULTI-INVALID",
            "barcode": "MULTI-INVALID",
            "name": "Article expiration invalide",
            "category": category.pk,
            "unit": ProductUnit.default().pk,
            "purchase_price": "10.00",
            "wholesale_price": "12.00",
            "detail_price": "14.00",
            "counter_price": "15.00",
            "stock_tracking_items": [
                {
                    "default_stock_alert": "2.000",
                    "expiration_date": None,
                    "requires_expiration_date": True,
                    "shelf_life_days": 90,
                }
            ],
            "is_active": True,
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert (
        "expiration_date"
        in response.data["details"]["stock_tracking_items"][0]
    )


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


def test_product_scan_reports_zero_when_store_has_no_stock_balance():
    user, store, category = create_store_setup()
    product = create_product("ART-NO-STOCK", "Article sans stock", category)
    client = authenticated_client(user)

    response = client.get(
        "/api/catalog/products/scan/",
        {"store": store.pk, "code": product.barcode},
    )

    assert response.status_code == status.HTTP_200_OK
    assert Decimal(response.data["available_stock"]) == Decimal("0")


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
