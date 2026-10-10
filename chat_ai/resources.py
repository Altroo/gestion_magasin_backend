"""Bindings to verified native queries, serializers and actions."""
from dataclasses import dataclass
from catalog.models import Product
from catalog.serializers import ProductSerializer
from catalog.views import _product_queryset, ProductDetailEditDeleteView
from stock.models import StockBalance, StockAddRequest, StockTransfer, Purchase, InventorySession
from stock.views import _stock_balance_base_queryset, _stock_add_request_queryset, _stock_transfer_queryset, _purchase_queryset, _inventory_queryset
from sales.models import Sale, Customer, Promotion
from sales.serializers import SaleSerializer, CustomerSerializer
from sales.views import _sale_queryset, _customer_queryset, _promotion_queryset, SaleDetailEditDeleteView, CustomerDetailEditDeleteView
from finance.models import Expense
from finance.serializers import ExpenseSerializer
from finance.views import _expense_queryset, ExpenseDetailEditDeleteView
from attendance.models import Employee, AttendanceRecord
from attendance.serializers import AttendanceRecordSerializer
from attendance.views import _employee_queryset, _attendance_queryset, AttendanceRecordDetailEditDeleteView
from account.models import CustomUser
from store.models import Store

@dataclass(frozen=True)
class Resource:
    model: object
    queryset: object = None
    scope_field: str | None = 'store_id'
    date_field: str | None = None
    serializer: object = None
    view: object = None
    editable: tuple = ()
    deletable: bool = False

RESOURCES = {
    'product': Resource(Product, _product_queryset, None, None, ProductSerializer, ProductDetailEditDeleteView, ('name', 'reference', 'barcode'), True),
    'stock': Resource(StockBalance, _stock_balance_base_queryset),
    'stock_request': Resource(StockAddRequest, _stock_add_request_queryset, 'store_id', 'date_created__date'),
    'sale': Resource(Sale, _sale_queryset, 'store_id', 'date_created__date', SaleSerializer, SaleDetailEditDeleteView, ('note',)),
    'customer': Resource(Customer, _customer_queryset, 'store_id', None, CustomerSerializer, CustomerDetailEditDeleteView, ('full_name', 'phone', 'email'), True),
    'expense': Resource(Expense, _expense_queryset, 'store_id', 'expense_date', ExpenseSerializer, ExpenseDetailEditDeleteView, ('label', 'note'), True),
    'purchase': Resource(Purchase, _purchase_queryset, 'store_id', 'purchase_date'),
    'transfer': Resource(StockTransfer, _stock_transfer_queryset, 'target_store_id', 'transfer_date'),
    'inventory': Resource(InventorySession, _inventory_queryset, 'store_id', 'inventory_date'),
    'promotion': Resource(Promotion, _promotion_queryset, 'store_id', 'date_created__date'),
    'attendance': Resource(AttendanceRecord, _attendance_queryset, 'store_id', 'date', AttendanceRecordSerializer, AttendanceRecordDetailEditDeleteView, ('observations', 'responsible'), True),
    'employee': Resource(Employee, _employee_queryset),
    'store': Resource(Store, None, 'pk'),
    'user': Resource(CustomUser, None, None),
}
