from django.db import models
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords


class Category(models.Model):
    code = models.CharField(max_length=40, unique=True, verbose_name=_("Code"))
    name = models.CharField(max_length=120, unique=True, verbose_name=_("Nom"))
    is_active = models.BooleanField(default=True, db_index=True, verbose_name=_("Actif"))
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Famille article")
        verbose_name_plural = _("Familles articles")
        ordering = ("code", "name")

    def __str__(self) -> str:
        return self.name


class Product(models.Model):
    reference = models.CharField(
        max_length=80,
        unique=True,
        null=True,
        blank=True,
        verbose_name=_("Référence"),
    )
    barcode = models.CharField(
        max_length=80,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("Code barre"),
    )
    name = models.CharField(max_length=255, db_index=True, verbose_name=_("Désignation"))
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products",
        null=True,
        blank=True,
        verbose_name=_("Famille"),
    )
    unit = models.CharField(max_length=40, default="unité", verbose_name=_("Unité"))
    purchase_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name=_("Prix achat"),
    )
    wholesale_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name=_("Prix gros"),
    )
    detail_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name=_("Prix détail"),
    )
    counter_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name=_("Prix comptoir"),
    )
    default_stock_alert = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=0,
        verbose_name=_("Stock minimum par défaut"),
    )
    expiration_date = models.DateField(
        null=True, blank=True, verbose_name=_("Date expiration")
    )
    shelf_life_days = models.PositiveIntegerField(
        null=True, blank=True, verbose_name=_("Durée")
    )
    compliance_required = models.BooleanField(
        default=False, verbose_name=_("Obligation conformité")
    )
    is_active = models.BooleanField(default=True, db_index=True, verbose_name=_("Actif"))
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Article")
        verbose_name_plural = _("Articles")
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        self.reference = self.reference or None
        self.barcode = self.barcode or None
        if not self.unit:
            self.unit = "unité"
        super().save(*args, **kwargs)


class ProductImportBatch(models.Model):
    store = models.ForeignKey(
        "store.Store",
        on_delete=models.PROTECT,
        related_name="product_imports",
        verbose_name=_("Magasin"),
    )
    file_name = models.CharField(max_length=255, verbose_name=_("Fichier"))
    imported_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="product_imports",
        verbose_name=_("Importé par"),
    )
    imported_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    date_created = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Import articles")
        verbose_name_plural = _("Imports articles")
        ordering = ("-date_created",)

    def __str__(self) -> str:
        return f"{self.file_name} - {self.store}"

