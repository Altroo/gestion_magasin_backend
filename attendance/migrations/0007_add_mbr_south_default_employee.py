from django.db import migrations


def add_mbr_south_default_employee(apps, schema_editor):
    Employee = apps.get_model("attendance", "Employee")
    Store = apps.get_model("store", "Store")
    store = Store.objects.get(code="mbr-south")

    Employee.objects.update_or_create(
        store=store,
        full_name="Mehdi Zorgane",
        defaults={"position": "Responsable", "is_active": True},
    )


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0006_ensure_mbr_south_employees"),
    ]

    operations = [
        migrations.RunPython(
            add_mbr_south_default_employee,
            migrations.RunPython.noop,
        ),
    ]
