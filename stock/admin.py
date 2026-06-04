from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

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


@admin.register(StockBalance)
class StockBalanceAdmin(SimpleHistoryAdmin):
    list_display = ("store", "product", "quantity", "min_stock", "average_cost")
    list_filter = ("store", "product__category")
    search_fields = ("product__name", "product__reference", "product__barcode", "store__name")


@admin.register(StockMovement)
class StockMovementAdmin(SimpleHistoryAdmin):
    list_display = ("date_created", "store", "product", "movement_type", "quantity", "balance_after")
    list_filter = ("store", "movement_type", "date_created")
    search_fields = ("product__name", "product__reference", "note")
    readonly_fields = ("date_created",)


class PurchaseLineInline(admin.TabularInline):
    model = PurchaseLine
    extra = 0
    readonly_fields = ("total",)


@admin.register(Purchase)
class PurchaseAdmin(SimpleHistoryAdmin):
    list_display = ("id", "store", "supplier_name", "reference", "purchase_date", "status", "subtotal")
    list_filter = ("store", "status", "purchase_date")
    search_fields = ("supplier_name", "reference", "note", "lines__product__name")
    readonly_fields = ("subtotal", "created_by", "received_by", "received_at", "date_created", "date_updated")
    inlines = [PurchaseLineInline]


class InventoryLineInline(admin.TabularInline):
    model = InventoryLine
    extra = 0
    readonly_fields = ("difference",)


@admin.register(InventorySession)
class InventorySessionAdmin(SimpleHistoryAdmin):
    list_display = ("code", "title", "store", "inventory_date", "status")
    list_filter = ("store", "status", "inventory_date")
    search_fields = ("code", "title", "note", "lines__product__name")
    readonly_fields = ("created_by", "validated_by", "validated_at", "date_created", "date_updated")
    inlines = [InventoryLineInline]


class StockTransferLineInline(admin.TabularInline):
    model = StockTransferLine
    extra = 0


@admin.register(StockTransfer)
class StockTransferAdmin(SimpleHistoryAdmin):
    list_display = ("id", "source_store", "target_store", "reference", "transfer_date", "status")
    list_filter = ("source_store", "target_store", "status", "transfer_date")
    search_fields = ("reference", "note", "lines__product__name", "lines__product__reference")
    readonly_fields = ("created_by", "validated_by", "validated_at", "date_created", "date_updated")
    inlines = [StockTransferLineInline]
