from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from catalog.models import Category, Product
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

    response = client.get("/api/reports/dashboard/", {"store": store.pk, "date_from": "2026-06-01", "date_to": "2026-06-30"})

    assert response.status_code == status.HTTP_200_OK
    assert response.data["kpis"]["low_stock_count"] == 1
    assert len(response.data["stock_alerts"]) == 1


def test_dashboard_report_all_stores_scope_for_staff():
    user, store, _product = create_store_setup()
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    other_store = Store.objects.create(code="report-other", name="REPORT OTHER", is_active=True)
    Sale.objects.create(store=store, seller=user, total=Decimal("100.00"))
    Sale.objects.create(store=other_store, seller=user, total=Decimal("50.00"))
    client = authenticated_client(user)

    response = client.get(
        "/api/reports/dashboard/",
        {"store": "all", "date_from": "2026-06-01", "date_to": "2026-06-30"},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["store"]["id"] is None
    assert response.data["kpis"]["sales_count"] >= 2


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
