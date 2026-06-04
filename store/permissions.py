from collections.abc import Iterable

from django.core.exceptions import PermissionDenied
from rest_framework import permissions

from store.models import Role, Store, StoreMembership


WRITE_ROLES = {
    Role.Codes.DIRECTION,
    Role.Codes.RESPONSABLE,
    Role.Codes.VENDEUR,
}
MANAGEMENT_ROLES = {Role.Codes.DIRECTION, Role.Codes.RESPONSABLE}


def _role_values(roles: Iterable[str] | None) -> set[str] | None:
    if roles is None:
        return None
    return {str(role) for role in roles}


def user_store_ids(user, roles: Iterable[str] | None = None) -> list[int]:
    if not user or not user.is_authenticated:
        return []
    if user.is_staff and roles is None:
        return list(Store.objects.filter(is_active=True).values_list("id", flat=True))

    qs = StoreMembership.objects.filter(user=user, is_active=True, store__is_active=True)
    role_values = _role_values(roles)
    if role_values:
        qs = qs.filter(role__code__in=role_values)
    return list(qs.values_list("store_id", flat=True))


def user_has_store_access(user, store_id: int, roles: Iterable[str] | None = None) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_staff:
        return Store.objects.filter(pk=store_id, is_active=True).exists()
    role_values = _role_values(roles)
    qs = StoreMembership.objects.filter(
        user=user,
        store_id=store_id,
        is_active=True,
        store__is_active=True,
    )
    if role_values:
        qs = qs.filter(role__code__in=role_values)
    return qs.exists()


def get_store_from_request(request, roles: Iterable[str] | None = None) -> Store:
    raw_store_id = (
        request.query_params.get("store")
        or request.query_params.get("store_id")
        or request.data.get("store")
        or request.data.get("store_id")
    )

    if raw_store_id:
        try:
            store_id = int(raw_store_id)
        except (TypeError, ValueError):
            raise PermissionDenied("Magasin invalide.")
        if not user_has_store_access(request.user, store_id, roles=roles):
            raise PermissionDenied("Vous n'avez pas accès à ce magasin.")
        return Store.objects.get(pk=store_id, is_active=True)

    if request.user.is_staff:
        store = Store.objects.filter(is_active=True).order_by("name").first()
    else:
        membership = (
            StoreMembership.objects.filter(
                user=request.user, is_active=True, store__is_active=True
            )
            .select_related("store")
            .order_by("store__name")
            .first()
        )
        store = membership.store if membership else None

    if not store:
        raise PermissionDenied("Aucun magasin autorisé pour cet utilisateur.")
    if roles and not user_has_store_access(request.user, store.pk, roles=roles):
        raise PermissionDenied("Rôle insuffisant pour ce magasin.")
    return store


class StoreAccessPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

