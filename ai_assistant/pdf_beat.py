"""Schedule PDF preparation without activating unrelated notification schedules."""

import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestion_magasin_backend.settings")
app = Celery("magasin_pdf_scheduler", set_as_current=False)
app.config_from_object("django.conf:settings", namespace="CELERY")
app.conf.beat_schedule = {
    "prepare-pending-pdf-translations": {
        "task": "ai_assistant.translate_pending_pdf_texts",
        "schedule": 60.0,
    }
}
