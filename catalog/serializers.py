from decimal import Decimal

from django.db import transaction
from rest_framework import serializers

from catalog.models import (
    Category,
    Product,
    ProductImportBatch,
    ProductStockTrackingItem,
    ProductUnit,
)
from stock.models import StockBalance


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "code", "name", "is_active", "date_created", "date_updated"]
        read_only_fields = ["date_created", "date_updated"]


class ProductUnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductUnit
        fields = ["id", "code", "name", "is_active", "date_created", "date_updated"]
        read_only_fields = ["date_created", "date_updated"]


class ProductStockTrackingItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductStockTrackingItem
        fields = [
            "id",
            "default_stock_alert",
            "expiration_date",
            "requires_expiration_date",
            "shelf_life_days",
            "position",
        ]
        read_only_fields = ["id", "position"]
        extra_kwargs = {"default_stock_alert": {"required": True}}

    def validate(self, attrs):
        if attrs.get("requires_expiration_date") and not attrs.get(
            "expiration_date"
        ):
            raise serializers.ValidationError(
                {"expiration_date": ["Ce champ est obligatoire."]}
            )
        return attrs


class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    unit_name = serializers.CharField(source="unit.name", read_only=True)
    available_stock = serializers.SerializerMethodField()
    min_stock = serializers.SerializerMethodField()
    stock_tracking_items = ProductStockTrackingItemSerializer(
        many=True, required=False
    )

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
            "unit_name",
            "purchase_price",
            "wholesale_price",
            "detail_price",
            "counter_price",
            "default_stock_alert",
            "expiration_date",
            "requires_expiration_date",
            "shelf_life_days",
            "stock_tracking_items",
            "is_active",
            "available_stock",
            "min_stock",
            "date_created",
            "date_updated",
        ]
        read_only_fields = ["date_created", "date_updated"]

    def validate(self, attrs):
        barcode = attrs.get("barcode", getattr(self.instance, "barcode", None))
        if not barcode or not str(barcode).strip():
            raise serializers.ValidationError(
                {"barcode": ["Ce champ est obligatoire."]}
            )
        attrs["barcode"] = str(barcode).strip()
        stock_tracking_items = attrs.get("stock_tracking_items")
        if stock_tracking_items is not None and not stock_tracking_items:
            raise serializers.ValidationError(
                {"stock_tracking_items": ["Ajoutez au moins une ligne."]}
            )
        requires_expiration_date = attrs.get(
            "requires_expiration_date",
            getattr(self.instance, "requires_expiration_date", False),
        )
        expiration_date = attrs.get(
            "expiration_date",
            getattr(self.instance, "expiration_date", None),
        )
        if (
            stock_tracking_items is None
            and requires_expiration_date
            and not expiration_date
        ):
            raise serializers.ValidationError(
                {"expiration_date": ["Ce champ est obligatoire."]}
            )
        return attrs

    @staticmethod
    def _legacy_values(item):
        return {
            "default_stock_alert": item["default_stock_alert"],
            "expiration_date": item.get("expiration_date"),
            "requires_expiration_date": item.get(
                "requires_expiration_date", False
            ),
            "shelf_life_days": item.get("shelf_life_days"),
        }

    @staticmethod
    def _item_values(product):
        return {
            "default_stock_alert": product.default_stock_alert,
            "expiration_date": product.expiration_date,
            "requires_expiration_date": product.requires_expiration_date,
            "shelf_life_days": product.shelf_life_days,
        }

    @staticmethod
    def _replace_stock_tracking_items(product, items):
        product.stock_tracking_items.all().delete()
        for position, item in enumerate(items):
            ProductStockTrackingItem.objects.create(
                product=product,
                position=position,
                **item,
            )
        getattr(product, "_prefetched_objects_cache", {}).pop(
            "stock_tracking_items", None
        )

    @transaction.atomic
    def create(self, validated_data):
        stock_tracking_items = validated_data.pop("stock_tracking_items", None)
        if stock_tracking_items:
            validated_data.update(self._legacy_values(stock_tracking_items[0]))
        product = super().create(validated_data)
        self._replace_stock_tracking_items(
            product,
            stock_tracking_items or [self._item_values(product)],
        )
        return product

    @transaction.atomic
    def update(self, instance, validated_data):
        stock_tracking_items = validated_data.pop("stock_tracking_items", None)
        updates_legacy_stock_values = any(
            field in validated_data
            for field in (
                "default_stock_alert",
                "expiration_date",
                "requires_expiration_date",
                "shelf_life_days",
            )
        )
        if stock_tracking_items:
            validated_data.update(self._legacy_values(stock_tracking_items[0]))
        product = super().update(instance, validated_data)
        if stock_tracking_items is not None:
            self._replace_stock_tracking_items(product, stock_tracking_items)
        elif updates_legacy_stock_values:
            product.stock_tracking_items.update_or_create(
                position=0,
                defaults=self._item_values(product),
            )
            getattr(product, "_prefetched_objects_cache", {}).pop(
                "stock_tracking_items", None
            )
        elif not product.stock_tracking_items.exists():
            self._replace_stock_tracking_items(product, [self._item_values(product)])
        return product

    def get_available_stock(self, instance):
        store_id = self.context.get("store_id")
        if not store_id:
            return None
        balance = getattr(instance, "_selected_balance", None)
        if balance:
            return balance.quantity
        quantity = (
            StockBalance.objects.filter(store_id=store_id, product=instance)
            .values_list("quantity", flat=True)
            .first()
        )
        return quantity if quantity is not None else Decimal("0")

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
