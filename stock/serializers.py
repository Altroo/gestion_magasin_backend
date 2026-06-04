from rest_framework import serializers

from stock.models import StockBalance, StockMovement


class StockBalanceSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_reference = serializers.CharField(source="product.reference", read_only=True)
    product_barcode = serializers.CharField(source="product.barcode", read_only=True)
    category_name = serializers.CharField(source="product.category.name", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)
    effective_min_stock = serializers.DecimalField(
        max_digits=12, decimal_places=3, read_only=True
    )
    is_low_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = StockBalance
        fields = [
            "id",
            "store",
            "store_name",
            "product",
            "product_name",
            "product_reference",
            "product_barcode",
            "category_name",
            "quantity",
            "min_stock",
            "effective_min_stock",
            "is_low_stock",
            "average_cost",
            "low_stock_notified_at",
            "date_created",
            "date_updated",
        ]
        read_only_fields = ["date_created", "date_updated", "low_stock_notified_at"]


class StockMovementSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_reference = serializers.CharField(source="product.reference", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)
    created_by_email = serializers.CharField(source="created_by.email", read_only=True)

    class Meta:
        model = StockMovement
        fields = [
            "id",
            "store",
            "store_name",
            "product",
            "product_name",
            "product_reference",
            "movement_type",
            "quantity",
            "balance_after",
            "unit_cost",
            "source_type",
            "source_id",
            "note",
            "created_by",
            "created_by_email",
            "date_created",
        ]
        read_only_fields = ["created_by", "balance_after", "date_created"]


class StockAdjustmentSerializer(serializers.Serializer):
    product = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    movement_type = serializers.ChoiceField(
        choices=[
            StockMovement.Types.PURCHASE,
            StockMovement.Types.ADJUSTMENT,
            StockMovement.Types.INVENTORY,
            StockMovement.Types.IMPORT,
            StockMovement.Types.RETURN,
        ],
        default=StockMovement.Types.ADJUSTMENT,
    )
    unit_cost = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    note = serializers.CharField(required=False, allow_blank=True)
    allow_negative = serializers.BooleanField(required=False, default=False)


class StockThresholdSerializer(serializers.Serializer):
    min_stock = serializers.DecimalField(max_digits=12, decimal_places=3)

