from rest_framework import serializers

from notification.models import Notification, NotificationPreference


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = [
            "id",
            "notify_low_stock",
            "notify_stock_add_requests",
            "low_stock_repeat_hours",
            "browser_notifications",
            "date_created",
            "date_updated",
        ]
        read_only_fields = ["id", "date_created", "date_updated"]


class NotificationSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source="store.name", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "title",
            "message",
            "notification_type",
            "object_id",
            "store",
            "store_name",
            "product",
            "product_name",
            "is_read",
            "date_created",
        ]
        read_only_fields = [
            "id",
            "title",
            "message",
            "notification_type",
            "object_id",
            "store",
            "store_name",
            "product",
            "product_name",
            "date_created",
        ]
