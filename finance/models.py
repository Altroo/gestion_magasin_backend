from os import path
from uuid import uuid4

from django.db import models
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords


def get_expense_invoice_path(_, filename):
    _, ext = path.splitext(filename)
    return path.join("expenses/invoices/", str(uuid4()) + ext)


class ExpenseCategory(models.Model):
    code = models.CharField(max_length=40, unique=True, verbose_name=_("Code"))
    name = models.CharField(max_length=120, unique=True, verbose_name=_("Nom"))
    is_active = models.BooleanField(default=True, db_index=True, verbose_name=_("Actif"))
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Poste de dépense")
        verbose_name_plural = _("Postes de dépense")
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class Expense(models.Model):
    class PaymentStatuses(models.TextChoices):
        PAID = "paid", _("Payée")
        PAYABLE = "payable", _("À payer")

    class PaymentModes(models.TextChoices):
        CASH = "cash", _("Espèces")
        CARD = "card", _("Carte")
        TRANSFER = "transfer", _("Virement")
        OTHER = "other", _("Autre")

    store = models.ForeignKey(
        "store.Store",
        on_delete=models.PROTECT,
        related_name="expenses",
        verbose_name=_("Magasin"),
    )
    category = models.ForeignKey(
        ExpenseCategory,
        on_delete=models.PROTECT,
        related_name="expenses",
        verbose_name=_("Poste de dépense"),
    )
    label = models.CharField(max_length=180, verbose_name=_("Libellé"))
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name=_("Montant"))
    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatuses.choices,
        default=PaymentStatuses.PAID,
        db_index=True,
        verbose_name=_("Statut paiement"),
    )
    payment_mode = models.CharField(
        max_length=20,
        choices=PaymentModes.choices,
        default=PaymentModes.CASH,
        verbose_name=_("Mode de paiement"),
    )
    expense_date = models.DateField(db_index=True, verbose_name=_("Date"))
    invoice_file = models.FileField(
        upload_to=get_expense_invoice_path,
        null=True,
        blank=True,
        verbose_name=_("Facture"),
    )
    note = models.TextField(blank=True, default="", verbose_name=_("Note"))
    created_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="expenses_created",
        verbose_name=_("Créé par"),
    )
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Dépense")
        verbose_name_plural = _("Dépenses")
        ordering = ("-expense_date", "-id")

    def __str__(self) -> str:
        return f"{self.label} - {self.amount}"
