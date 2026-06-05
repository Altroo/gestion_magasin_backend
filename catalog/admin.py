from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from catalog.models import Category, Product, ProductImportBatch, ProductUnit


@admin.register(Category)
class CategoryAdmin(SimpleHistoryAdmin):
    list_display = ("code", "name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")


@admin.register(ProductUnit)
class ProductUnitAdmin(SimpleHistoryAdmin):
    list_display = ("code", "name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")


@admin.register(Product)
class ProductAdmin(SimpleHistoryAdmin):
    list_display = (
        "reference",
        "barcode",
        "name",
        "category",
        "unit",
        "counter_price",
        "default_stock_alert",
        "is_active",
    )
    list_filter = ("category", "unit", "is_active", "compliance_required")
    search_fields = ("reference", "barcode", "name")


@admin.register(ProductImportBatch)
class ProductImportBatchAdmin(SimpleHistoryAdmin):
    list_display = ("file_name", "store", "imported_count", "skipped_count", "date_created")
    list_filter = ("store",)
    search_fields = ("file_name",)
    readonly_fields = ("date_created",)
