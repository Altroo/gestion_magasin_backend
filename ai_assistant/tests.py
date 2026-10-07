import hashlib
import hmac
import json
from unittest.mock import patch, MagicMock

import pytest
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from account.models import CustomUser
from .client import AiAssistantClient
from .exceptions import InvalidModelResponse, AssistantDisabled

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def ai_settings(settings):
    settings.AI_ASSISTANT_ENABLED = True
    settings.AI_ASSISTANT_SERVICE_NAME = "gestion_magasin"
    settings.AI_ASSISTANT_SERVICE_SECRET = "local-test-secret"
    settings.AI_ASSISTANT_GATEWAY_URL = "http://ai-assistant-gateway:8080"
    settings.AI_ASSISTANT_TIMEOUT_SECONDS = 185


def test_signed_gateway_request_uses_exact_body_and_unique_identifier():
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(
        {"suggested_text": "Texte corrigé", "detected_language": "fr"}
    ).encode()
    with patch("ai_assistant.client.request.urlopen", return_value=response) as send:
        client = AiAssistantClient()
        result = client.assist(action="fix_grammar", text="Texte corrige")
        first = send.call_args.args[0]
        client.assist(action="fix_grammar", text="Texte corrige")
        second = send.call_args.args[0]
    headers = {key.lower(): value for key, value in first.header_items()}
    canonical = f"{headers['x-ai-timestamp']}\n{headers['x-ai-service']}\n{headers['x-ai-request-id']}\n{hashlib.sha256(first.data).hexdigest()}"
    assert (
        headers["x-ai-signature"]
        == hmac.new(
            b"local-test-secret", canonical.encode(), hashlib.sha256
        ).hexdigest()
    )
    assert first.full_url == "http://ai-assistant-gateway:8080/v1/assist"
    assert headers["x-ai-request-id"] != second.get_header("X-ai-request-id")
    assert result["original_text"] == "Texte corrige"


def test_pdf_translation_deduplicates_and_bounds_batches():
    captured = []

    def translate(endpoint, payload):
        captured.append(payload)
        return {"translations": ["NL " + text for text in payload["texts"]]}

    values = [f"Désignation {i}" for i in range(35)]
    with patch.object(AiAssistantClient, "_post", side_effect=translate):
        translated = AiAssistantClient().translate_many(
            values + values, target_language="nl"
        )
    assert len(translated) == 35
    assert len(captured) == 3
    assert all(len(p["texts"]) <= 15 for p in captured)
    assert all(p["target_language"] == "nl" for p in captured)


def test_long_text_retains_spacing_when_gateway_returns_identical_text():
    value = " " * 6000 + "Description détaillée.\n" * 300
    with patch.object(
        AiAssistantClient,
        "_post",
        side_effect=lambda endpoint, payload: {
            "translations": [t.strip() for t in payload["texts"]]
        },
    ):
        result = AiAssistantClient().translate_many([value], target_language="fr")
    assert result[value] == value


def test_translation_rejects_missing_or_blank_output():
    with patch.object(AiAssistantClient, "_post", return_value={"translations": []}):
        with pytest.raises(InvalidModelResponse):
            AiAssistantClient().translate_many(["Chaise"], target_language="en")


def test_assistant_is_authenticated_validates_action_and_only_returns_a_preview():
    api = APIClient()
    url = reverse("ai_assistant:assist")
    payload = {"action": "fix_grammar", "text": "Texte corrige"}
    assert api.post(url, payload, format="json").status_code in (401, 403)
    user = CustomUser.objects.create_user(
        email="assistant@example.test", password="test-pass"
    )
    api.force_authenticate(user)
    with patch(
        "ai_assistant.views.AiAssistantClient.assist",
        return_value={
            "original_text": "Texte corrige",
            "suggested_text": "Texte corrigé",
        },
    ) as assist:
        response = api.post(url, payload, format="json")
        invalid = api.post(url, {**payload, "action": "change_prices"}, format="json")
    assert response.status_code == 200
    assert response.data["suggested_text"] == "Texte corrigé"
    assert invalid.status_code == 400
    assert assist.call_count == 1


def test_missing_service_key_fails_without_network(settings):
    settings.AI_ASSISTANT_SERVICE_SECRET = ""
    with patch("ai_assistant.client.request.urlopen") as send:
        with pytest.raises(AssistantDisabled):
            AiAssistantClient().assist(action="fix_grammar", text="Texte")
    send.assert_not_called()


def test_pdf_batch_waits_for_existing_rate_limit_before_retrying():
    from rest_framework.exceptions import Throttled

    with patch.object(
        AiAssistantClient,
        "_post",
        side_effect=[Throttled(wait=60), {"translations": ["Chair"]}],
    ) as send, patch("ai_assistant.client.time.sleep") as sleep:
        result = AiAssistantClient().translate_many(["Chaise"], target_language="en")
    assert result == {"Chaise": "Chair"}
    sleep.assert_called_once_with(60.1)
    assert send.call_count == 2


def test_ai_rate_limit_is_separate_from_page_requests_and_still_enforced():
    from types import SimpleNamespace
    from rest_framework.throttling import UserRateThrottle
    from .views import AssistantThrottle

    request = SimpleNamespace(user=SimpleNamespace(is_authenticated=True, pk=999123))
    ordinary = UserRateThrottle()
    assistant = AssistantThrottle()
    ordinary_key = ordinary.get_cache_key(request, None)
    ai_key = assistant.get_cache_key(request, None)
    assert ordinary_key != ai_key
    assistant.cache.delete(ai_key)
    ordinary.cache.set(ordinary_key, [ordinary.timer()] * 30, 60)
    try:
        for _ in range(10):
            assert AssistantThrottle().allow_request(request, None)
        assert not AssistantThrottle().allow_request(request, None)
    finally:
        ordinary.cache.delete(ordinary_key)
        assistant.cache.delete(ai_key)
