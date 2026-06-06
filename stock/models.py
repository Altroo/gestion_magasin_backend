from decimal import Decimal

from django.db import models
from django.utils import timezone
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
        TRANSFER_OUT = "transfer_out", _("Transfert sortant")
        TRANSFER_IN = "transfer_in", _("Transfert entrant")

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


class StockTransfer(models.Model):
    class Statuses(models.TextChoices):
        DRAFT = "draft", _("Brouillon")
        VALIDATED = "validated", _("Validé")
        CANCELLED = "cancelled", _("Annulé")

    target_store = models.ForeignKey(
        "store.Store",
        on_delete=models.PROTECT,
        related_name="stock_transfers_received",
        verbose_name=_("Magasin destination"),
    )
    reference = models.CharField(
        max_length=80,
        blank=True,
        default="",
        db_index=True,
        verbose_name=_("Référence"),
    )
    transfer_date = models.DateField(
        default=timezone.localdate,
        db_index=True,
        verbose_name=_("Date transfert"),
    )
    status = models.CharField(
        max_length=20,
        choices=Statuses.choices,
        default=Statuses.DRAFT,
        db_index=True,
        verbose_name=_("Statut"),
    )
    note = models.TextField(blank=True, default="", verbose_name=_("Note"))
    created_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_transfers_created",
        verbose_name=_("Créé par"),
    )
    validated_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_transfers_validated",
        verbose_name=_("Validé par"),
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Transfert stock")
        verbose_name_plural = _("Transferts stock")
        ordering = ("-transfer_date", "-id")

    def __str__(self) -> str:
        return f"Transfert #{self.pk} vers {self.target_store}"


class StockTransferLine(models.Model):
    transfer = models.ForeignKey(
        StockTransfer,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name=_("Transfert"),
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="stock_transfer_lines",
        verbose_name=_("Article"),
    )
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        verbose_name=_("Quantité"),
    )
    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Ligne transfert stock")
        verbose_name_plural = _("Lignes transferts stock")
        constraints = [
            models.UniqueConstraint(
                fields=("transfer", "product"),
                name="unique_stock_transfer_product",
            )
        ]

    def __str__(self) -> str:
        return f"{self.product} x {self.quantity}"


class Purchase(models.Model):
    class Statuses(models.TextChoices):
        DRAFT = "draft", _("Brouillon")
        RECEIVED = "received", _("Réceptionnée")
        CANCELLED = "cancelled", _("Annulée")

    store = models.ForeignKey(
        "store.Store",
        on_delete=models.PROTECT,
        related_name="purchases",
        verbose_name=_("Magasin"),
    )
    supplier_name = models.CharField(max_length=160, blank=True, default="", verbose_name=_("Fournisseur"))
    reference = models.CharField(max_length=80, blank=True, default="", db_index=True, verbose_name=_("Référence"))
    purchase_date = models.DateField(default=timezone.localdate, db_index=True, verbose_name=_("Date achat"))
    status = models.CharField(
        max_length=20,
        choices=Statuses.choices,
        default=Statuses.DRAFT,
        db_index=True,
        verbose_name=_("Statut"),
    )
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    note = models.TextField(blank=True, default="", verbose_name=_("Note"))
    created_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchases_created",
        verbose_name=_("Créé par"),
    )
    received_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchases_received",
        verbose_name=_("Réceptionné par"),
    )
    received_at = models.DateTimeField(null=True, blank=True)
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Achat")
        verbose_name_plural = _("Achats")
        ordering = ("-purchase_date", "-id")

    def __str__(self) -> str:
        return f"Achat #{self.pk} - {self.store}"


class PurchaseLine(models.Model):
    purchase = models.ForeignKey(
        Purchase,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name=_("Achat"),
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="purchase_lines",
        verbose_name=_("Article"),
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=3, verbose_name=_("Quantité"))
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, verbose_name=_("Coût unitaire"))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Ligne achat")
        verbose_name_plural = _("Lignes achats")

    def save(self, *args, **kwargs):
        self.total = (self.quantity or Decimal("0")) * (self.unit_cost or Decimal("0"))
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.product} x {self.quantity}"


class InventorySession(models.Model):
    class Statuses(models.TextChoices):
        DRAFT = "draft", _("Brouillon")
        VALIDATED = "validated", _("Validé")
        CANCELLED = "cancelled", _("Annulé")

    store = models.ForeignKey(
        "store.Store",
        on_delete=models.PROTECT,
        related_name="inventory_sessions",
        verbose_name=_("Magasin"),
    )
    code = models.CharField(max_length=80, db_index=True, verbose_name=_("Code inventaire"))
    title = models.CharField(max_length=160, verbose_name=_("Titre"))
    inventory_date = models.DateField(default=timezone.localdate, db_index=True, verbose_name=_("Date inventaire"))
    status = models.CharField(
        max_length=20,
        choices=Statuses.choices,
        default=Statuses.DRAFT,
        db_index=True,
        verbose_name=_("Statut"),
    )
    note = models.TextField(blank=True, default="", verbose_name=_("Note"))
    created_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_sessions_created",
    )
    validated_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_sessions_validated",
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Inventaire")
        verbose_name_plural = _("Inventaires")
        ordering = ("-inventory_date", "-id")
        constraints = [
            models.UniqueConstraint(fields=("store", "code"), name="unique_store_inventory_code")
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.store}"


class InventoryLine(models.Model):
    session = models.ForeignKey(
        InventorySession,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name=_("Inventaire"),
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="inventory_lines",
        verbose_name=_("Article"),
    )
    expected_quantity = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    counted_quantity = models.DecimalField(max_digits=12, decimal_places=3)
    difference = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    note = models.CharField(max_length=255, blank=True, default="")
    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Ligne inventaire")
        verbose_name_plural = _("Lignes inventaire")
        constraints = [
            models.UniqueConstraint(fields=("session", "product"), name="unique_inventory_product")
        ]

    def save(self, *args, **kwargs):
        self.difference = (self.counted_quantity or Decimal("0")) - (self.expected_quantity or Decimal("0"))
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.session} - {self.product}"
