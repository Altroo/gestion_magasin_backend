from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from catalog.models import Category, Product, ProductStockTrackingItem
from finance.models import Expense, ExpenseCategory
from sales.models import Sale
from stock.models import StockBalance
from store.models import Role, Store, StoreMembership

pytestmark = pytest.mark.django_db

User = get_user_model()


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def create_store_setup():
    user = User.objects.create_user(email="reports@example.com", password="securepass123")
    role, _ = Role.objects.get_or_create(
        code=Role.Codes.RESPONSABLE,
        defaults={"name": "Responsable", "rank": 1},
    )
    store = Store.objects.create(code="report-store", name="REPORT STORE", is_active=True)
    StoreMembership.objects.create(user=user, store=store, role=role)
    category = Category.objects.create(code="report-family", name="Report Family")
    product = Product.objects.create(
        reference="REP-001",
        barcode="REP-001",
        name="Article rapport",
        category=category,
        purchase_price=Decimal("10.00"),
        counter_price=Decimal("25.00"),
        default_stock_alert=Decimal("5.000"),
    )
    StockBalance.objects.create(store=store, product=product, quantity=Decimal("3.000"), min_stock=Decimal("5.000"))
    return user, store, product


def test_dashboard_report_returns_kpis_and_low_stock_alerts():
    user, store, _product = create_store_setup()
    expense_category = ExpenseCategory.objects.create(code="ops", name="Ops")
    Expense.objects.create(
        store=store,
        category=expense_category,
        label="Charge",
        amount=Decimal("100.00"),
        expense_date=date(2026, 6, 1),
    )
    Sale.objects.create(store=store, seller=user, total=Decimal("250.00"))
    client = authenticated_client(user)

    response = client.get("/api/reports/dashboard/", {"store": store.pk, "date_from": "2026-06-01",
                                                      "date_to": "2026-06-30"})

    assert response.status_code == status.HTTP_200_OK
    assert response.data["kpis"]["low_stock_count"] == 1
    assert len(response.data["stock_alerts"]) == 1


def test_dashboard_counts_product_when_any_stock_tracking_item_expires_soon():
    user, store, product = create_store_setup()
    today = timezone.localdate()
    ProductStockTrackingItem.objects.create(
        product=product,
        default_stock_alert=Decimal("5.000"),
        expiration_date=today + timedelta(days=90),
        position=0,
    )
    ProductStockTrackingItem.objects.create(
        product=product,
        default_stock_alert=Decimal("5.000"),
        expiration_date=today + timedelta(days=10),
        position=1,
    )
    client = authenticated_client(user)

    response = client.get(
        "/api/reports/dashboard/",
        {
            "store": store.pk,
            "date_from": today.isoformat(),
            "date_to": today.isoformat(),
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["kpis"]["expiring_count"] == 1


def test_dashboard_report_all_stores_scope_for_staff():
    user, store, _product = create_store_setup()
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    other_store = Store.objects.create(code="report-other", name="REPORT OTHER", is_active=True)
    sale = Sale.objects.create(store=store, seller=user, total=Decimal("100.00"))
    other_sale = Sale.objects.create(store=other_store, seller=user, total=Decimal("50.00"))
    # auto_now_add uses the current date; place both sales in the requested period.
    Sale.objects.filter(pk__in=[sale.pk, other_sale.pk]).update(
        date_created=timezone.make_aware(datetime(2026, 6, 15, 12)),
    )
    client = authenticated_client(user)

    response = client.get(
        "/api/reports/dashboard/",
        {"store": "all", "date_from": "2026-06-01", "date_to": "2026-06-30"},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["store"]["id"] is None
    assert response.data["kpis"]["sales_count"] == 2
    assert response.data["kpis"]["sales_total"] == Decimal("150.00")
    assert response.data["sales_trend"] == [
        {"date": date(2026, 6, 15), "total": Decimal("150.00"), "count": 2},
    ]


@pytest.mark.parametrize(
    "is_staff,all_stores,expected_count,expected_total",
    [
        pytest.param(True, True, 2, "150.00", id="staff-all-stores"),
        pytest.param(True, False, 1, "100.00", id="staff-selected-store"),
        pytest.param(False, True, 1, "100.00", id="member-all-stores"),
        pytest.param(False, False, 1, "100.00", id="member-selected-store"),
    ],
)
def test_dashboard_report_filters_sales_by_period_status_and_store(
    is_staff, all_stores, expected_count, expected_total,
):
    user, store, _product = create_store_setup()
    user.is_staff = is_staff
    user.save(update_fields=["is_staff"])
    other_store = Store.objects.create(
        code="report-other", name="REPORT OTHER", is_active=True,
    )
    for sale_store, created_at, sale_status, total in [
        (store, datetime(2026, 6, 1), Sale.Statuses.CONFIRMED, "100.00"),
        (
            other_store,
            datetime(2026, 6, 30, 23, 59, 59, 999999),
            Sale.Statuses.CONFIRMED,
            "50.00",
        ),
        (
            store,
            datetime(2026, 5, 31, 23, 59, 59, 999999),
            Sale.Statuses.CONFIRMED,
            "200.00",
        ),
        (store, datetime(2026, 7, 1), Sale.Statuses.CONFIRMED, "300.00"),
        (store, datetime(2026, 6, 15, 12), Sale.Statuses.VOID, "400.00"),
    ]:
        sale = Sale.objects.create(
            store=sale_store, seller=user, status=sale_status, total=Decimal(total),
        )
        Sale.objects.filter(pk=sale.pk).update(
            date_created=timezone.make_aware(created_at),
        )

    response = authenticated_client(user).get(
        "/api/reports/dashboard/",
        {
            "store": "all" if all_stores else store.pk,
            "date_from": "2026-06-01",
            "date_to": "2026-06-30",
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["kpis"]["sales_count"] == expected_count
    assert response.data["kpis"]["sales_total"] == Decimal(expected_total)


def test_stock_export_csv_returns_file_response():
    user, store, _product = create_store_setup()
    client = authenticated_client(user)

    response = client.get("/api/reports/export/stock/", {"store": store.pk, "format": "csv"})

    assert response.status_code == status.HTTP_200_OK
    assert response["Content-Type"].startswith("text/csv")
    assert "attachment" in response["Content-Disposition"]


def test_stock_export_pdf_opens_inline_with_pdf_filename():
    pytest.importorskip("reportlab")

    user, store, _product = create_store_setup()
    client = authenticated_client(user)

    response = client.get("/api/reports/export/stock/", {"store": store.pk, "format": "pdf"})

    assert response.status_code == status.HTTP_200_OK
    assert response["Content-Type"].startswith("application/pdf")
    assert "inline" in response["Content-Disposition"]
    assert 'filename="stock.pdf"' in response["Content-Disposition"]
