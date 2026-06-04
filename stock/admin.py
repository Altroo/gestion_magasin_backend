from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from stock.models import StockBalance, StockMovement


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
