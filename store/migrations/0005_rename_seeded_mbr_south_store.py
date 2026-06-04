from django.db import migrations


def rename_seeded_mbr_south_store(apps, schema_editor):
    Store = apps.get_model("store", "Store")
    store = Store.objects.filter(code="mbr-south", is_global_stock=False).first()
    if not store:
        return

    if not Store.objects.filter(code="magasin-casablanca").exclude(pk=store.pk).exists():
        store.code = "magasin-casablanca"
    if not Store.objects.filter(name="Magasin Casablanca").exclude(pk=store.pk).exists():
        store.name = "Magasin Casablanca"
    store.save(update_fields=["code", "name", "date_updated"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("store", "0004_seed_mbr_stock"),
    ]

    operations = [
        migrations.RunPython(rename_seeded_mbr_south_store, noop),
    ]
