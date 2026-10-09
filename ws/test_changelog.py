from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from .models import ChangelogEntry
from .serializers import ChangelogEntrySerializer

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def empty_changelog():
    ChangelogEntry.objects.all().delete()


def entry(**kwargs):
    values = dict(
        date=timezone.localdate(),
        title_fr="Travail partagé",
        title_en="Shared work",
        changes_fr="  Une nouveauté.\n\nUne amélioration. ",
        changes_en=" A new feature.\n\nAn improvement. ",
        is_published=True,
    )
    return ChangelogEntry.objects.create(**(values | kwargs))


def test_authenticated_members_get_complete_bilingual_published_history_only():
    today = timezone.localdate()
    entry(date=today - timedelta(days=3))
    newest = entry(version="1.0.0")
    entry(date=today - timedelta(days=1), is_published=False, title_fr="DRAFT SECRET")
    entry(date=today + timedelta(days=1), title_fr="FUTURE SECRET")
    client = APIClient()
    client.force_authenticate(
        get_user_model().objects.create_user(
            email="changelog@example.com", password="test-only"
        )
    )
    response = client.get("/api/ws/changelog/")
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    assert len(response.data) == 2
    assert response.data[0]["id"] == newest.pk
    assert response.data[0]["version"] == "1.0.0"
    assert response.data[1]["version"] == ""
    assert response.data[0]["changes_fr"] == ["Une nouveauté.", "Une amélioration."]
    assert response.data[0]["changes_en"] == ["A new feature.", "An improvement."]
    assert "SECRET" not in str(response.data)
    assert client.post("/api/ws/changelog/", {}).status_code == 405


def test_history_requires_authentication():
    assert APIClient().get("/api/ws/changelog/").status_code in (401, 403)


def test_publication_requires_both_languages():
    draft = entry(title_en="", changes_en=" ", is_published=False)
    draft.full_clean()
    draft.is_published = True
    with pytest.raises(ValidationError):
        draft.full_clean()


@pytest.mark.parametrize("version", ["1", "01.0.0", "1.0.0-beta", "1.0.0\\n"])
def test_invalid_versions_are_rejected(version):
    with pytest.raises(ValidationError):
        entry(version=version).full_clean()


def test_complete_history_is_bilingual_idempotent_and_preserves_edits():
    import json
    from importlib import import_module
    from pathlib import Path
    from django.apps import apps
    from django.db import connection

    seed = import_module("ws.migrations.0003_seed_changelog_history")
    editor = connection.schema_editor()
    seed.seed_changelog(apps, editor)
    rows = list(ChangelogEntry.objects.order_by("date"))
    assert len(rows) == 26
    assert str(rows[0].date) == "2026-06-04"
    assert str(rows[-1].date) == "2026-10-09"
    source = json.loads(
        (Path(__file__).parents[1] / "docs/changelog-history-sources.json").read_text()
    )
    assert {commit["date"] for commit in source["commits"]} | {"2026-10-09"} == {
        str(row.date) for row in rows
    }
    assert len(source["commits"]) == 136
    for row in rows:
        row.full_clean()
        assert len(row.changes_fr.splitlines()) == len(row.changes_en.splitlines())
        assert row.version
    versions = [tuple(map(int, row.version.split("."))) for row in rows]
    assert versions == sorted(set(versions))
    assert rows[-1].version == "2.9.0"
    assert ChangelogEntry.objects.get(date="2026-06-04").version == "1.0.0"
    assert ChangelogEntry.objects.get(date="2026-06-27").version == "2.0.0"
    assert source["versioning"]["status"] == "reconstructed"
    assert len({(c["repository"], c["hash"]) for c in source["commits"]}) == 136
    first = rows[0]
    first.title_fr = "Titre conservé"
    first.is_published = False
    first.save()
    seed.seed_changelog(apps, editor)
    first.refresh_from_db()
    assert first.title_fr == "Titre conservé"
    assert not first.is_published
    assert ChangelogEntry.objects.count() == 26


def test_maintenance_version_bootstrap_and_broadcast(
    django_capture_on_commit_callbacks,
):
    from unittest.mock import AsyncMock, patch
    from .models import WsMaintenanceState

    with patch("ws.models.get_channel_layer") as layer:
        layer.return_value.group_send = AsyncMock()
        with django_capture_on_commit_callbacks(execute=True):
            WsMaintenanceState.objects.create(maintenance=False, version="0.2.0")
            layer.return_value.group_send.assert_not_called()
        layer.return_value.group_send.assert_awaited_once_with(
            "maintenance",
            {
                "type": "receive_group_message",
                "message": {
                    "type": "MAINTENANCE",
                    "maintenance": False,
                    "version": "0.2.0",
                },
            },
        )
    response = APIClient().get("/api/ws/maintenance/")
    assert response.data == {"maintenance": False, "version": "0.2.0"}
    assert response["Cache-Control"] == "no-store"


def test_bootstrap_is_public_unthrottled_and_defaults_safely():
    from .models import WsMaintenanceState
    from .views import GetMaintenanceView
    WsMaintenanceState.objects.all().delete()
    assert GetMaintenanceView.throttle_classes == ()
    response = APIClient().get("/api/ws/maintenance/")
    assert response.status_code == 200
    assert response.data == {"maintenance": False, "version": "0.1.0"}


def test_rollback_does_not_broadcast(django_capture_on_commit_callbacks):
    from django.db import transaction
    from unittest.mock import patch
    from .models import WsMaintenanceState
    with patch("ws.models.get_channel_layer") as layer:
        with django_capture_on_commit_callbacks(execute=True):
            with pytest.raises(RuntimeError), transaction.atomic():
                WsMaintenanceState.objects.create(version="2.9.0")
                raise RuntimeError("rollback")
        layer.assert_not_called()


def test_delete_announces_latest_remaining_state(django_capture_on_commit_callbacks):
    from unittest.mock import AsyncMock, patch
    from .models import WsMaintenanceState
    first = WsMaintenanceState.objects.create(version="2.8.0")
    latest = WsMaintenanceState.objects.create(version="2.9.0")
    WsMaintenanceState.objects.filter(pk=first.pk).update(updated_at=latest.updated_at)
    with patch("ws.models.get_channel_layer") as layer:
        layer.return_value.group_send = AsyncMock()
        assert APIClient().get("/api/ws/maintenance/").data["version"] == "2.9.0"
        with django_capture_on_commit_callbacks(execute=True):
            latest.delete()
            layer.return_value.group_send.assert_not_called()
        assert layer.return_value.group_send.call_args.args[1]["message"]["version"] == "2.8.0"
