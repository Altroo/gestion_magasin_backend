from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from notification.models import Notification, NotificationPreference


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(SimpleHistoryAdmin):
    list_display = ("user", "notify_low_stock", "low_stock_repeat_hours", "browser_notifications")
    search_fields = ("user__email",)
    readonly_fields = ("date_created", "date_updated")


@admin.register(Notification)
class NotificationAdmin(SimpleHistoryAdmin):
    list_display = ("user", "store", "product", "notification_type", "is_read", "date_created")
    list_filter = ("notification_type", "store", "is_read", "date_created")
    search_fields = ("user__email", "title", "message", "product__name", "store__name")
    readonly_fields = ("date_created",)
