from django.db import migrations


def record_release(apps, schema_editor):
    apps.get_model("ws", "ChangelogEntry").objects.using(
        schema_editor.connection.alias
    ).update_or_create(
        date="2026-11-17",
        defaults={
            "version": "2.10.1",
            "title_fr": "Des textes plus naturels et professionnels",
            "title_en": "More natural and professional writing",
            "changes_fr": "Traduction tenant compte du sens et du vocabulaire métier.\nCorrection grammaticale et reformulation professionnelle améliorées.\nRetours à la ligne, listes, mentions de collègues, références et valeurs conservés.\nLes textes des factures et rapports sont préparés en arrière-plan dès leur enregistrement ; les PDF utilisent les traductions sauvegardées.",
            "changes_en": "Meaning-aware translation using business terminology.\nImproved grammar correction and professional rewriting.\nPreserve line breaks, lists, colleague mentions, references and values.\nInvoice and report text is prepared in the background after saving; PDFs use stored translations.",
            "is_published": False,
        },
    )


class Migration(migrations.Migration):
    dependencies = [("ws", "0004_mbr_south_release_2_10_0")]
    operations = [migrations.RunPython(record_release, migrations.RunPython.noop)]
