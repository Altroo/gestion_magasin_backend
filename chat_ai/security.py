"""Native user flags, store roles and restricted application modes stay authoritative."""
import hashlib
import json
import re
from django.conf import settings
from account.models import CustomUser
from store.models import Store, StoreMembership, Role
from store.permissions import user_has_store_access, user_store_ids, MANAGEMENT_ROLES, WRITE_ROLES
from chat_ai_assistant.contracts import ChatAIError

SECRET = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:Bearer\s+)[A-Za-z0-9._-]{16,}|(?:password|api[_-]?key|secret|access[_-]?token)\s*[:=]\s*\S+", re.I)
COMMON_RESOURCES = {'product', 'stock', 'sale', 'customer', 'expense', 'inventory', 'attendance', 'employee', 'stock_request'}
STAFF_RESOURCES = {'purchase', 'transfer', 'promotion', 'store', 'user'}


def validate_text(text):
    if not isinstance(text, str) or not text.strip() or len(text) > 4000 or '\x00' in text:
        raise ChatAIError('INVALID_ARGUMENTS')
    if SECRET.search(text):
        raise ChatAIError('SENSITIVE_INPUT')
    return text.strip()


def flag(user, name):
    return bool(user.is_staff or getattr(user, 'can_' + name, False))


def vendeur_only(user):
    if user.is_staff or user.pointage_only:
        return False
    roles = list(StoreMembership.objects.filter(user=user, is_active=True, store__is_active=True, store__is_global_stock=False).values_list('role__code', flat=True))
    return bool(roles) and all(role == Role.Codes.VENDEUR for role in roles)


def selected_store_vendeur(user, store_id):
    return StoreMembership.objects.filter(user=user, store_id=store_id, is_active=True, store__is_active=True, role__code=Role.Codes.VENDEUR).exists()


def available_stores(user):
    return Store.objects.filter(pk__in=user_store_ids(user), is_active=True).order_by('name', 'pk')


def authorize_identity(user_id):
    if not settings.CHAT_AI_ASSISTANT_ENABLED:
        raise ChatAIError('APPLICATION_UNAVAILABLE')
    user = CustomUser.objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        raise ChatAIError('NOT_AUTHENTICATED')
    if not flag(user, 'view'):
        raise ChatAIError('PERMISSION_DENIED')
    return user


def authorize(user_id, company_id):
    # company_id is the shared conversation-scope field; here it stores a native Store PK.
    user = authorize_identity(user_id)
    if type(company_id) is not int or company_id < 1 or not user_has_store_access(user, company_id):
        raise ChatAIError('PERMISSION_DENIED')
    return user


def allowed_resources(user):
    if user.pointage_only:
        return {'attendance', 'employee'}
    if vendeur_only(user):
        return set()  # POS guidance/navigation only; no broader hidden module lists.
    return COMMON_RESOURCES | (STAFF_RESOURCES if user.is_staff else set())


def capabilities(user, store_id):
    result = {'read'}
    resources = allowed_resources(user)
    result.update('read_' + name for name in resources)
    if not user.pointage_only and user.is_staff:
        result.add('financial')
    if not vendeur_only(user):
        for action, native in [('print', 'print'), ('create', 'create'), ('update', 'edit'), ('delete', 'delete')]:
            if flag(user, native) or (action == 'delete' and user.pointage_only):
                result.add(action)
    if user_has_store_access(user, store_id, roles=MANAGEMENT_ROLES):
        result.add('store_management')
    if user_has_store_access(user, store_id, roles=WRITE_ROLES):
        result.add('store_write')
    if user.pointage_only:
        result.discard('print')
        result.add('attendance_only')
    if not user.pointage_only and (flag(user, 'create') or selected_store_vendeur(user, store_id)):
        result.add('pos_access')
    if not user.pointage_only and not vendeur_only(user) and flag(user,'create_promotion'):
        result.add('promotion_form')
    if vendeur_only(user):
        result.add('pos_only')
    return result


def authorize_resource(user, store_id, resource):
    if resource not in allowed_resources(user):
        raise ChatAIError('PERMISSION_DENIED')


def authorize_change(user, store_id, resource, operation):
    authorize_resource(user, store_id, resource)
    if operation not in ('update', 'delete') or operation not in capabilities(user, store_id):
        raise ChatAIError('PERMISSION_DENIED')
    roles = WRITE_ROLES if resource == 'customer' else MANAGEMENT_ROLES
    if not user_has_store_access(user, store_id, roles=roles):
        raise ChatAIError('PERMISSION_DENIED')


def authorization_stamp(user_id, company_id):
    user = authorize(user_id, company_id)
    memberships = list(StoreMembership.objects.filter(user=user).order_by('pk').values_list('pk', 'store_id', 'is_active', 'role__code', 'store__is_active', 'store__is_global_stock'))
    selected = Store.objects.values('id', 'is_active', 'is_global_stock', 'code').get(pk=company_id)
    payload = ['gestion_magasin', user.pk, user.is_staff, user.is_superuser, user.pointage_only, sorted(capabilities(user, company_id)), memberships, selected]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
