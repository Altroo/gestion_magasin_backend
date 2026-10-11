"""Clarification wording follows the current utterance, not quoted history."""
from unittest import TestCase
from unittest.mock import patch
from chat_ai_assistant.clarifications import MESSAGES
from chat_ai_assistant.planning_messages import planning_messages
from chat_ai_assistant.provider import ChatAIModelService, ModelConfig
from .provider import ChatAIMagasinModelService, APPLICATION_MESSAGES


class PlannerLanguageTests(TestCase):
    def test_language_switch_with_actual_planner_envelope(self):
        model = ChatAIMagasinModelService(ModelConfig('http://127.0.0.1:1/v1', 'fixture'))
        for current, old, language in (
            ('Affiche les revenus de mars.', 'Find quotes from March.', 'fr'),
            ('Find quotes from March.', 'Affiche les revenus de mars.', 'en'),
        ):
            for reason in MESSAGES['fr']:
                with self.subTest(language=language, reason=reason):
                    messages = planning_messages('Rules', {}, current, [{'role': 'user', 'content': old}])
                    with patch.object(ChatAIModelService, 'choose', return_value=(
                        {'tool': 'clarify', 'message': MESSAGES['en'][reason]}, {}
                    )):
                        action, _ = model.choose(messages, [])
                    self.assertEqual(action['message'], APPLICATION_MESSAGES[language][reason])
