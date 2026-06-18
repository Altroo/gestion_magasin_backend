from rest_framework import serializers

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


class StockBalanceSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_reference = serializers.CharField(
        source="product.reference", read_only=True
    )
    product_barcode = serializers.CharField(source="product.barcode", read_only=True)
    product_purchase_price = serializers.DecimalField(
        source="product.purchase_price",
        max_digits=12,
        decimal_places=2,
        read_only=True,
    )
    category_name = serializers.CharField(
        source="product.category.name", read_only=True
    )
    unit_name = serializers.CharField(source="product.unit.name", read_only=True)
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
            "product_purchase_price",
            "category_name",
            "unit_name",
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
    product_reference = serializers.CharField(
        source="product.reference", read_only=True
    )
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
    unit_cost = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False
    )
    note = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    allow_negative = serializers.BooleanField(required=False, default=False)


class StockThresholdSerializer(serializers.Serializer):
    min_stock = serializers.DecimalField(max_digits=12, decimal_places=3)


class StockAddRequestSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_reference = serializers.CharField(source="product.reference", read_only=True)
    product_barcode = serializers.CharField(source="product.barcode", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)
    requested_by_email = serializers.CharField(source="requested_by.email", read_only=True)
    reviewed_by_email = serializers.CharField(source="reviewed_by.email", read_only=True)

    class Meta:
        model = StockAddRequest
        fields = [
            "id",
            "store",
            "store_name",
            "product",
            "product_name",
            "product_reference",
            "product_barcode",
            "quantity",
            "unit_cost",
            "status",
            "note",
            "requested_by",
            "requested_by_email",
            "reviewed_by",
            "reviewed_by_email",
            "reviewed_at",
            "rejection_reason",
            "date_created",
            "date_updated",
        ]
        read_only_fields = [
            "store",
            "store_name",
            "status",
            "requested_by",
            "requested_by_email",
            "reviewed_by",
            "reviewed_by_email",
            "reviewed_at",
            "rejection_reason",
            "date_created",
            "date_updated",
        ]

    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError("La quantité doit être positive.")
        return value

    def validate_unit_cost(self, value):
        if value < 0:
            raise serializers.ValidationError("Le coût doit être positif.")
        return value


class StockAddRequestDecisionSerializer(serializers.Serializer):
    rejection_reason = serializers.CharField(required=False, allow_blank=True)


class StockTransferLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_reference = serializers.CharField(
        source="product.reference", read_only=True
    )
    product_barcode = serializers.CharField(source="product.barcode", read_only=True)

    class Meta:
        model = StockTransferLine
        fields = [
            "id",
            "product",
            "product_name",
            "product_reference",
            "product_barcode",
            "quantity",
        ]


class StockTransferSerializer(serializers.ModelSerializer):
    target_store_name = serializers.CharField(
        source="target_store.name", read_only=True
    )
    created_by_email = serializers.CharField(source="created_by.email", read_only=True)
    validated_by_email = serializers.CharField(
        source="validated_by.email", read_only=True
    )
    lines = StockTransferLineSerializer(many=True, read_only=True)

    class Meta:
        model = StockTransfer
        fields = [
            "id",
            "target_store",
            "target_store_name",
            "reference",
            "transfer_date",
            "status",
            "note",
            "created_by",
            "created_by_email",
            "validated_by",
            "validated_by_email",
            "validated_at",
            "date_created",
            "date_updated",
            "lines",
        ]
        read_only_fields = [
            "created_by",
            "validated_by",
            "validated_at",
            "date_created",
            "date_updated",
        ]


class StockTransferLineInputSerializer(serializers.Serializer):
    product = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)

    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError("La quantité doit être positive.")
        return value


class StockTransferCreateSerializer(serializers.Serializer):
    target_store = serializers.IntegerField(required=False)
    target_store_id = serializers.IntegerField(required=False)
    reference = serializers.CharField(required=False, allow_blank=True)
    transfer_date = serializers.DateField(required=False)
    status = serializers.ChoiceField(
        choices=StockTransfer.Statuses.choices,
        default=StockTransfer.Statuses.DRAFT,
    )
    note = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    lines = StockTransferLineInputSerializer(many=True)

    def validate(self, attrs):
        attrs["target_store"] = attrs.get("target_store") or attrs.get(
            "target_store_id"
        )
        if not attrs.get("target_store"):
            raise serializers.ValidationError(
                {"target_store": "Magasin destination requis."}
            )
        return attrs

    def validate_lines(self, value):
        if not value:
            raise serializers.ValidationError(
                "Le transfert doit contenir au moins une ligne."
            )
        product_ids = [item["product"] for item in value]
        if len(product_ids) != len(set(product_ids)):
            raise serializers.ValidationError(
                "Un article ne peut figurer qu'une seule fois."
            )
        return value


class PurchaseLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_reference = serializers.CharField(
        source="product.reference", read_only=True
    )
    product_barcode = serializers.CharField(source="product.barcode", read_only=True)

    class Meta:
        model = PurchaseLine
        fields = [
            "id",
            "product",
            "product_name",
            "product_reference",
            "product_barcode",
            "quantity",
            "unit_cost",
            "total",
        ]
        read_only_fields = ["total"]


class PurchaseSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source="store.name", read_only=True)
    created_by_email = serializers.CharField(source="created_by.email", read_only=True)
    received_by_email = serializers.CharField(
        source="received_by.email", read_only=True
    )
    lines = PurchaseLineSerializer(many=True, read_only=True)
    invoice_file_url = serializers.SerializerMethodField()

    def get_invoice_file_url(self, obj):
        if not obj.invoice_file:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.invoice_file.url)
        return obj.invoice_file.url

    class Meta:
        model = Purchase
        fields = [
            "id",
            "store",
            "store_name",
            "supplier_name",
            "reference",
            "purchase_date",
            "status",
            "subtotal",
            "invoice_file",
            "invoice_file_url",
            "note",
            "created_by",
            "created_by_email",
            "received_by",
            "received_by_email",
            "received_at",
            "date_created",
            "date_updated",
            "lines",
        ]
        read_only_fields = [
            "subtotal",
            "created_by",
            "received_by",
            "received_at",
            "date_created",
            "date_updated",
            "invoice_file_url",
        ]


class PurchaseLineInputSerializer(serializers.Serializer):
    product = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    unit_cost = serializers.DecimalField(max_digits=12, decimal_places=2)

    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError("La quantité doit être positive.")
        return value

    def validate_unit_cost(self, value):
        if value < 0:
            raise serializers.ValidationError("Le coût doit être positif.")
        return value


class PurchaseCreateSerializer(serializers.Serializer):
    store = serializers.IntegerField(required=False)
    store_id = serializers.IntegerField(required=False)
    supplier_name = serializers.CharField(required=False, allow_blank=True)
    reference = serializers.CharField(required=False, allow_blank=True)
    purchase_date = serializers.DateField(required=False)
    status = serializers.ChoiceField(
        choices=Purchase.Statuses.choices, default=Purchase.Statuses.DRAFT
    )
    invoice_file = serializers.FileField(required=False, allow_null=True)
    note = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    lines = PurchaseLineInputSerializer(many=True)

    def validate_lines(self, value):
        if not value:
            raise serializers.ValidationError(
                "L'achat doit contenir au moins une ligne."
            )
        return value


class InventoryLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_reference = serializers.CharField(
        source="product.reference", read_only=True
    )
    product_barcode = serializers.CharField(source="product.barcode", read_only=True)

    class Meta:
        model = InventoryLine
        fields = [
            "id",
            "product",
            "product_name",
            "product_reference",
            "product_barcode",
            "expected_quantity",
            "counted_quantity",
            "difference",
            "note",
        ]
        read_only_fields = ["difference"]


class InventorySessionSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source="store.name", read_only=True)
    created_by_email = serializers.CharField(source="created_by.email", read_only=True)
    validated_by_email = serializers.CharField(
        source="validated_by.email", read_only=True
    )
    lines = InventoryLineSerializer(many=True, read_only=True)

    class Meta:
        model = InventorySession
        fields = [
            "id",
            "store",
            "store_name",
            "code",
            "title",
            "inventory_date",
            "status",
            "note",
            "created_by",
            "created_by_email",
            "validated_by",
            "validated_by_email",
            "validated_at",
            "date_created",
            "date_updated",
            "lines",
        ]
        read_only_fields = [
            "created_by",
            "validated_by",
            "validated_at",
            "date_created",
            "date_updated",
        ]


class InventoryLineInputSerializer(serializers.Serializer):
    product = serializers.IntegerField()
    expected_quantity = serializers.DecimalField(
        max_digits=12, decimal_places=3, required=False
    )
    counted_quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    note = serializers.CharField(max_length=2000, required=False, allow_blank=True)

    def validate_counted_quantity(self, value):
        if value < 0:
            raise serializers.ValidationError("La quantité comptée doit être positive.")
        return value


class InventorySessionCreateSerializer(serializers.Serializer):
    store = serializers.IntegerField(required=False)
    store_id = serializers.IntegerField(required=False)
    code = serializers.CharField(max_length=80)
    title = serializers.CharField(max_length=160)
    inventory_date = serializers.DateField(required=False)
    status = serializers.ChoiceField(
        choices=InventorySession.Statuses.choices,
        default=InventorySession.Statuses.DRAFT,
    )
    note = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    lines = InventoryLineInputSerializer(many=True)

    def validate_lines(self, value):
        if not value:
            raise serializers.ValidationError(
                "L'inventaire doit contenir au moins une ligne."
            )
        return value
