from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from attendance.importers import import_attendance_from_workbook
from store.models import Store

User = get_user_model()


class Command(BaseCommand):
    help = "Importe le fichier Excel de pointage MBR SOUTH."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--store", required=True, help="Code du magasin")
        parser.add_argument("--user-email", default="")

    def handle(self, *args, **options):
        try:
            store = Store.objects.get(code=options["store"])
        except Store.DoesNotExist as exc:
            raise CommandError("Magasin introuvable.") from exc

        user = None
        if options["user_email"]:
            user = User.objects.filter(email=options["user_email"]).first()

        batch = import_attendance_from_workbook(
            options["path"],
            store=store,
            imported_by=user,
            file_name=options["path"].split("/")[-1],
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"{batch.imported_count} pointages importés, {batch.skipped_count} lignes ignorées."
            )
        )
