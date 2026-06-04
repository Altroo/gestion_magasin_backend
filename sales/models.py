from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords


class Customer(models.Model):
    full_name = models.CharField(max_length=160, verbose_name=_("Nom"))
    phone = models.CharField(max_length=40, blank=True, default="", verbose_name=_("Téléphone"))
    email = models.EmailField(blank=True, default="", verbose_name=_("Email"))
    store = models.ForeignKey(
        "store.Store",
        on_delete=models.CASCADE,
        related_name="customers",
        verbose_name=_("Magasin"),
    )
    credit_limit = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name=_("Plafond crédit")
    )
    is_active = models.BooleanField(default=True, db_index=True, verbose_name=_("Actif"))
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Client")
        verbose_name_plural = _("Clients")
        ordering = ("full_name",)

    def __str__(self) -> str:
        return self.full_name


class PaymentMode(models.Model):
    code = models.CharField(max_length=40, unique=True, verbose_name=_("Code"))
    name = models.CharField(max_length=80, unique=True, verbose_name=_("Nom"))
    is_credit = models.BooleanField(default=False, verbose_name=_("Crédit client"))
    is_active = models.BooleanField(default=True, db_index=True, verbose_name=_("Actif"))

    class Meta:
        verbose_name = _("Mode de paiement")
        verbose_name_plural = _("Modes de paiement")
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class Sale(models.Model):
    class Statuses(models.TextChoices):
        CONFIRMED = "confirmed", _("Confirmée")
        VOID = "void", _("Annulée")

    class PaymentStatuses(models.TextChoices):
        PAID = "paid", _("Payée")
        CREDIT = "credit", _("Crédit")

    store = models.ForeignKey(
        "store.Store",
        on_delete=models.PROTECT,
        related_name="sales",
        verbose_name=_("Magasin"),
    )
    seller = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales",
        verbose_name=_("Vendeur"),
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales",
        verbose_name=_("Client"),
    )
    payment_mode = models.ForeignKey(
        PaymentMode,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sales",
        verbose_name=_("Mode paiement"),
    )
    status = models.CharField(
        max_length=20,
        choices=Statuses.choices,
        default=Statuses.CONFIRMED,
        db_index=True,
        verbose_name=_("Statut"),
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatuses.choices,
        default=PaymentStatuses.PAID,
        verbose_name=_("Statut paiement"),
    )
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    change_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    idempotency_key = models.CharField(
        max_length=120,
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("Clé idempotence"),
    )
    offline_created_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True, default="", verbose_name=_("Note"))
    void_reason = models.TextField(blank=True, default="", verbose_name=_("Raison annulation"))
    voided_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="voided_sales",
    )
    voided_at = models.DateTimeField(null=True, blank=True)
    date_created = models.DateTimeField(auto_now_add=True, db_index=True)
    date_updated = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Vente")
        verbose_name_plural = _("Ventes")
        ordering = ("-date_created",)
        constraints = [
            models.UniqueConstraint(
                fields=("store", "idempotency_key"),
                condition=models.Q(idempotency_key__isnull=False),
                name="unique_store_sale_idempotency",
            )
        ]

    def __str__(self) -> str:
        return f"Vente #{self.pk} - {self.store}"


class SaleLine(models.Model):
    sale = models.ForeignKey(
        Sale, on_delete=models.CASCADE, related_name="lines", verbose_name=_("Vente")
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="sale_lines",
        verbose_name=_("Article"),
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=3, verbose_name=_("Quantité"))
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name=_("Prix unitaire"))
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        verbose_name = _("Ligne vente")
        verbose_name_plural = _("Lignes ventes")

    def save(self, *args, **kwargs):
        self.unit_cost = self.unit_cost or self.product.purchase_price
        self.total = (self.quantity or Decimal("0")) * (self.unit_price or Decimal("0"))
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.product} x {self.quantity}"


class CustomerCreditLedger(models.Model):
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="credit_entries",
        verbose_name=_("Client"),
    )
    sale = models.ForeignKey(
        Sale,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="credit_entries",
        verbose_name=_("Vente"),
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name=_("Montant"))
    note = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Note"))
    created_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customer_credit_entries",
    )
    date_created = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Journal crédit client")
        verbose_name_plural = _("Journal crédits clients")
        ordering = ("-date_created",)

