"""Proposals from the planner require a target supplied by trusted request state."""
from chat_ai_assistant.selection_context import ordinal_target_matches, explicit_target_matches
from datetime import datetime

ALIASES = {'product':r'article|product|produit', 'sale':r'vente|sale', 'customer':r'client|customer', 'expense':r'depense|expense', 'attendance':r'pointage|attendance'}


def trusted_target(resource, identifier, *, instruction, context, state, now):
    if type(identifier) is not int or identifier < 1 or not isinstance(instruction, str):
        return False
    ordinal = ordinal_target_matches(instruction, resource, identifier, state, now, ALIASES)
    if ordinal is False:
        return False
    explicit = explicit_target_matches(instruction, resource, identifier, ALIASES, ())
    if explicit is not None:
        return explicit
    if ordinal is not None:
        return ordinal
    if context.get('resource') == resource and type(context.get('identifier')) is int and context['identifier'] == identifier:
        return True
    ids = state.get('ids', [])
    expiry = state.get('expires_at')
    if state.get('resource') == resource and isinstance(ids, list) and any(type(value) is int and value == identifier for value in ids) and isinstance(expiry, str):
        try:
            expires_at = datetime.fromisoformat(expiry)
            if expires_at.utcoffset() is not None and expires_at > now:
                return True
        except (TypeError, ValueError):
            pass
    return False
