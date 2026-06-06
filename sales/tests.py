from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from catalog.models import Category, Product
from notification.models import Notification
from notification.tasks import notify_low_stock_if_needed
from sales.models import (
    PaymentMode,
    Promotion,
    PromotionLine,
    Sale,
    SaleLine,
    SalePromotionLine,
)
from stock.models import StockBalance, StockMovement
from store.models import Role, Store, StoreMembership

pytestmark = pytest.mark.django_db

User = get_user_model()


def create_user(email="seller@example.com"):
    return User.objects.create_user(email=email, password="securepass123")


def create_store_setup(user, role_code=Role.Codes.VENDEUR):
    role, _ = Role.objects.get_or_create(
        code=role_code,
        defaults={"name": role_code.title(), "rank": 1},
    )
    store, _ = Store.objects.get_or_create(
        code="mbr-test",
        defaults={"name": "MBR TEST", "is_active": True},
    )
    StoreMembership.objects.get_or_create(user=user, store=store, role=role)
    PaymentMode.objects.get_or_create(code="cash", defaults={"name": "Espèces"})
    category, _ = Category.objects.get_or_create(
        code="1", defaults={"name": "Famille 1"}
    )
    product = Product.objects.create(
        reference="ART-001",
        barcode="ART-001",
        name="Article test",
        category=category,
        purchase_price=Decimal("10.00"),
        counter_price=Decimal("25.00"),
        default_stock_alert=Decimal("2.000"),
    )
    StockBalance.objects.create(
        store=store,
        product=product,
        quantity=Decimal("3.000"),
        min_stock=Decimal("2.000"),
        average_cost=Decimal("10.00"),
    )
    return store, product


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_confirm_sale_reduces_stock_and_creates_audit_rows():
    user = create_user()
    store, product = create_store_setup(user)
    client = authenticated_client(user)

    response = client.post(
        "/api/sales/",
        {
            "store": store.pk,
            "payment_mode_code": "cash",
            "lines": [{"product": product.pk, "quantity": "1", "unit_price": "25.00"}],
            "idempotency_key": "sale-001",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    sale = Sale.objects.get(id=response.data["id"])
    assert sale.total == Decimal("25.00")
    assert SaleLine.objects.filter(
        sale=sale, product=product, quantity=Decimal("1.000")
    ).exists()

    balance = StockBalance.objects.get(store=store, product=product)
    assert balance.quantity == Decimal("2.000")
    assert StockMovement.objects.filter(
        store=store,
        product=product,
        movement_type=StockMovement.Types.SALE,
        quantity=Decimal("-1.000"),
        source_id=sale.pk,
    ).exists()


def test_confirm_promotion_sale_reduces_component_stock():
    user = create_user("promo-seller@example.com")
    store, product = create_store_setup(user)
    category = product.category
    second_product = Product.objects.create(
        reference="ART-002",
        barcode="ART-002",
        name="Article promotion",
        category=category,
        purchase_price=Decimal("8.00"),
        counter_price=Decimal("18.00"),
        default_stock_alert=Decimal("2.000"),
    )
    StockBalance.objects.create(
        store=store,
        product=second_product,
        quantity=Decimal("5.000"),
        min_stock=Decimal("1.000"),
        average_cost=Decimal("8.00"),
    )
    promotion = Promotion.objects.create(
        store=store,
        name="Pack test",
        selling_price=Decimal("40.00"),
        status=Promotion.Statuses.ACTIVE,
        created_by=user,
    )
    PromotionLine.objects.create(
        promotion=promotion,
        product=product,
        quantity=Decimal("2.000"),
    )
    PromotionLine.objects.create(
        promotion=promotion,
        product=second_product,
        quantity=Decimal("1.000"),
    )
    client = authenticated_client(user)

    response = client.post(
        "/api/sales/",
        {
            "store": store.pk,
            "payment_mode_code": "cash",
            "promotion_lines": [
                {"promotion": promotion.pk, "quantity": "1", "unit_price": "40.00"}
            ],
            "idempotency_key": "sale-promo-001",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    sale = Sale.objects.get(id=response.data["id"])
    assert sale.total == Decimal("40.00")
    assert SalePromotionLine.objects.filter(sale=sale, promotion=promotion).exists()
    assert StockBalance.objects.get(store=store, product=product).quantity == Decimal(
        "1.000"
    )
    assert StockBalance.objects.get(
        store=store, product=second_product
    ).quantity == Decimal("4.000")


def test_promotions_bulk_delete_removes_selected_promotions():
    user = create_user("promo-bulk@example.com")
    user.can_create_promotion = True
    user.save(update_fields=["can_create_promotion"])
    store, _product = create_store_setup(user, Role.Codes.RESPONSABLE)
    first = Promotion.objects.create(
        store=store,
        name="Bulk promo 1",
        selling_price=Decimal("10.00"),
        created_by=user,
    )
    second = Promotion.objects.create(
        store=store,
        name="Bulk promo 2",
        selling_price=Decimal("12.00"),
        created_by=user,
    )
    client = authenticated_client(user)

    response = client.delete(
        "/api/sales/promotions/bulk-delete/",
        {"ids": [first.pk, second.pk]},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["deleted"] == 2
    assert not Promotion.objects.filter(pk__in=[first.pk, second.pk]).exists()


def test_low_stock_task_notifies_store_managers():
    responsible = create_user("responsable@example.com")
    store, product = create_store_setup(responsible, role_code=Role.Codes.RESPONSABLE)
    balance = StockBalance.objects.get(store=store, product=product)
    balance.quantity = Decimal("2.000")
    balance.save(update_fields=["quantity"])

    notify_low_stock_if_needed(balance.pk)

    notification = Notification.objects.get(
        user=responsible, product=product, store=store
    )
    assert notification.notification_type == Notification.Types.LOW_STOCK
    assert "Stock minimum atteint" in notification.title


def test_lecture_role_cannot_confirm_sale():
    user = create_user("lecture@example.com")
    store, product = create_store_setup(user, role_code=Role.Codes.LECTURE)
    client = authenticated_client(user)

    response = client.post(
        "/api/sales/",
        {
            "store": store.pk,
            "lines": [{"product": product.pk, "quantity": "1"}],
        },
        format="json",
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_sales_list_accepts_comma_separated_status_filters():
    user = create_user("sales-filter@example.com")
    store, _product = create_store_setup(user)
    confirmed = Sale.objects.create(
        store=store, seller=user, status=Sale.Statuses.CONFIRMED
    )
    void = Sale.objects.create(store=store, seller=user, status=Sale.Statuses.VOID)
    client = authenticated_client(user)

    response = client.get(
        "/api/sales/",
        {
            "store": store.pk,
            "status": "confirmed,void",
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert {item["id"] for item in response.data["results"]} == {confirmed.pk, void.pk}


def test_sales_list_filters_by_payment_mode_id():
    user = create_user("sales-payment-mode-filter@example.com")
    store, _product = create_store_setup(user)
    cash = PaymentMode.objects.get(code="cash")
    card = PaymentMode.objects.create(code="card-test", name="Carte test")
    cash_sale = Sale.objects.create(store=store, seller=user, payment_mode=cash)
    Sale.objects.create(store=store, seller=user, payment_mode=card)
    client = authenticated_client(user)

    response = client.get(
        "/api/sales/",
        {
            "store": store.pk,
            "payment_mode": str(cash.pk),
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert [item["id"] for item in response.data["results"]] == [cash_sale.pk]
