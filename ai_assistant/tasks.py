"""Bounded background translation, durable retries, and resumable backfilling."""

from datetime import timedelta
import math
from uuid import uuid4

from celery.utils.log import get_task_logger
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from gestion_magasin_backend.celery_conf import app
from .client import AiAssistantClient
from rest_framework.exceptions import Throttled
from .exceptions import InvalidModelResponse
from .models import PdfTextTranslation
from .pdf_translation import (
    LANGUAGES,
    ENGINE_REVISION,
    validate_saved_translation,
    ensure_sources,
    translation_enabled,
)

logger = get_task_logger(__name__)


@app.task(
    name="ai_assistant.translate_pending_pdf_texts",
    ignore_result=True,
    queue="celery",
)
def translate_pending_pdf_texts():
    if not translation_enabled():
        return
    now = timezone.now()
    eligible = eligible_work(now)
    token = uuid4()
    with transaction.atomic():
        first = (
            PdfTextTranslation.objects.filter(eligible)
            .order_by("priority", "pk")
            .values("language", "namespace", "priority")
            .first()
        )
        if first is None:
            return
        candidates = list(
            PdfTextTranslation.objects.select_for_update(skip_locked=True)
            .filter(
                eligible,
                language=first["language"],
                namespace=first["namespace"],
                priority=first["priority"],
            )
            .order_by("priority", "pk")[:15]
        )
        rows = []
        size = 0
        for row in candidates:
            if rows and size + len(row.source_text) > 6000:
                break
            rows.append(row)
            size += len(row.source_text)
        if not rows:
            return
        ids = [row.pk for row in rows]
        lease_seconds = max(
            600,
            math.ceil(size / 4000) * (settings.AI_ASSISTANT_TIMEOUT_SECONDS + 5) + 60,
        )
        PdfTextTranslation.objects.filter(pk__in=ids).update(
            status="processing",
            lease_until=now + timedelta(seconds=lease_seconds),
            lease_token=token,
        )
    try:
        translations = AiAssistantClient().translate_many(
            [row.source_text for row in rows],
            target_language=first["language"],
            protected_terms=list(
                dict.fromkeys(term for row in rows for term in row.protected_terms)
            ),
            context="document_pdf",
            retry_rate_limit=False,
            background=first["priority"] >= 100,
        )
        for row in rows:
            text = translations.get(row.source_text)
            validate_saved_translation(row, text)
        with transaction.atomic():
            for row in rows:
                PdfTextTranslation.objects.filter(pk=row.pk, lease_token=token).update(
                    status="ready",
                    engine_revision=ENGINE_REVISION,
                    translated_text=translations[row.source_text],
                    lease_until=None,
                    lease_token=None,
                    last_error="",
                    updated_at=timezone.now(),
                )
    except Exception as exc:
        if isinstance(exc, InvalidModelResponse) and len(rows) > 1:
            # A bad legacy field must not fail otherwise valid fields in its batch.
            for row in rows:
                try:
                    translated = (
                        AiAssistantClient()
                        .translate_many(
                            [row.source_text],
                            target_language=row.language,
                            protected_terms=row.protected_terms,
                            context="document_pdf",
                            retry_rate_limit=False,
                            background=row.priority >= 100,
                        )
                        .get(row.source_text)
                    )
                    validate_saved_translation(row, translated)
                    PdfTextTranslation.objects.filter(
                        pk=row.pk, lease_token=token
                    ).update(
                        status="ready",
                        engine_revision=ENGINE_REVISION,
                        translated_text=translated,
                        lease_until=None,
                        lease_token=None,
                        last_error="",
                        updated_at=timezone.now(),
                    )
                except Exception as single_error:
                    record_failure(row, token, single_error)
        else:
            for row in rows:
                record_failure(row, token, exc)
    # Beat recovers pending/expired work even if this follow-up cannot be sent.
    if PdfTextTranslation.objects.filter(eligible_work(timezone.now())).exists():
        translate_pending_pdf_texts.apply_async(countdown=1)


def eligible_work(now):
    eligible = (
        Q(status="pending", available_at__lte=now)
        | Q(status="pending", last_error="ai_rate_limited")
        | Q(status="processing", lease_until__lt=now)
    )
    # The gateway handles Groq quota internally. Only its own request limit pauses work.
    if cache.get(quota_key(100), 0) > now.timestamp():
        eligible &= ~Q(priority__gte=100)
    if cache.get(quota_key(0), 0) > now.timestamp():
        eligible &= ~Q(priority__lt=100)
    return eligible


def quota_key(priority):
    return "pdf-translation-gateway-quota:" + (
        "background" if priority >= 100 else "foreground"
    )


def record_failure(row, token, exc):
    # Retry asynchronously. A slow/unavailable engine never delays a save or PDF.
    if isinstance(exc, Throttled):
        wait = max(1, float(exc.wait or 60))
        cache.set(
            quota_key(row.priority),
            timezone.now().timestamp() + wait,
            math.ceil(wait) + 1,
        )
        PdfTextTranslation.objects.filter(pk=row.pk, lease_token=token).update(
            status="pending",
            available_at=timezone.now()
            + timedelta(seconds=max(1, float(exc.wait or 60))),
            lease_until=None,
            lease_token=None,
            last_error="ai_gateway_throttled",
            updated_at=timezone.now(),
        )
        return
    error_code = str(getattr(exc, "default_code", type(exc).__name__))[:80]
    attempts = row.attempts + 1
    delay = max(
        float(getattr(exc, "wait", 0) or 0),
        min(3600, 30 * 2 ** min(attempts - 1, 7)),
    )
    changed = PdfTextTranslation.objects.filter(pk=row.pk, lease_token=token).update(
        status="failed" if attempts >= 6 else "pending",
        attempts=attempts,
        available_at=timezone.now() + timedelta(seconds=delay),
        lease_until=None,
        lease_token=None,
        last_error=error_code,
        updated_at=timezone.now(),
    )
    if changed:
        logger.warning(
            "PDF translation failed: row_id=%s language=%s attempt=%s code=%s",
            row.pk,
            row.language,
            attempts,
            error_code,
        )


@app.task(name="ai_assistant.backfill_pdf_translations", autoretry_for=(Exception,),
          retry_backoff=True, retry_kwargs={"max_retries": 5})
def backfill_pdf_translations(model_index=0, after_pk=0, batch_size=50):
    from django.apps import apps
    from .pdf_sources import REGISTRY, NAMESPACE, instance_sources
    if not translation_enabled() or model_index >= len(REGISTRY):
        return
    label, fields = REGISTRY[model_index]
    batch_size = max(1, min(100, batch_size))
    instances = list(apps.get_model(label).objects.filter(pk__gt=after_pk)
                     .order_by("pk")[:max(1, min(100, batch_size))])
    from .pdf_sources import known_names
    names = known_names()
    for instance in instances:
        ensure_sources(NAMESPACE, instance_sources(instance, names),
                       dispatch=False, priority=100)
    if instances:
        translate_pending_pdf_texts.delay()
    next_index = model_index if len(instances) == batch_size else model_index + 1
    if next_index < len(REGISTRY):
        backfill_pdf_translations.apply_async(kwargs={
            "model_index": next_index,
            "after_pk": instances[-1].pk if next_index == model_index else 0,
            "batch_size": batch_size}, countdown=1)
    return {"model": label, "scanned": len(instances)}
