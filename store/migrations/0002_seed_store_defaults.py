from django.db import migrations


def seed_store_defaults(apps, schema_editor):
    Role = apps.get_model("store", "Role")
    Store = apps.get_model("store", "Store")

    roles = [
        ("direction", "Direction", 1),
        ("responsable", "Responsable", 2),
        ("vendeur", "Vendeur", 3),
        ("lecture", "Lecture", 4),
    ]
    for code, name, rank in roles:
        Role.objects.update_or_create(
            code=code,
            defaults={"name": name, "rank": rank},
        )

    Store.objects.update_or_create(
        code="mbr-south",
        defaults={
            "name": "MBR SOUTH",
            "address": "",
            "phone": "",
            "is_active": True,
        },
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("store", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_store_defaults, noop),
    ]

