"""Source snapshots shared by save hooks, backfill and financial reports."""
from django.apps import apps
from .pdf_translation import source, ensure_sources

NAMESPACE = "gestion_magasin"
REGISTRY = (
    ("catalog.Product", ("name",)),
    ("catalog.Category", ("name",)),
    ("sales.Promotion", ("name",)),
    ("finance.Expense", ("label",)),
    ("finance.ExpenseCategory", ("name",)),
    ("stock.InventorySession", ("title",)),
)


def known_names():
    from store.models import Store
    from sales.models import Customer
    from attendance.models import Employee
    from stock.models import Purchase
    from catalog.models import Product
    values = set(Store.objects.values_list("name", flat=True))
    values.update(Customer.objects.values_list("full_name", flat=True))
    values.update(Employee.objects.values_list("full_name", flat=True))
    values.update(Purchase.objects.exclude(supplier_name="").values_list("supplier_name", flat=True))
    values.update(Product.objects.exclude(reference__isnull=True).values_list("reference", flat=True))
    return {v for v in values if v}



def specifications(values, names=None):
    if names is None:
        names = known_names()
    return list({spec.fingerprint: spec for value in values
                 if (spec := source(value, names)) is not None}.values())


def instance_sources(instance, names=None):
    fields = next(fields for label, fields in REGISTRY
                  if instance._meta.label_lower == label.lower())
    return specifications([getattr(instance, field) for field in fields], names)


def prepare_saved(sender, instance, raw=False, update_fields=None, **kwargs):
    from .pdf_translation import translation_enabled
    if raw or not translation_enabled():
        return
    fields = next(fields for label, fields in REGISTRY
                  if sender._meta.label_lower == label.lower())
    if update_fields is None or set(fields).intersection(update_fields):
        ensure_sources(NAMESPACE, instance_sources(instance))


def connect():
    from django.db.models.signals import post_save
    for label, fields in REGISTRY:
        post_save.connect(prepare_saved, sender=apps.get_model(label),
                          dispatch_uid="prepare_pdf_" + label)
