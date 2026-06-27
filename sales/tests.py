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


def test_wholesale_sale_requires_user_permission():
    user = create_user("wholesale-denied@example.com")
    store, product = create_store_setup(user)
    client = authenticated_client(user)

    response = client.post(
        "/api/sales/",
        {
            "store": store.pk,
            "payment_mode_code": "cash",
            "sale_type": Sale.Types.WHOLESALE,
            "lines": [{"product": product.pk, "quantity": "1"}],
            "idempotency_key": "sale-wholesale-denied",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_wholesale_sale_uses_wholesale_price_and_prints_facture_pdf():
    user = create_user("wholesale-allowed@example.com")
    user.can_wholesale_sale = True
    user.can_print = True
    user.save(update_fields=["can_wholesale_sale", "can_print"])
    store, product = create_store_setup(user)
    product.wholesale_price = Decimal("17.00")
    product.save(update_fields=["wholesale_price"])
    client = authenticated_client(user)

    response = client.post(
        "/api/sales/",
        {
            "store": store.pk,
            "payment_mode_code": "cash",
            "sale_type": Sale.Types.WHOLESALE,
            "lines": [{"product": product.pk, "quantity": "1"}],
            "idempotency_key": "sale-wholesale-allowed",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED, response.data
    sale = Sale.objects.get(id=response.data["id"])
    assert sale.sale_type == Sale.Types.WHOLESALE
    assert sale.total == Decimal("17.00")

    pdf_response = client.get(f"/api/sales/{sale.pk}/facture/")
    assert pdf_response.status_code == status.HTTP_200_OK
    assert pdf_response["Content-Type"] == "application/pdf"
    assert pdf_response.content.startswith(b"%PDF")


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


def test_payment_mode_list_filters_active_modes():
    user = create_user("payment-mode-filter@example.com")
    active = PaymentMode.objects.create(
        code="active-filter-test", name="Actif filtre", is_active=True
    )
    inactive = PaymentMode.objects.create(
        code="inactive-filter-test", name="Inactif filtre", is_active=False
    )
    client = authenticated_client(user)

    response = client.get("/api/sales/payment-modes/", {"is_active": "true"})

    assert response.status_code == status.HTTP_200_OK
    ids = {item["id"] for item in response.data["results"]}
    assert active.pk in ids
    assert inactive.pk not in ids


def test_promotion_eligible_stores_marks_missing_stock_as_disabled():
    staff = create_user("promotion-admin@example.com")
    staff.is_staff = True
    staff.is_superuser = True
    staff.can_create_promotion = True
    staff.save(update_fields=["is_staff", "is_superuser", "can_create_promotion"])
    category, _ = Category.objects.get_or_create(
        code="promo-cat", defaults={"name": "Famille promotion"}
    )
    product = Product.objects.create(
        reference="PROMO-001",
        barcode="PROMO-001",
        name="Article promotion eligible",
        category=category,
        purchase_price=Decimal("10.00"),
        counter_price=Decimal("20.00"),
        default_stock_alert=Decimal("1.000"),
    )
    eligible_store = Store.objects.create(
        code="eligible-store", name="Magasin eligible", is_active=True
    )
    disabled_store = Store.objects.create(
        code="disabled-store", name="Magasin disabled", is_active=True
    )
    StockBalance.objects.create(
        store=eligible_store,
        product=product,
        quantity=Decimal("3.000"),
        average_cost=Decimal("10.00"),
    )
    StockBalance.objects.create(
        store=disabled_store,
        product=product,
        quantity=Decimal("1.000"),
        average_cost=Decimal("10.00"),
    )
    client = authenticated_client(staff)

    response = client.get(
        "/api/sales/promotions/eligible-stores/",
        {"product_ids": str(product.pk), "quantities": "2"},
    )

    assert response.status_code == status.HTTP_200_OK
    eligibility = {item["id"]: item for item in response.data}
    assert eligibility[eligible_store.pk]["is_eligible"] is True
    assert eligibility[disabled_store.pk]["is_eligible"] is False
    assert eligibility[disabled_store.pk]["missing_products"][0]["product"] == product.pk


def test_staff_can_create_promotion_for_multiple_eligible_stores():
    staff = create_user("promotion-bulk-admin@example.com")
    staff.is_staff = True
    staff.is_superuser = True
    staff.can_create_promotion = True
    staff.save(update_fields=["is_staff", "is_superuser", "can_create_promotion"])
    category, _ = Category.objects.get_or_create(
        code="promo-bulk-cat", defaults={"name": "Famille promotion bulk"}
    )
    product = Product.objects.create(
        reference="PROMO-002",
        barcode="PROMO-002",
        name="Article promotion bulk",
        category=category,
        purchase_price=Decimal("8.00"),
        counter_price=Decimal("18.00"),
        default_stock_alert=Decimal("1.000"),
    )
    first_store = Store.objects.create(
        code="promo-store-1", name="Magasin promo 1", is_active=True
    )
    second_store = Store.objects.create(
        code="promo-store-2", name="Magasin promo 2", is_active=True
    )
    for store in (first_store, second_store):
        StockBalance.objects.create(
            store=store,
            product=product,
            quantity=Decimal("4.000"),
            average_cost=Decimal("8.00"),
        )
    client = authenticated_client(staff)

    response = client.post(
        "/api/sales/promotions/",
        {
            "stores": [first_store.pk, second_store.pk],
            "name": "Pack multi magasins",
            "selling_price": "30.00",
            "status": Promotion.Statuses.ACTIVE,
            "lines": [{"product": product.pk, "quantity": "2"}],
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["count"] == 2
    assert Promotion.objects.filter(name="Pack multi magasins").count() == 2
    assert set(
        Promotion.objects.filter(name="Pack multi magasins").values_list(
            "store_id", flat=True
        )
    ) == {first_store.pk, second_store.pk}


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
