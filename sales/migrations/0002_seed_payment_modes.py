from django.db import migrations


def seed_payment_modes(apps, schema_editor):
    PaymentMode = apps.get_model("sales", "PaymentMode")
    modes = [
        ("cash", "Espèces", False),
        ("card", "Carte bancaire", False),
        ("transfer", "Virement", False),
        ("credit", "Crédit client", True),
    ]
    for code, name, is_credit in modes:
        PaymentMode.objects.update_or_create(
            code=code,
            defaults={"name": name, "is_credit": is_credit, "is_active": True},
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_payment_modes, noop),
    ]

