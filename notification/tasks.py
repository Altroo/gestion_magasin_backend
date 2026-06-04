import logging
from datetime import timedelta

from asgiref.sync import async_to_sync
from celery import shared_task
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model
from django.utils import timezone

from notification.models import Notification, NotificationPreference
from stock.models import StockBalance
from store.models import Role, StoreMembership

logger = logging.getLogger(__name__)
User = get_user_model()


def _broadcast(user_id: int, notification: Notification) -> None:
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    try:
        async_to_sync(channel_layer.group_send)(
            str(user_id),
            {
                "type": "receive_group_message",
                "message": {
                    "type": "NOTIFICATION",
                    "id": notification.pk,
                    "title": notification.title,
                    "message": notification.message,
                    "notification_type": notification.notification_type,
                    "object_id": notification.object_id,
                    "store": notification.store_id,
                    "product": notification.product_id,
                    "is_read": notification.is_read,
                    "date_created": notification.date_created.isoformat(),
                },
            },
        )
    except Exception as exc:
        logger.warning("WebSocket broadcast failed for user %s: %s", user_id, exc)


def _recipients(balance: StockBalance):
    member_ids = StoreMembership.objects.filter(
        store=balance.store,
        is_active=True,
        role__code__in=[Role.Codes.DIRECTION, Role.Codes.RESPONSABLE],
        user__is_active=True,
    ).values_list("user_id", flat=True)
    staff_ids = User.objects.filter(is_staff=True, is_active=True).values_list("id", flat=True)
    return User.objects.filter(id__in=set(member_ids).union(set(staff_ids))).distinct()


def _create_and_broadcast(user, balance: StockBalance) -> Notification:
    notification = Notification.objects.create(
        user=user,
        store=balance.store,
        product=balance.product,
        title=f"Stock minimum atteint - {balance.product.name}",
        message=(
            f"Le stock de {balance.product.name} au magasin {balance.store.name} "
            f"est à {balance.quantity} (minimum {balance.effective_min_stock})."
        ),
        notification_type=Notification.Types.LOW_STOCK,
        object_id=balance.product_id,
    )
    _broadcast(user.pk, notification)
    return notification


@shared_task(name="notification.notify_low_stock_if_needed")
def notify_low_stock_if_needed(balance_id: int) -> None:
    try:
        balance = StockBalance.objects.select_related("store", "product").get(pk=balance_id)
    except StockBalance.DoesNotExist:
        return

    if not balance.is_low_stock:
        if balance.low_stock_notified_at:
            balance.low_stock_notified_at = None
            balance.save(update_fields=["low_stock_notified_at", "date_updated"])
        return

    now = timezone.now()
    for user in _recipients(balance):
        preference, _ = NotificationPreference.objects.get_or_create(user=user)
        if not preference.notify_low_stock:
            continue
        repeat_after = now - timedelta(hours=preference.low_stock_repeat_hours)
        already_sent = Notification.objects.filter(
            user=user,
            store=balance.store,
            product=balance.product,
            notification_type=Notification.Types.LOW_STOCK,
            date_created__gte=repeat_after,
        ).exists()
        if not already_sent:
            _create_and_broadcast(user, balance)

    balance.low_stock_notified_at = now
    balance.save(update_fields=["low_stock_notified_at", "date_updated"])


@shared_task(name="notification.check_low_stock_notifications")
def check_low_stock_notifications() -> None:
    for balance in StockBalance.objects.select_related("store", "product").iterator():
        if balance.is_low_stock:
            notify_low_stock_if_needed(balance.pk)

