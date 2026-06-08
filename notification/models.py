from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords


class NotificationPreference(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preference",
        verbose_name=_("Utilisateur"),
    )
    notify_low_stock = models.BooleanField(
        default=True,
        verbose_name=_("Notifier le stock minimum"),
    )
    low_stock_repeat_hours = models.PositiveIntegerField(
        default=24,
        verbose_name=_("Répéter l'alerte stock après X heures"),
    )
    browser_notifications = models.BooleanField(
        default=True,
        verbose_name=_("Notifications navigateur"),
    )
    date_created = models.DateTimeField(auto_now_add=True, verbose_name=_("Date création"))
    date_updated = models.DateTimeField(auto_now=True, verbose_name=_("Date modification"))
    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Préférence notification")
        verbose_name_plural = _("Préférences notifications")

    def __str__(self) -> str:
        return f"Notifications - {self.user.email}"


class Notification(models.Model):
    class Types(models.TextChoices):
        LOW_STOCK = "low_stock", _("Stock minimum atteint")
        STOCK_ADD_REQUEST = "stock_add_request", _("Demande ajout stock")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name=_("Utilisateur"),
    )
    store = models.ForeignKey(
        "store.Store",
        on_delete=models.CASCADE,
        related_name="notifications",
        null=True,
        blank=True,
        verbose_name=_("Magasin"),
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.CASCADE,
        related_name="notifications",
        null=True,
        blank=True,
        verbose_name=_("Article"),
    )
    title = models.CharField(max_length=255, verbose_name=_("Titre"))
    message = models.TextField(verbose_name=_("Message"))
    notification_type = models.CharField(
        max_length=30,
        choices=Types.choices,
        verbose_name=_("Type"),
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    is_read = models.BooleanField(default=False, verbose_name=_("Lu"))
    date_created = models.DateTimeField(auto_now_add=True, db_index=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Notification")
        verbose_name_plural = _("Notifications")
        ordering = ("-date_created",)

    def __str__(self) -> str:
        return f"{self.title} - {self.user.email}"
