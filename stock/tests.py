from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from catalog.models import Category, Product, ProductUnit
from stock.models import (
    InventorySession,
    Purchase,
    StockBalance,
    StockMovement,
    StockTransfer,
)
from store.models import Role, Store, StoreMembership

pytestmark = pytest.mark.django_db

User = get_user_model()


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def create_store_setup(role_code=Role.Codes.RESPONSABLE, is_global_stock=False):
    user = User.objects.create_user(email="stock@example.com", password="securepass123")
    role, _ = Role.objects.get_or_create(
        code=role_code,
        defaults={"name": role_code.title(), "rank": 1},
    )
    store = Store.objects.create(
        code=f"stock-store-{is_global_stock}",
        name=f"STOCK STORE {is_global_stock}",
        is_active=True,
        is_global_stock=is_global_stock,
    )
    StoreMembership.objects.create(user=user, store=store, role=role)
    category = Category.objects.create(code="stock-family", name="Stock Famille")
    return user, store, category


def create_balance(store, category, reference, name, quantity, min_stock, unit=None):
    product = Product.objects.create(
        reference=reference,
        barcode=reference,
        name=name,
        category=category,
        unit=unit or ProductUnit.default(),
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
    unit = ProductUnit.objects.create(code="stock-piece-test", name="Pièce stock test")
    low_balance = create_balance(
        store,
        category,
        "STK-LOW",
        "Article stock bas",
        "1.000",
        "2.000",
        unit=unit,
    )
    create_balance(store, category, "STK-OK", "Article reserve", "12.000", "4.000")
    client = authenticated_client(user)

    response = client.get(
        "/api/stock/balances/",
        {
            "store": store.pk,
            "low": "true",
            "quantity__lte": "2",
            "category_ids": str(category.pk),
            "unit_ids": str(unit.pk),
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["count"] == 1
    assert response.data["results"][0]["id"] == low_balance.pk
    assert response.data["results"][0]["unit_name"] == unit.name


def test_stock_list_accepts_comma_separated_low_filter_values():
    user, store, category = create_store_setup()
    low_balance = create_balance(
        store, category, "STK-CSV-LOW", "Article stock bas", "1.000", "2.000"
    )
    ok_balance = create_balance(
        store, category, "STK-CSV-OK", "Article reserve", "12.000", "4.000"
    )
    client = authenticated_client(user)

    response = client.get(
        "/api/stock/balances/",
        {
            "store": store.pk,
            "low": "true,false",
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert {item["id"] for item in response.data["results"]} == {
        low_balance.pk,
        ok_balance.pk,
    }


def test_stock_threshold_update_requires_management_role():
    user, store, category = create_store_setup(role_code=Role.Codes.LECTURE)
    balance = create_balance(
        store, category, "STK-READ", "Article lecture", "5.000", "2.000"
    )
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
    balance = create_balance(
        store, category, "STK-EDIT", "Article edit", "5.000", "2.000"
    )
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
    balance = create_balance(
        store, category, "STK-BULK", "Article bulk", "5.000", "2.000"
    )
    client = authenticated_client(user)

    response = client.delete(
        "/api/stock/balances/bulk-delete/",
        {"ids": [balance.pk]},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert not StockBalance.objects.filter(pk=balance.pk).exists()


def test_stock_adjustment_adds_stock_for_responsable_store():
    user, store, category = create_store_setup(is_global_stock=False)
    balance = create_balance(
        store, category, "STK-ADD", "Article ajout", "5.000", "2.000"
    )
    client = authenticated_client(user)

    response = client.post(
        "/api/stock/balances/adjust/",
        {
            "store": store.pk,
            "product": balance.product.pk,
            "quantity": "50.000",
            "movement_type": StockMovement.Types.ADJUSTMENT,
            "note": "Achat manuel magasin",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    balance.refresh_from_db()
    assert balance.quantity == Decimal("55.000")
    assert StockMovement.objects.filter(
        store=store,
        product=balance.product,
        movement_type=StockMovement.Types.ADJUSTMENT,
        quantity=Decimal("50.000"),
    ).exists()


def test_received_purchase_adds_stock_and_purchase_movement():
    user, store, category = create_store_setup(is_global_stock=True)
    product = create_balance(
        store, category, "PUR-001", "Article achat", "2.000", "1.000"
    ).product
    client = authenticated_client(user)

    response = client.post(
        "/api/stock/purchases/",
        {
            "store": store.pk,
            "supplier_name": "Fournisseur test",
            "reference": "BL-001",
            "status": "received",
            "lines": [
                {"product": product.pk, "quantity": "3.000", "unit_cost": "12.50"}
            ],
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    purchase = Purchase.objects.get(pk=response.data["id"])
    assert purchase.status == Purchase.Statuses.RECEIVED
    balance = StockBalance.objects.get(store=store, product=product)
    assert balance.quantity == Decimal("5.000")
    assert StockMovement.objects.filter(
        store=store,
        product=product,
        movement_type=StockMovement.Types.PURCHASE,
        quantity=Decimal("3.000"),
        source_id=purchase.pk,
    ).exists()


def test_validated_transfer_moves_stock_from_mbr_to_store():
    user, source_store, category = create_store_setup(is_global_stock=True)
    target_store = Store.objects.create(
        code="stock-target", name="STOCK TARGET", is_active=True
    )
    role = Role.objects.get(code=Role.Codes.RESPONSABLE)
    StoreMembership.objects.create(user=user, store=target_store, role=role)
    source_balance = create_balance(
        source_store,
        category,
        "TR-001",
        "Article transfert",
        "20.000",
        "5.000",
    )
    client = authenticated_client(user)

    response = client.post(
        "/api/stock/transfers/",
        {
            "store": source_store.pk,
            "target_store": target_store.pk,
            "reference": "TR-DEMO",
            "status": "validated",
            "lines": [
                {
                    "product": source_balance.product.pk,
                    "quantity": "6.000",
                }
            ],
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    transfer = StockTransfer.objects.get(pk=response.data["id"])
    assert transfer.status == StockTransfer.Statuses.VALIDATED
    source_balance.refresh_from_db()
    target_balance = StockBalance.objects.get(
        store=target_store,
        product=source_balance.product,
    )
    assert source_balance.quantity == Decimal("14.000")
    assert target_balance.quantity == Decimal("6.000")
    assert StockMovement.objects.filter(
        store=source_store,
        product=source_balance.product,
        movement_type=StockMovement.Types.TRANSFER_OUT,
        quantity=Decimal("-6.000"),
        source_id=transfer.pk,
    ).exists()


def test_validated_inventory_adjusts_stock_to_counted_quantity():
    user, store, category = create_store_setup()
    balance = create_balance(
        store, category, "INV-001", "Article inventaire", "8.000", "1.000"
    )
    client = authenticated_client(user)

    response = client.post(
        "/api/stock/inventory/",
        {
            "store": store.pk,
            "code": "INV-2026-001",
            "title": "Inventaire juin",
            "status": "validated",
            "lines": [
                {
                    "product": balance.product.pk,
                    "expected_quantity": "8.000",
                    "counted_quantity": "6.000",
                }
            ],
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    session = InventorySession.objects.get(pk=response.data["id"])
    assert session.status == InventorySession.Statuses.VALIDATED
    balance.refresh_from_db()
    assert balance.quantity == Decimal("6.000")
    assert StockMovement.objects.filter(
        store=store,
        product=balance.product,
        movement_type=StockMovement.Types.INVENTORY,
        quantity=Decimal("-2.000"),
        source_id=session.pk,
    ).exists()


def test_draft_inventory_can_be_edited_before_validation():
    user, store, category = create_store_setup()
    balance = create_balance(
        store, category, "INV-EDIT", "Article inventaire edit", "8.000", "1.000"
    )
    client = authenticated_client(user)
    create_response = client.post(
        "/api/stock/inventory/",
        {
            "store": store.pk,
            "code": "INV-DRAFT",
            "title": "Inventaire draft",
            "status": "draft",
            "lines": [
                {
                    "product": balance.product.pk,
                    "expected_quantity": "8.000",
                    "counted_quantity": "8.000",
                }
            ],
        },
        format="json",
    )
    session = InventorySession.objects.get(pk=create_response.data["id"])

    response = client.put(
        f"/api/stock/inventory/{session.pk}/",
        {
            "store": store.pk,
            "code": "INV-DRAFT-UPDATED",
            "title": "Inventaire draft modifie",
            "status": "draft",
            "lines": [
                {
                    "product": balance.product.pk,
                    "expected_quantity": "8.000",
                    "counted_quantity": "7.000",
                    "note": "Comptage corrige",
                }
            ],
        },
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    session.refresh_from_db()
    line = session.lines.get()
    assert session.code == "INV-DRAFT-UPDATED"
    assert session.title == "Inventaire draft modifie"
    assert session.status == InventorySession.Statuses.DRAFT
    assert line.counted_quantity == Decimal("7.000")
    assert line.note == "Comptage corrige"


def test_validated_inventory_cannot_be_edited_or_deleted():
    user, store, category = create_store_setup()
    balance = create_balance(
        store, category, "INV-LOCK", "Article inventaire verrouille", "8.000", "1.000"
    )
    client = authenticated_client(user)
    create_response = client.post(
        "/api/stock/inventory/",
        {
            "store": store.pk,
            "code": "INV-LOCK",
            "title": "Inventaire valide",
            "status": "validated",
            "lines": [
                {
                    "product": balance.product.pk,
                    "expected_quantity": "8.000",
                    "counted_quantity": "6.000",
                }
            ],
        },
        format="json",
    )
    session = InventorySession.objects.get(pk=create_response.data["id"])

    edit_response = client.put(
        f"/api/stock/inventory/{session.pk}/",
        {
            "store": store.pk,
            "code": "INV-LOCK-UPDATED",
            "title": "Inventaire modifie",
            "status": "draft",
            "lines": [
                {
                    "product": balance.product.pk,
                    "expected_quantity": "8.000",
                    "counted_quantity": "5.000",
                }
            ],
        },
        format="json",
    )
    delete_response = client.delete(f"/api/stock/inventory/{session.pk}/")

    assert edit_response.status_code == status.HTTP_400_BAD_REQUEST
    assert delete_response.status_code == status.HTTP_400_BAD_REQUEST
    session.refresh_from_db()
    balance.refresh_from_db()
    assert session.status == InventorySession.Statuses.VALIDATED
    assert session.code == "INV-LOCK"
    assert balance.quantity == Decimal("6.000")
