from django.db import migrations


def record_release(apps, schema_editor):
    entry, _ = apps.get_model("ws", "ChangelogEntry").objects.using(
        schema_editor.connection.alias
    ).get_or_create(
        date="2026-11-19",
        defaults={
            "version": "2.10.2",
            "title_fr": "Impression directe des PDF rédigés en français",
            "title_en": "Direct printing for French PDFs",
            "changes_fr": (
                "Les PDF rédigés en français s’ouvrent sans attendre la file "
                "de traduction.\n"
                "Le texte d’origine, les références et la mise en page sont conservés."
            ),
            "changes_en": (
                "PDFs written in French open without waiting for the translation queue.\n"
                "Original wording, references and layout are preserved."
            ),
            "is_published": False,
        },
    )
    if entry.version != "2.10.2":
        raise ValueError("Another changelog entry already exists for this release date")


class Migration(migrations.Migration):
    dependencies = [("ws", "0005_groq_pdf_release")]
    operations = [migrations.RunPython(record_release, migrations.RunPython.noop)]
