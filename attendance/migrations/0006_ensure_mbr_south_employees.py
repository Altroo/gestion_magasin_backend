from django.db import migrations


def ensure_mbr_south_employees(apps, schema_editor):
    Employee = apps.get_model("attendance", "Employee")
    Store = apps.get_model("store", "Store")
    store, _ = Store.objects.update_or_create(
        code="mbr-south",
        defaults={"name": "MBR SOUTH", "is_active": True},
    )

    employees = (
        ("MALAMANE BADR", "Conseiller de vente"),
        ("BELKACEM ABDELHAMID", "Conseiller de vente"),
        ("EL ABBID MANAL", "Conseillère de vente"),
    )
    for full_name, position in employees:
        Employee.objects.update_or_create(
            store=store,
            full_name=full_name,
            defaults={"position": position, "is_active": True},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0005_alter_attendanceimportbatch_responsible_and_more"),
        ("store", "0002_seed_store_defaults"),
    ]

    operations = [
        migrations.RunPython(
            ensure_mbr_south_employees,
            migrations.RunPython.noop,
        ),
    ]
