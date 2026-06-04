from rest_framework import serializers

from catalog.models import Category, Product, ProductImportBatch
from stock.models import StockBalance


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "code", "name", "is_active", "date_created", "date_updated"]
        read_only_fields = ["date_created", "date_updated"]


class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    available_stock = serializers.SerializerMethodField()
    min_stock = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "reference",
            "barcode",
            "name",
            "category",
            "category_name",
            "unit",
            "purchase_price",
            "wholesale_price",
            "detail_price",
            "counter_price",
            "default_stock_alert",
            "expiration_date",
            "shelf_life_days",
            "compliance_required",
            "is_active",
            "available_stock",
            "min_stock",
            "date_created",
            "date_updated",
        ]
        read_only_fields = ["date_created", "date_updated"]

    def get_available_stock(self, instance):
        store_id = self.context.get("store_id")
        if not store_id:
            return None
        balance = getattr(instance, "_selected_balance", None)
        if balance:
            return balance.quantity
        return (
            StockBalance.objects.filter(store_id=store_id, product=instance)
            .values_list("quantity", flat=True)
            .first()
        )

    def get_min_stock(self, instance):
        store_id = self.context.get("store_id")
        if not store_id:
            return instance.default_stock_alert
        balance = getattr(instance, "_selected_balance", None)
        if balance:
            return balance.effective_min_stock
        return (
            StockBalance.objects.filter(store_id=store_id, product=instance)
            .values_list("min_stock", flat=True)
            .first()
            or instance.default_stock_alert
        )


class ProductImportBatchSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source="store.name", read_only=True)
    imported_by_email = serializers.CharField(source="imported_by.email", read_only=True)

    class Meta:
        model = ProductImportBatch
        fields = [
            "id",
            "store",
            "store_name",
            "file_name",
            "imported_by",
            "imported_by_email",
            "imported_count",
            "skipped_count",
            "date_created",
        ]
        read_only_fields = [
            "id",
            "file_name",
            "imported_by",
            "imported_count",
            "skipped_count",
            "date_created",
        ]

