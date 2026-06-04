from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords


class Employee(models.Model):
    store = models.ForeignKey(
        "store.Store",
        on_delete=models.CASCADE,
        related_name="employees",
        verbose_name=_("Magasin"),
    )
    user = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee_profiles",
        verbose_name=_("Utilisateur"),
    )
    full_name = models.CharField(max_length=160, verbose_name=_("Nom complet"))
    position = models.CharField(max_length=120, blank=True, default="", verbose_name=_("Poste"))
    is_active = models.BooleanField(default=True, db_index=True, verbose_name=_("Actif"))
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Employé")
        verbose_name_plural = _("Employés")
        ordering = ("full_name",)
        constraints = [
            models.UniqueConstraint(
                fields=("store", "full_name"), name="unique_store_employee_name"
            )
        ]

    def __str__(self) -> str:
        return self.full_name


class AttendanceRecord(models.Model):
    class Statuses(models.TextChoices):
        PRESENT = "present", _("Présent")
        OFF = "off", _("Repos")
        ABSENT = "absent", _("Absent")

    store = models.ForeignKey(
        "store.Store",
        on_delete=models.CASCADE,
        related_name="attendance_records",
        verbose_name=_("Magasin"),
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="attendance_records",
        verbose_name=_("Employé"),
    )
    date = models.DateField(db_index=True, verbose_name=_("Date"))
    clock_in = models.TimeField(null=True, blank=True, verbose_name=_("Entrée"))
    break_start = models.TimeField(null=True, blank=True, verbose_name=_("Début pause"))
    break_end = models.TimeField(null=True, blank=True, verbose_name=_("Fin pause"))
    clock_out = models.TimeField(null=True, blank=True, verbose_name=_("Sortie"))
    hours_worked = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("0"), verbose_name=_("Heures")
    )
    delay_minutes = models.PositiveIntegerField(default=0, verbose_name=_("Retard minutes"))
    status = models.CharField(
        max_length=20,
        choices=Statuses.choices,
        default=Statuses.PRESENT,
        verbose_name=_("Statut"),
    )
    responsible = models.CharField(max_length=160, blank=True, default="", verbose_name=_("Responsable"))
    observations = models.TextField(blank=True, default="", verbose_name=_("Observations"))
    created_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_records_created",
    )
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Pointage")
        verbose_name_plural = _("Pointages")
        ordering = ("-date", "employee__full_name")
        constraints = [
            models.UniqueConstraint(
                fields=("store", "employee", "date"), name="unique_employee_attendance_day"
            )
        ]

    def __str__(self) -> str:
        return f"{self.employee} - {self.date}"


class AttendanceImportBatch(models.Model):
    store = models.ForeignKey(
        "store.Store",
        on_delete=models.PROTECT,
        related_name="attendance_imports",
        verbose_name=_("Magasin"),
    )
    file_name = models.CharField(max_length=255, verbose_name=_("Fichier"))
    responsible = models.CharField(max_length=160, blank=True, default="", verbose_name=_("Responsable"))
    week_start = models.DateField(null=True, blank=True)
    week_end = models.DateField(null=True, blank=True)
    imported_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_imports",
    )
    imported_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    date_created = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Import pointage")
        verbose_name_plural = _("Imports pointage")
        ordering = ("-date_created",)

    def __str__(self) -> str:
        return f"{self.file_name} - {self.store}"
