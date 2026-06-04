from django.db import migrations


def seed_mbr_stock(apps, schema_editor):
    Store = apps.get_model("store", "Store")
    Store.objects.update_or_create(
        code="mbr-stock",
        defaults={
            "name": "MBR Stock",
            "address": "",
            "phone": "",
            "is_active": True,
            "is_global_stock": True,
        },
    )
    Store.objects.filter(code="mbr-south").update(is_global_stock=False)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("store", "0003_historicalstore_is_global_stock_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_mbr_stock, noop),
    ]
