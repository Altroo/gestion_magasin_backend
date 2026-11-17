"""One source contract for saved-content preparation and PDF lookups."""

import hashlib
import json
import logging
import re
from dataclasses import dataclass

from django.apps import apps
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import PdfTextTranslation

logger = logging.getLogger(__name__)
LANGUAGES = ("fr", "en")
ENGINE_REVISION = 2


@dataclass(frozen=True)
class TextSource:
    text: str
    protected_terms: tuple[str, ...]

    @property
    def fingerprint(self):
        payload = json.dumps(
            [1, self.text, self.protected_terms],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()


def source(value, protected=()):
    if not isinstance(value, str) or not value.strip():
        return None
    # Irrelevant document names must not prevent reuse of an article translation.
    relevant = {
        term
        for term in protected
        if isinstance(term, str)
        and 1 < len(term) <= 200
        and re.search(rf"(?<!\w){re.escape(term)}(?!\w)", value, re.IGNORECASE)
    }
    terms = tuple(sorted(relevant, key=lambda term: (term.casefold(), term)))
    return TextSource(value, terms)


def dispatch_pending():
    from .tasks import translate_pending_pdf_texts

    try:
        translate_pending_pdf_texts.delay()
    except Exception:
        # The rows remain durable. Beat also drains them after broker recovery.
        logger.exception("Could not dispatch PDF translations; pending rows retained")


def ensure_sources(
    namespace, sources, languages=LANGUAGES, *, dispatch=True, priority=10
):
    sources = {spec.fingerprint: spec for spec in sources}
    if not sources:
        return
    PdfTextTranslation.objects.bulk_create(
        [
            PdfTextTranslation(
                namespace=namespace,
                fingerprint=key,
                source_text=spec.text,
                protected_terms=list(spec.protected_terms),
                language=language,
                priority=priority,
            )
            for key, spec in sources.items()
            for language in languages
        ],
        ignore_conflicts=True,
    )
    # A ready value from an older engine is never silently reused. Keep the
    # previous text for recovery, but prepare a current validated result.
    stale = PdfTextTranslation.objects.filter(
        namespace=namespace,
        fingerprint__in=sources,
        language__in=languages,
        engine_revision__lt=ENGINE_REVISION,
    )
    stale.update(
        status="pending",
        engine_revision=ENGINE_REVISION,
        attempts=0,
        available_at=timezone.now(),
        last_error="",
        lease_until=None,
        lease_token=None,
    )
    PdfTextTranslation.objects.filter(
        namespace=namespace,
        fingerprint__in=sources,
        language__in=languages,
        status="pending",
        priority__gt=priority,
    ).update(priority=priority)
    if dispatch:
        transaction.on_commit(dispatch_pending, robust=True)


def load_pdf_translations(namespace, specs, language):
    from .exceptions import PdfTranslationPending, PdfTranslationFailed

    if not specs:
        return {}
    rows = {
        row.fingerprint: row
        for row in PdfTextTranslation.objects.filter(
            namespace=namespace,
            language=language,
            fingerprint__in=[spec.fingerprint for spec in specs],
        )
    }
    missing = [spec for spec in specs if spec.fingerprint not in rows]
    if missing:
        ensure_sources(namespace, missing, [language], priority=0)
    outdated = [
        spec
        for spec in specs
        if spec.fingerprint in rows
        and rows[spec.fingerprint].engine_revision < ENGINE_REVISION
    ]
    if outdated:
        ensure_sources(namespace, outdated, [language], priority=0)
        raise PdfTranslationPending()
    if any(row.status == "failed" for row in rows.values()):
        raise PdfTranslationFailed()
    if missing or any(row.status != "ready" for row in rows.values()):
        promoted = PdfTextTranslation.objects.filter(
            namespace=namespace,
            language=language,
            pk__in=[row.pk for row in rows.values() if row.status == "pending"],
            priority__gt=0,
        ).update(priority=0)
        # An explicitly requested PDF can use the foreground quota reserved by
        # the shared gateway even when the bulk backfill is deferred.
        if promoted:
            PdfTextTranslation.objects.filter(
                namespace=namespace,
                language=language,
                status="pending",
                priority=0,
                last_error="ai_rate_limited",
                fingerprint__in=[spec.fingerprint for spec in specs],
            ).update(available_at=timezone.now(), last_error="")
        if promoted and not missing:
            transaction.on_commit(dispatch_pending, robust=True)
        if not promoted:
            waits = [
                (row.available_at - timezone.now()).total_seconds()
                for row in rows.values()
                if row.status == "pending" and row.last_error == "ai_rate_limited"
            ]
            if waits:
                from .exceptions import PdfTranslationDeferred

                raise PdfTranslationDeferred(wait=max(1, min(waits)))
        raise PdfTranslationPending()
    return {spec.text: rows[spec.fingerprint].translated_text for spec in specs}


def translation_enabled():
    return getattr(settings, "AI_PDF_TRANSLATION_ENABLED", False)


def validate_saved_translation(row, translated):
    from .exceptions import InvalidModelResponse
    from .text_integrity import Document, validate_meaning

    if not isinstance(translated, str) or not translated.strip():
        raise InvalidModelResponse()
    original = Document(row.source_text, row.protected_terms)
    result = Document(translated, row.protected_terms)
    if len(original.lines) != len(result.lines):
        raise InvalidModelResponse("La traduction a modifié les lignes.")
    for before, after in zip(original.lines, result.lines):
        if (before.prefix, before.suffix, before.ending) != (
            after.prefix,
            after.suffix,
            after.ending,
        ):
            raise InvalidModelResponse("La traduction a modifié la mise en page.")
        if list(before.replacements.values()) != list(after.replacements.values()):
            raise InvalidModelResponse("La traduction a modifié une valeur protégée.")
    if translated != row.source_text:
        validate_meaning(row.source_text, translated, row.language)
