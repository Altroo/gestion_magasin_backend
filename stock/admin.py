from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from gestion_magasin_backend.admin_history import register_history_admin
from stock.models import (
    InventoryLine,
    InventorySession,
    Purchase,
    PurchaseLine,
    StockAddRequest,
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


@admin.register(StockAddRequest)
class StockAddRequestAdmin(SimpleHistoryAdmin):
    list_display = ("id", "store", "product", "quantity", "unit_cost", "status", "requested_by", "reviewed_by")
    list_filter = ("store", "status", "date_created")
    search_fields = ("store__name", "product__name", "product__reference", "product__barcode", "note")
    readonly_fields = ("requested_by", "reviewed_by", "reviewed_at", "date_created", "date_updated")


class PurchaseLineInline(admin.TabularInline):
    model = PurchaseLine
    extra = 0
    readonly_fields = ("total",)


@admin.register(PurchaseLine)
class PurchaseLineAdmin(SimpleHistoryAdmin):
    list_display = ("purchase", "product", "quantity", "unit_cost", "total")
    list_filter = ("purchase__store", "product__category")
    search_fields = ("purchase__reference", "product__name", "product__reference", "product__barcode")
    readonly_fields = ("total",)


@admin.register(Purchase)
class PurchaseAdmin(SimpleHistoryAdmin):
    list_display = ("id", "store", "supplier_name", "reference", "purchase_date", "status", "subtotal", "invoice_file")
    list_filter = ("store", "status", "purchase_date")
    search_fields = ("supplier_name", "reference", "note", "lines__product__name")
    readonly_fields = ("subtotal", "created_by", "received_by", "received_at", "date_created", "date_updated")
    inlines = [PurchaseLineInline]


class InventoryLineInline(admin.TabularInline):
    model = InventoryLine
    extra = 0
    readonly_fields = ("difference",)


@admin.register(InventoryLine)
class InventoryLineAdmin(SimpleHistoryAdmin):
    list_display = ("session", "product", "expected_quantity", "counted_quantity", "difference")
    list_filter = ("session__store", "product__category")
    search_fields = ("session__code", "session__title", "product__name", "product__reference")
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


@admin.register(StockTransferLine)
class StockTransferLineAdmin(SimpleHistoryAdmin):
    list_display = ("transfer", "product", "quantity")
    list_filter = ("transfer__target_store", "product__category")
    search_fields = ("transfer__reference", "product__name", "product__reference", "product__barcode")


@admin.register(StockTransfer)
class StockTransferAdmin(SimpleHistoryAdmin):
    list_display = ("id", "target_store", "reference", "transfer_date", "status")
    list_filter = ("target_store", "status", "transfer_date")
    search_fields = ("reference", "note", "lines__product__name", "lines__product__reference")
    readonly_fields = ("created_by", "validated_by", "validated_at", "date_created", "date_updated")
    inlines = [StockTransferLineInline]


register_history_admin(
    StockBalance,
    display_fields=("id", "store", "product", "quantity", "min_stock", "average_cost"),
    list_filter=("store",),
    search_fields=("product__name", "product__reference", "product__barcode", "store__name"),
)
register_history_admin(
    StockMovement,
    display_fields=("id", "store", "product", "movement_type", "quantity", "balance_after"),
    list_filter=("store", "movement_type"),
    search_fields=("product__name", "product__reference", "note", "store__name"),
)
register_history_admin(
    StockAddRequest,
    display_fields=("id", "store", "product", "quantity", "unit_cost", "status", "requested_by", "reviewed_by"),
    list_filter=("store", "status"),
    search_fields=("store__name", "product__name", "product__reference", "product__barcode", "note"),
)
register_history_admin(
    Purchase,
    display_fields=("id", "store", "supplier_name", "reference", "purchase_date", "status", "subtotal", "invoice_file"),
    list_filter=("store", "status", "purchase_date"),
    search_fields=("supplier_name", "reference", "note"),
)
register_history_admin(
    PurchaseLine,
    display_fields=("id", "purchase", "product", "quantity", "unit_cost", "total"),
    list_filter=("purchase__store",),
    search_fields=("purchase__reference", "product__name", "product__reference", "product__barcode"),
)
register_history_admin(
    InventorySession,
    display_fields=("id", "code", "title", "store", "inventory_date", "status"),
    list_filter=("store", "status", "inventory_date"),
    search_fields=("code", "title", "note"),
)
register_history_admin(
    InventoryLine,
    display_fields=("id", "session", "product", "expected_quantity", "counted_quantity", "difference"),
    list_filter=("session__store",),
    search_fields=("session__code", "session__title", "product__name", "product__reference"),
)
register_history_admin(
    StockTransfer,
    display_fields=("id", "target_store", "reference", "transfer_date", "status"),
    list_filter=("target_store", "status", "transfer_date"),
    search_fields=("reference", "note"),
)
register_history_admin(
    StockTransferLine,
    display_fields=("id", "transfer", "product", "quantity"),
    list_filter=("transfer__target_store",),
    search_fields=("transfer__reference", "product__name", "product__reference", "product__barcode"),
)
