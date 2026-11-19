from datetime import date, timedelta
from unittest.mock import patch
import pytest
from django.core.cache import cache
from django.utils import timezone
from ai_assistant.models import PdfTextTranslation
from ai_assistant.pdf_translation import ensure_sources, load_pdf_translations, source, validate_saved_translation
from ai_assistant.tasks import translate_pending_pdf_texts, backfill_pdf_translations, quota_key
from ai_assistant.client import AiAssistantClient
from ai_assistant.exceptions import PdfTranslationPending, PdfTranslationDeferred, InvalidModelResponse
from ai_assistant.pdf_sources import instance_sources, NAMESPACE
from catalog.models import Product, Category
from django.test import override_settings

def make_project():
    with override_settings(AI_PDF_TRANSLATION_ENABLED=False):
        category = Category.objects.create(code="QA",name="Famille QA")
        return Product.objects.create(reference="QA-2048",name="Article QA",category=category)

pytestmark = pytest.mark.django_db

@pytest.fixture(autouse=True)
def preparation_settings(settings):
    settings.AI_PDF_TRANSLATION_ENABLED = True
    settings.CELERY_TASK_ALWAYS_EAGER = False
    cache.clear()
    with patch("ai_assistant.pdf_translation.dispatch_pending") as dispatch, patch.object(translate_pending_pdf_texts, "apply_async"):
        yield dispatch


def test_new_or_edited_pdf_text_never_uses_an_old_cached_value():
    spec = source("Livrer avant midi")
    ensure_sources("casa_di_lusso", [spec], ["en"], dispatch=False)
    with pytest.raises(PdfTranslationPending):
        load_pdf_translations("casa_di_lusso", [spec], "en")
    PdfTextTranslation.objects.update(
        status="ready", translated_text="Deliver before noon"
    )
    with patch.object(AiAssistantClient, "translate_many") as model:
        assert (
            load_pdf_translations("casa_di_lusso", [spec], "en")[spec.text]
            == "Deliver before noon"
        )
    model.assert_not_called()
    with pytest.raises(PdfTranslationPending):
        load_pdf_translations("casa_di_lusso", [source("Livrer après midi")], "en")
    with pytest.raises(PdfTranslationPending):
        load_pdf_translations("blueline", [spec], "en")


def test_worker_persists_valid_text_and_rejects_broken_layout():
    spec = source("• Livrer 120*120cm.\n• Marbre non compris.")
    ensure_sources("casa_di_lusso", [spec], ["en"], dispatch=False)
    with patch.object(
        AiAssistantClient,
        "translate_many",
        return_value={spec.text: "• Deliver 120*120cm.\n• Marble not included."},
    ) as client:
        translate_pending_pdf_texts()
    assert PdfTextTranslation.objects.get().status == "ready"
    assert client.call_args.kwargs["context"] == "document_pdf"
    row = PdfTextTranslation.objects.get()
    for broken in [
        "Deliver 120*120cm. Marble not included.",
        "• Deliver 120x120cm.\n• Marble not included.",
        "• Deliver 120*120cm.\n• Marble included.",
    ]:
        with pytest.raises(InvalidModelResponse):
            validate_saved_translation(row, broken)


def test_quota_deadlines_do_not_extend_and_foreground_can_use_reserved_capacity():
    from rest_framework.exceptions import Throttled

    ensure_sources(
        "casa_di_lusso",
        [source("Chaise en bois")],
        ["en"],
        priority=100,
        dispatch=False,
    )
    with patch.object(
        AiAssistantClient, "translate_many", side_effect=Throttled(wait=60)
    ):
        translate_pending_pdf_texts()
    deadline = cache.get(quota_key(100))
    ensure_sources(
        "casa_di_lusso", [source("Table en bois")], ["en"], priority=100, dispatch=False
    )
    for _ in range(10):
        translate_pending_pdf_texts()
    assert cache.get(quota_key(100)) == deadline
    ensure_sources(
        "casa_di_lusso", [source("Lampe en bois")], ["en"], priority=0, dispatch=False
    )
    with patch.object(
        AiAssistantClient,
        "translate_many",
        return_value={"Lampe en bois": "Wooden lamp"},
    ):
        translate_pending_pdf_texts()
    assert PdfTextTranslation.objects.get(source_text="Lampe en bois").status == "ready"
    assert not PdfTextTranslation.objects.exclude(attempts=0).exists()


def test_quota_deferred_pdf_does_not_wait_for_sync_translation():
    spec = source("Livrer avant midi")
    ensure_sources("casa_di_lusso", [spec], ["en"], priority=0, dispatch=False)
    PdfTextTranslation.objects.update(
        last_error="ai_rate_limited", available_at=timezone.now() - timedelta(seconds=1)
    )
    with pytest.raises(PdfTranslationDeferred):
        load_pdf_translations("casa_di_lusso", [spec], "en")



def test_save_is_durable_and_async(django_capture_on_commit_callbacks, preparation_settings):
    with patch.object(AiAssistantClient, "translate_many") as model, django_capture_on_commit_callbacks(execute=True):
        project = make_project()
        project.name = "• Marbre non compris.\n  • Pose 120*120cm."
        project.save(update_fields=["name"])
        assert PdfTextTranslation.objects.filter(source_text=project.name).count() == 2
        preparation_settings.assert_not_called()
    preparation_settings.assert_called_once()
    model.assert_not_called()
    project.refresh_from_db()
    assert "Marbre non compris" in project.name


def test_save_rollback_removes_translation_rows(django_capture_on_commit_callbacks, preparation_settings):
    from django.db import transaction
    with django_capture_on_commit_callbacks(execute=True):
        with pytest.raises(ValueError), transaction.atomic():
            project = make_project()
            project.name = "Notes annulées"
            project.save(update_fields=["name"])
            raise ValueError("rollback")
    assert not PdfTextTranslation.objects.exists()
    preparation_settings.assert_not_called()


def test_backfill_is_bounded_idempotent(settings):
    settings.AI_PDF_TRANSLATION_ENABLED = False
    project = make_project()
    project.name = "Contenu historique"
    project.save(update_fields=["name"])
    settings.AI_PDF_TRANSLATION_ENABLED = True
    with patch.object(backfill_pdf_translations, "apply_async") as next_job, patch.object(translate_pending_pdf_texts, "delay"):
        assert backfill_pdf_translations()["scanned"] == 1
        backfill_pdf_translations()
    assert PdfTextTranslation.objects.count() == 2
    assert set(PdfTextTranslation.objects.values_list("priority", flat=True)) == {100}
    assert next_job.call_args.kwargs["kwargs"]["model_index"] == 1




def test_sale_pdf_reads_cache_and_preserves_lines_and_amounts(tmp_path):
    from sales.models import Sale, SaleLine
    from sales.pdf import build_sale_facture_pdf
    from sales.tests import create_user, create_store_setup
    with override_settings(AI_PDF_TRANSLATION_ENABLED=False):
        user=create_user();store,product=create_store_setup(user)
        product.name="• Marbre non compris.\n  • Pose 120*120cm."
        product.save(update_fields=["name"])
        sale=Sale.objects.create(store=store,seller=user,subtotal=25,total=25)
        SaleLine.objects.create(sale=sale,product=product,quantity=1,unit_price=25,total=25)
    with patch("sales.pdf.load_pdf_translations",return_value={product.name:"• Marble not included.\n  • Install 120*120cm."}) as lookup, patch.object(AiAssistantClient,"translate_many") as model:
        pdf=build_sale_facture_pdf(sale,language="en")
    assert pdf.content.startswith(b"%PDF-")
    model.assert_not_called()
    assert lookup.call_args.args[1][0].text==product.name
    path=tmp_path/"invoice.pdf";path.write_bytes(pdf.content)
    import subprocess
    text=subprocess.check_output(["pdftotext","-layout",str(path),"-"],text=True)
    assert "Marble not included." in text and "Install 120*120cm." in text and "25.00" in text
    product.refresh_from_db();assert "Marbre" in product.name


def test_stock_report_translates_all_prose_columns_without_touching_identities(tmp_path):
    from reporting.views import _pdf_response
    from rest_framework.test import APIRequestFactory
    from rest_framework.request import Request
    request=Request(APIRequestFactory().get("/api/reports/export/stock/",{"language":"en"}))
    headers=["Magasin","Article","Famille","Poste","Titre","Nom","Reference","Statut","Total"]
    rows=[["Brouillon","Chaise","Bois","Ménage","Inventaire initial","Promotion du soir","sale","draft",25]]
    texts={"Chaise":"Chair","Bois":"Wood","Ménage":"Cleaning","Inventaire initial":"Initial inventory","Promotion du soir":"Evening promotion"}
    with patch("reporting.views.load_pdf_translations",return_value=texts) as lookup, patch.object(AiAssistantClient,"translate_many") as model:
        response=_pdf_response("stock",headers,rows,request)
    path=tmp_path/"stock.pdf";path.write_bytes(b"".join(response.streaming_content))
    import subprocess
    text=subprocess.check_output(["pdftotext","-layout",str(path),"-"],text=True)
    for value in ["Chair","Wood","Cleaning","Initial inventory","Evening promotion","Brouillon","sale","Draft","25,00"]:assert value in text
    assert {spec.text for spec in lookup.call_args.args[1]}==set(texts)
    model.assert_not_called()


def test_fixed_report_copy_is_complete():
    import ast,inspect
    from reporting import views
    from reporting.pdf_labels import EN_LABELS
    headers=set()
    for node in ast.walk(ast.parse(inspect.getsource(views._queryset_for_export))):
        if isinstance(node,ast.Return) and isinstance(node.value,ast.Tuple) and isinstance(node.value.elts[0],ast.List):
            headers.update(v.value for v in node.value.elts[0].elts if isinstance(v,ast.Constant))
    assert headers <= EN_LABELS.keys()
    assert set(views.REPORT_TITLES.values()) <= EN_LABELS.keys()
    assert set(views.STATUS_LABELS.values()) <= EN_LABELS.keys()


def test_pdf_layout_escape_preserves_bullets():
    from ai_assistant.pdf_text import escaped_pdf_text
    assert escaped_pdf_text("• A & B\n  • <Suite>")=="• A &amp; B<br/>&#160;&#160;• &lt;Suite&gt;"


def test_pdf_scheduler_leaves_notification_schedule_unchanged():
    from gestion_magasin_backend.celery_conf import app as main
    before=dict(main.conf.beat_schedule)
    from ai_assistant.pdf_beat import app
    assert app is not main
    assert set(app.conf.beat_schedule)=={"prepare-pending-pdf-translations"}
    assert dict(main.conf.beat_schedule)==before



def test_french_pdf_uses_original_source_before_reading_translation_rows():
    value = "Location STORE N° 42"
    with patch.object(PdfTextTranslation.objects, "filter") as lookup:
        assert load_pdf_translations("casa_di_lusso", [source(value)], "fr") == {value: value}

    lookup.assert_not_called()
