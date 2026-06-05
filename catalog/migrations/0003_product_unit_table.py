from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import simple_history.models


def migrate_units_forward(apps, schema_editor):
    Product = apps.get_model("catalog", "Product")
    ProductUnit = apps.get_model("catalog", "ProductUnit")

    default_unit, _created = ProductUnit.objects.get_or_create(
        code="unite",
        defaults={"name": "Unité", "is_active": True},
    )
    for product in Product.objects.all():
        label = (product.unit or "").strip() or default_unit.name
        code = (
            label.lower()
            .replace("é", "e")
            .replace("è", "e")
            .replace("ê", "e")
            .replace("à", "a")
            .replace(" ", "-")
        )[:40] or "unite"
        unit, _created = ProductUnit.objects.get_or_create(
            code=code,
            defaults={"name": label, "is_active": True},
        )
        product.unit_ref_id = unit.pk
        product.save(update_fields=["unit_ref"])


def migrate_units_backward(apps, schema_editor):
    Product = apps.get_model("catalog", "Product")
    for product in Product.objects.select_related("unit_ref").all():
        product.unit = product.unit_ref.name if product.unit_ref_id else "unité"
        product.save(update_fields=["unit"])


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0002_historicalproductimportbatch"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ProductUnit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=40, unique=True, verbose_name="Code")),
                ("name", models.CharField(max_length=80, unique=True, verbose_name="Nom")),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="Actif")),
                ("date_created", models.DateTimeField(auto_now_add=True)),
                ("date_updated", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Unité article",
                "verbose_name_plural": "Unités articles",
                "ordering": ("code", "name"),
            },
        ),
        migrations.CreateModel(
            name="HistoricalProductUnit",
            fields=[
                ("id", models.BigIntegerField(auto_created=True, blank=True, db_index=True, verbose_name="ID")),
                ("code", models.CharField(db_index=True, max_length=40, verbose_name="Code")),
                ("name", models.CharField(db_index=True, max_length=80, verbose_name="Nom")),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="Actif")),
                ("date_created", models.DateTimeField(blank=True, editable=False)),
                ("date_updated", models.DateTimeField(blank=True, editable=False)),
                ("history_id", models.AutoField(primary_key=True, serialize=False)),
                ("history_date", models.DateTimeField(db_index=True)),
                ("history_change_reason", models.CharField(max_length=100, null=True)),
                ("history_type", models.CharField(choices=[("+", "Created"), ("~", "Changed"), ("-", "Deleted")], max_length=1)),
                ("history_user", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "historical Unité article",
                "verbose_name_plural": "historical Unités articles",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.AddField(
            model_name="product",
            name="unit_ref",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="products",
                to="catalog.productunit",
                verbose_name="Unité",
            ),
        ),
        migrations.RunPython(migrate_units_forward, migrate_units_backward),
        migrations.RemoveField(
            model_name="historicalproduct",
            name="unit",
        ),
        migrations.RemoveField(
            model_name="product",
            name="unit",
        ),
        migrations.RenameField(
            model_name="product",
            old_name="unit_ref",
            new_name="unit",
        ),
        migrations.AddField(
            model_name="historicalproduct",
            name="unit",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="catalog.productunit",
                verbose_name="Unité",
            ),
        ),
        migrations.AlterField(
            model_name="product",
            name="unit",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="products",
                to="catalog.productunit",
                verbose_name="Unité",
            ),
        ),
    ]
