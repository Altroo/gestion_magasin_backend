from datetime import date

from django.db import migrations


def seed_release(apps, schema_editor):
    apps.get_model("ws", "ChangelogEntry").objects.using(
        schema_editor.connection.alias
    ).get_or_create(
        date=date(2026, 11, 14),
        defaults={
            "version": "2.10.0",
            "title_fr": "Nouveautés",
            "title_en": "Updates",
            "changes_fr": (
                "Les articles et le stock central sont gérés par MBR SOUTH.\n"
                "Les magasins demandent du stock, puis MBR SOUTH leur affecte les quantités disponibles.\n"
                "La vente en gros est réservée à la direction et prélève le stock de MBR SOUTH."
            ),
            "changes_en": (
                "Products and central inventory are managed by MBR SOUTH.\n"
                "Stores request stock, then MBR SOUTH allocates available quantities.\n"
                "Wholesale sales require Direction access and deduct inventory from MBR SOUTH."
            ),
            "is_published": False,
        },
    )


class Migration(migrations.Migration):
    dependencies = [("ws", "0003_seed_changelog_history")]
    operations = [migrations.RunPython(seed_release, migrations.RunPython.noop)]
