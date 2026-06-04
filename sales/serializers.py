from decimal import Decimal

from rest_framework import serializers

from catalog.models import Product
from sales.models import Customer, PaymentMode, Sale, SaleLine


class CustomerSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source="store.name", read_only=True)

    class Meta:
        model = Customer
        fields = [
            "id",
            "store",
            "store_name",
            "full_name",
            "phone",
            "email",
            "credit_limit",
            "is_active",
            "date_created",
            "date_updated",
        ]
        read_only_fields = ["date_created", "date_updated"]


class PaymentModeSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentMode
        fields = ["id", "code", "name", "is_credit", "is_active"]


class SaleLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_reference = serializers.CharField(source="product.reference", read_only=True)
    product_barcode = serializers.CharField(source="product.barcode", read_only=True)

    class Meta:
        model = SaleLine
        fields = [
            "id",
            "product",
            "product_name",
            "product_reference",
            "product_barcode",
            "quantity",
            "unit_price",
            "unit_cost",
            "total",
        ]
        read_only_fields = ["unit_cost", "total"]


class SaleSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source="store.name", read_only=True)
    seller_email = serializers.CharField(source="seller.email", read_only=True)
    customer_name = serializers.CharField(source="customer.full_name", read_only=True)
    payment_mode_name = serializers.CharField(source="payment_mode.name", read_only=True)
    lines = SaleLineSerializer(many=True, read_only=True)

    class Meta:
        model = Sale
        fields = [
            "id",
            "store",
            "store_name",
            "seller",
            "seller_email",
            "customer",
            "customer_name",
            "payment_mode",
            "payment_mode_name",
            "status",
            "payment_status",
            "subtotal",
            "discount_amount",
            "total",
            "paid_amount",
            "change_amount",
            "idempotency_key",
            "offline_created_at",
            "note",
            "void_reason",
            "voided_by",
            "voided_at",
            "date_created",
            "date_updated",
            "lines",
        ]
        read_only_fields = [
            "seller",
            "status",
            "subtotal",
            "total",
            "change_amount",
            "voided_by",
            "voided_at",
            "date_created",
            "date_updated",
        ]


class SaleCreateLineSerializer(serializers.Serializer):
    product = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)

    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError("La quantité doit être positive.")
        return value


class SaleCreateSerializer(serializers.Serializer):
    store = serializers.IntegerField(required=False)
    store_id = serializers.IntegerField(required=False)
    customer = serializers.IntegerField(required=False, allow_null=True)
    payment_mode = serializers.IntegerField(required=False, allow_null=True)
    payment_mode_code = serializers.CharField(required=False, allow_blank=True)
    payment_status = serializers.ChoiceField(
        choices=Sale.PaymentStatuses.choices,
        default=Sale.PaymentStatuses.PAID,
    )
    discount_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0")
    )
    paid_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False
    )
    idempotency_key = serializers.CharField(required=False, allow_blank=True)
    offline_created_at = serializers.DateTimeField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True)
    lines = SaleCreateLineSerializer(many=True)

    def validate_lines(self, value):
        if not value:
            raise serializers.ValidationError("La vente doit contenir au moins une ligne.")
        return value


class SaleVoidSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)


class SaleDashboardSerializer(serializers.Serializer):
    sales_count = serializers.IntegerField()
    total_sales = serializers.DecimalField(max_digits=12, decimal_places=2)
    low_stock_count = serializers.IntegerField()
    products_count = serializers.IntegerField()


def resolve_product(product_id: int) -> Product:
    try:
        return Product.objects.get(pk=product_id, is_active=True)
    except Product.DoesNotExist as exc:
        raise serializers.ValidationError({"product": ["Article introuvable."]}) from exc

