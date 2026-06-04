from __future__ import absolute_import, unicode_literals

from os import environ

from celery import Celery
from django.conf import settings

environ.setdefault("DJANGO_SETTINGS_MODULE", "gestion_magasin_backend.settings")

app = Celery("gestion_magasin_backend", broker=settings.CELERY_BROKER_URL)
app.config_from_object("django.conf:settings", namespace="CELERY")
app.conf.timezone = settings.TIME_ZONE
app.conf.setdefault("worker_cancel_long_running_tasks_on_connection_loss", True)
app.conf.task_serializer = "json"
app.conf.result_serializer = "json"
app.conf.accept_content = ["json"]
from celery.schedules import crontab

app.autodiscover_tasks(
    packages=[
        "account.tasks",
        "notification.tasks",
    ]
)

app.conf.beat_schedule = {
    "check-low-stock-notifications-every-hour": {
        "task": "notification.check_low_stock_notifications",
        "schedule": crontab(minute=0),
    },
}
