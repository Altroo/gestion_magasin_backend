from django.conf import settings
from django.contrib import admin

from attendance.models import AttendanceImportBatch, AttendanceRecord, Employee
from catalog.models import Category, Product, ProductImportBatch, ProductUnit
from finance.models import Expense, ExpenseCategory
from notification.models import Notification, NotificationPreference
from sales.models import (
    Customer,
    CustomerCreditLedger,
    PaymentMode,
    Promotion,
    PromotionLine,
    Sale,
    SaleLine,
    SalePromotionLine,
)
from stock.models import (
    InventoryLine,
    InventorySession,
    Purchase,
    PurchaseLine,
    StockBalance,
    StockMovement,
    StockTransfer,
    StockTransferLine,
)
from store.models import Role, Store, StoreMembership


HISTORY_MODELS = (
    Role,
    Store,
    StoreMembership,
    Category,
    ProductUnit,
    Product,
    ProductImportBatch,
    StockBalance,
    StockMovement,
    StockTransfer,
    StockTransferLine,
    Purchase,
    PurchaseLine,
    InventorySession,
    InventoryLine,
    Customer,
    PaymentMode,
    Promotion,
    PromotionLine,
    Sale,
    SaleLine,
    SalePromotionLine,
    CustomerCreditLedger,
    Employee,
    AttendanceRecord,
    AttendanceImportBatch,
    ExpenseCategory,
    Expense,
    NotificationPreference,
    Notification,
)

LINE_MODELS = (
    StockTransferLine,
    PurchaseLine,
    InventoryLine,
    PromotionLine,
    SaleLine,
    SalePromotionLine,
)


def test_admin_view_site_uses_frontend_url():
    assert admin.site.site_url == (settings.FRONTEND_URL or "/")


def test_history_models_are_registered_in_admin():
    for model in HISTORY_MODELS:
        assert model.history.model in admin.site._registry


def test_operational_line_models_are_registered_in_admin():
    for model in LINE_MODELS:
        assert model in admin.site._registry
