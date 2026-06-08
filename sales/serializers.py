from decimal import Decimal

from rest_framework import serializers

from catalog.models import Product
from sales.models import (
    Customer,
    PaymentMode,
    Promotion,
    PromotionLine,
    Sale,
    SaleLine,
    SalePromotionLine,
)


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


class PromotionLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_reference = serializers.CharField(source="product.reference", read_only=True)
    product_barcode = serializers.CharField(source="product.barcode", read_only=True)

    class Meta:
        model = PromotionLine
        fields = [
            "id",
            "product",
            "product_name",
            "product_reference",
            "product_barcode",
            "quantity",
        ]


class PromotionSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source="store.name", read_only=True)
    created_by_email = serializers.CharField(source="created_by.email", read_only=True)
    lines = PromotionLineSerializer(many=True, read_only=True)

    class Meta:
        model = Promotion
        fields = [
            "id",
            "store",
            "store_name",
            "name",
            "selling_price",
            "status",
            "start_date",
            "end_date",
            "note",
            "created_by",
            "created_by_email",
            "date_created",
            "date_updated",
            "lines",
        ]
        read_only_fields = ["created_by", "date_created", "date_updated"]


class PromotionLineInputSerializer(serializers.Serializer):
    product = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)

    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError("La quantité doit être positive.")
        return value


class PromotionCreateSerializer(serializers.Serializer):
    store = serializers.IntegerField(required=False)
    store_id = serializers.IntegerField(required=False)
    stores = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        allow_empty=False,
    )
    name = serializers.CharField(max_length=160)
    selling_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    status = serializers.ChoiceField(
        choices=Promotion.Statuses.choices,
        default=Promotion.Statuses.ACTIVE,
    )
    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True)
    lines = PromotionLineInputSerializer(many=True)

    def validate_selling_price(self, value):
        if value <= 0:
            raise serializers.ValidationError("Le prix de vente doit être positif.")
        return value

    def validate_lines(self, value):
        if not value:
            raise serializers.ValidationError("La promotion doit contenir au moins un article.")
        product_ids = [item["product"] for item in value]
        if len(product_ids) != len(set(product_ids)):
            raise serializers.ValidationError("Un article ne peut figurer qu'une seule fois.")
        return value


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


class SalePromotionLineSerializer(serializers.ModelSerializer):
    promotion_name = serializers.CharField(source="promotion.name", read_only=True)

    class Meta:
        model = SalePromotionLine
        fields = [
            "id",
            "promotion",
            "promotion_name",
            "quantity",
            "unit_price",
            "total",
        ]
        read_only_fields = ["total"]


class SaleSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source="store.name", read_only=True)
    seller_email = serializers.CharField(source="seller.email", read_only=True)
    customer_name = serializers.CharField(source="customer.full_name", read_only=True)
    payment_mode_name = serializers.CharField(source="payment_mode.name", read_only=True)
    lines = SaleLineSerializer(many=True, read_only=True)
    promotion_lines = SalePromotionLineSerializer(many=True, read_only=True)

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
            "promotion_lines",
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


class SaleCreatePromotionLineSerializer(serializers.Serializer):
    promotion = serializers.IntegerField()
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
    lines = SaleCreateLineSerializer(many=True, required=False)
    promotion_lines = SaleCreatePromotionLineSerializer(many=True, required=False)

    def validate(self, attrs):
        if not attrs.get("lines") and not attrs.get("promotion_lines"):
            raise serializers.ValidationError(
                {"lines": "La vente doit contenir au moins une ligne."}
            )
        return attrs


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


def resolve_promotion(promotion_id: int) -> Promotion:
    try:
        return Promotion.objects.prefetch_related("lines", "lines__product").get(
            pk=promotion_id,
            status=Promotion.Statuses.ACTIVE,
        )
    except Promotion.DoesNotExist as exc:
        raise serializers.ValidationError({"promotion": ["Promotion active introuvable."]}) from exc
