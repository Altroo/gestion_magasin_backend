from django.core.management.base import BaseCommand
from django.db.models import Count
from ai_assistant.models import PdfTextTranslation
from ai_assistant.tasks import backfill_pdf_translations


class Command(BaseCommand):
    help = "Queue resumable preparation of saved sales invoice and stock report PDF text."

    def add_arguments(self, parser):
        parser.add_argument("--status", action="store_true")

    def handle(self, *args, **options):
        if options["status"]:
            for item in PdfTextTranslation.objects.values(
                "language", "status"
            ).annotate(count=Count("pk")):
                self.stdout.write(str(item))
        else:
            task = backfill_pdf_translations.delay()
            self.stdout.write(f"sales invoice and stock report PDF preparation queued: {task.id}")
