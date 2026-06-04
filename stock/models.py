from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords


class StockBalance(models.Model):
    store = models.ForeignKey(
        "store.Store",
        on_delete=models.CASCADE,
        related_name="stock_balances",
        verbose_name=_("Magasin"),
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.CASCADE,
        related_name="stock_balances",
        verbose_name=_("Article"),
    )
    quantity = models.DecimalField(
        max_digits=12, decimal_places=3, default=0, verbose_name=_("Quantité")
    )
    min_stock = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        null=True,
        blank=True,
        verbose_name=_("Stock minimum"),
    )
    average_cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name=_("Coût moyen"),
    )
    low_stock_notified_at = models.DateTimeField(null=True, blank=True)
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Solde stock")
        verbose_name_plural = _("Soldes stock")
        ordering = ("store__name", "product__name")
        constraints = [
            models.UniqueConstraint(
                fields=("store", "product"), name="unique_store_product_stock"
            )
        ]

    def __str__(self) -> str:
        return f"{self.store} - {self.product}: {self.quantity}"

    @property
    def effective_min_stock(self) -> Decimal:
        if self.min_stock is not None:
            return self.min_stock
        return self.product.default_stock_alert or Decimal("0")

    @property
    def is_low_stock(self) -> bool:
        return self.effective_min_stock > 0 and self.quantity <= self.effective_min_stock


class StockMovement(models.Model):
    class Types(models.TextChoices):
        SALE = "sale", _("Vente")
        RETURN = "return", _("Retour")
        PURCHASE = "purchase", _("Achat")
        ADJUSTMENT = "adjustment", _("Ajustement")
        INVENTORY = "inventory", _("Inventaire")
        IMPORT = "import", _("Import")

    store = models.ForeignKey(
        "store.Store",
        on_delete=models.PROTECT,
        related_name="stock_movements",
        verbose_name=_("Magasin"),
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="stock_movements",
        verbose_name=_("Article"),
    )
    movement_type = models.CharField(
        max_length=30, choices=Types.choices, verbose_name=_("Type")
    )
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        verbose_name=_("Quantité"),
        help_text=_("Positive pour entrée, négative pour sortie."),
    )
    balance_after = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=0,
        verbose_name=_("Solde après"),
    )
    unit_cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name=_("Coût unitaire"),
    )
    source_type = models.CharField(max_length=40, blank=True, default="")
    source_id = models.PositiveIntegerField(null=True, blank=True)
    note = models.TextField(blank=True, default="", verbose_name=_("Note"))
    created_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_movements",
        verbose_name=_("Créé par"),
    )
    date_created = models.DateTimeField(auto_now_add=True, db_index=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Mouvement stock")
        verbose_name_plural = _("Mouvements stock")
        ordering = ("-date_created",)

    def __str__(self) -> str:
        return f"{self.movement_type} {self.product} ({self.quantity})"

