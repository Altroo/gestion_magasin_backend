from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords


class Role(models.Model):
    class Codes(models.TextChoices):
        DIRECTION = "direction", _("Direction")
        RESPONSABLE = "responsable", _("Responsable")
        VENDEUR = "vendeur", _("Vendeur")
        LECTURE = "lecture", _("Lecture")

    code = models.CharField(
        max_length=32,
        choices=Codes.choices,
        unique=True,
        verbose_name=_("Code"),
    )
    name = models.CharField(max_length=80, unique=True, verbose_name=_("Nom"))
    rank = models.PositiveSmallIntegerField(default=99, verbose_name=_("Priorité"))
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Rôle")
        verbose_name_plural = _("Rôles")
        ordering = ("rank", "name")

    def __str__(self) -> str:
        return self.name


class Store(models.Model):
    name = models.CharField(max_length=160, unique=True, verbose_name=_("Nom"))
    code = models.CharField(max_length=40, unique=True, verbose_name=_("Code"))
    address = models.CharField(
        max_length=255, blank=True, default="", verbose_name=_("Adresse")
    )
    phone = models.CharField(
        max_length=40, blank=True, default="", verbose_name=_("Téléphone")
    )
    is_active = models.BooleanField(default=True, db_index=True, verbose_name=_("Actif"))
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Magasin")
        verbose_name_plural = _("Magasins")
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class StoreMembership(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="store_memberships",
        verbose_name=_("Utilisateur"),
    )
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name=_("Magasin"),
    )
    role = models.ForeignKey(
        Role,
        on_delete=models.PROTECT,
        related_name="memberships",
        verbose_name=_("Rôle"),
    )
    is_active = models.BooleanField(default=True, db_index=True, verbose_name=_("Actif"))
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Permission magasin")
        verbose_name_plural = _("Permissions magasins")
        ordering = ("store__name", "user__email")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "store"), name="unique_store_membership"
            )
        ]

    def __str__(self) -> str:
        return f"{self.user} - {self.store} ({self.role})"

