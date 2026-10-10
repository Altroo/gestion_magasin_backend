"""Application wording around the shared provider; no authorization decisions."""
from chat_ai_assistant.provider import ChatAIModelService
from chat_ai_assistant.clarifications import MESSAGES, message_language

APPLICATION_MESSAGES = {
    'fr': {
        'missing_details': 'Précisez l’article, la vente, le client ou la période recherchée (avec l’année).',
        'ambiguous_metric': 'Précisez l’indicateur : ventes confirmées, montants payés, dépenses ou valeur du stock. Le solde du tableau de bord n’est pas un bénéfice comptable.',
        'unsupported': 'Précisez ce que vous souhaitez faire dans Gestion Magasin, ou utilisez /aide pour voir les fonctions disponibles.',
    },
    'en': {
        'missing_details': 'Please specify the product, sale, customer or date period (including the year).',
        'ambiguous_metric': 'Please specify confirmed sales, paid amounts, expenses or stock value. Dashboard balance is not accounting profit.',
        'unsupported': 'Please clarify what you want to do in Gestion Magasin, or use /help to see the available actions.',
    },
}


class ChatAIMagasinModelService(ChatAIModelService):
    def __init__(self, config, interface_language='fr'):
        super().__init__(config)
        self.interface_language = 'en' if interface_language == 'en' else 'fr'

    def choose(self, messages, tools, cancel=None):
        action, usage = super().choose(messages, tools, cancel)
        if action.get('tool') == 'clarify':
            reason = next((reason for variants in MESSAGES.values()
                           for reason, text in variants.items() if text == action.get('message')), None)
            if reason:
                question = next((message['content'] for message in reversed(messages)
                                 if message['role'] == 'user'), '')
                language = message_language(question, self.interface_language)
                action = {**action, 'message': APPLICATION_MESSAGES[language][reason]}
        return action, usage
