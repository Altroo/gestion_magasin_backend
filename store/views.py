from django.db.models import Count, Q
from django.http import Http404
from django.utils.translation import gettext_lazy as _
from rest_framework import permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from gestion_magasin_backend.utils import CustomPagination
from store.filters import StoreFilter, StoreMembershipFilter
from store.models import Role, Store, StoreMembership
from store.permissions import user_store_ids
from store.serializers import (
    RoleSerializer,
    StoreDetailSerializer,
    StoreMembershipSerializer,
    StoreSerializer,
    UserStoreSerializer,
)


STORE_BUSINESS_DEPENDENCIES = (
    ("stock_balances", _("stock")),
    ("stock_movements", _("mouvements de stock")),
    ("stock_transfers_received", _("transferts de stock")),
    ("purchases", _("achats")),
    ("inventory_sessions", _("inventaires")),
    ("sales", _("ventes")),
    ("customers", _("clients")),
    ("promotions", _("promotions")),
    ("expenses", _("dépenses")),
    ("employees", _("employés")),
    ("attendance_records", _("pointages")),
    ("attendance_imports", _("imports pointage")),
    ("product_imports", _("imports articles")),
)


def _store_business_dependency_labels(store):
    labels = []
    for related_name, label in STORE_BUSINESS_DEPENDENCIES:
        manager = getattr(store, related_name, None)
        if manager is not None and manager.exists():
            labels.append(str(label))
    return labels


def _ensure_store_can_be_deleted(store):
    if store.is_global_stock:
        raise ValidationError(
            {"store": _("Le stock MBR ne peut pas être supprimé.")}
        )

    labels = _store_business_dependency_labels(store)
    if labels:
        dependencies = ", ".join(labels[:5])
        if len(labels) > 5:
            dependencies = f"{dependencies}, ..."
        raise ValidationError(
            {
                "store": _(
                    "Impossible de supprimer ce magasin car il contient déjà des données : %(dependencies)s. Désactivez-le plutôt."
                )
                % {"dependencies": dependencies}
            }
        )


def _filtered_stores_for_user(request):
    queryset = Store.objects.annotate(members_count=Count("memberships")).order_by(
        "name"
    ).exclude(Q(is_global_stock=True) | Q(code="mbr-south"))
    if not request.user.is_staff:
        queryset = queryset.filter(id__in=user_store_ids(request.user))
    return StoreFilter(request.query_params, queryset=queryset).qs


class RoleListView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request, *args, **kwargs):
        paginator = CustomPagination()
        queryset = Role.objects.all().order_by("rank", "name")
        page = paginator.paginate_queryset(queryset, request)
        serializer = RoleSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class StoreListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get_permissions(self):
        if self.request.method == "POST":
            return [permissions.IsAdminUser()]
        return super().get_permissions()

    @staticmethod
    def get(request, *args, **kwargs):
        paginator = CustomPagination()
        page = paginator.paginate_queryset(_filtered_stores_for_user(request), request)
        serializer = StoreSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @staticmethod
    def post(request, *args, **kwargs):
        serializer = StoreDetailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        store = serializer.save()
        return Response(
            StoreDetailSerializer(store).data,
            status=status.HTTP_201_CREATED,
        )


class StoreDetailEditDeleteView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get_permissions(self):
        if self.request.method in {"PUT", "PATCH", "DELETE"}:
            return [permissions.IsAdminUser()]
        return super().get_permissions()

    def get_object(self, pk):
        try:
            return _filtered_stores_for_user(self.request).get(pk=pk)
        except Store.DoesNotExist:
            raise Http404(_("Aucun magasin ne correspond à la requête."))

    def get(self, request, pk, *args, **kwargs):
        serializer = StoreDetailSerializer(self.get_object(pk))
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, pk, *args, **kwargs):
        store = self.get_object(pk)
        serializer = StoreDetailSerializer(store, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, pk, *args, **kwargs):
        store = self.get_object(pk)
        serializer = StoreDetailSerializer(store, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, pk, *args, **kwargs):
        store = self.get_object(pk)
        _ensure_store_can_be_deleted(store)
        store.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class BulkDeleteStoresView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    @staticmethod
    def delete(request, *args, **kwargs):
        ids = request.data.get("ids")
        if not ids or not isinstance(ids, list):
            raise ValidationError({"ids": _("Une liste d'identifiants est requise.")})

        try:
            ids = [int(item) for item in ids]
        except (TypeError, ValueError):
            raise ValidationError({"ids": _("Les identifiants doivent être entiers.")})

        stores = list(Store.objects.filter(pk__in=ids))
        if len(stores) != len(set(ids)):
            raise ValidationError({"ids": _("Certains magasins sont introuvables.")})

        for store in stores:
            _ensure_store_can_be_deleted(store)

        deleted, _deleted_breakdown = Store.objects.filter(pk__in=ids).delete()
        return Response({"deleted": deleted}, status=status.HTTP_200_OK)


class MyStoresView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request, *args, **kwargs):
        if request.user.is_staff:
            direction_role = Role.objects.get(code=Role.Codes.DIRECTION)
            stores = Store.objects.filter(is_active=True).order_by("name")
            return Response(
                [
                    {
                        "id": store.id,
                        "store": StoreSerializer(store).data,
                        "role": RoleSerializer(direction_role).data,
                        "is_active": True,
                    }
                    for store in stores
                ],
                status=status.HTTP_200_OK,
            )

        memberships = (
            StoreMembership.objects.filter(
                user=request.user, is_active=True, store__is_active=True
            )
            .select_related("store", "role")
            .order_by("store__name")
        )
        return Response(
            UserStoreSerializer(memberships, many=True).data,
            status=status.HTTP_200_OK,
        )


class StoreMembershipListCreateView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    @staticmethod
    def get(request, *args, **kwargs):
        paginator = CustomPagination()
        queryset = StoreMembership.objects.select_related(
            "user", "store", "role"
        ).order_by("store__name", "user__email")
        queryset = StoreMembershipFilter(request.query_params, queryset=queryset).qs
        page = paginator.paginate_queryset(queryset, request)
        serializer = StoreMembershipSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @staticmethod
    def post(request, *args, **kwargs):
        serializer = StoreMembershipSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = serializer.save()
        return Response(
            StoreMembershipSerializer(membership).data,
            status=status.HTTP_201_CREATED,
        )


class StoreMembershipDetailEditDeleteView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    @staticmethod
    def get_object(pk):
        try:
            return StoreMembership.objects.select_related("user", "store", "role").get(
                pk=pk
            )
        except StoreMembership.DoesNotExist:
            raise Http404(_("Aucune permission magasin ne correspond à la requête."))

    def get(self, request, pk, *args, **kwargs):
        return Response(
            StoreMembershipSerializer(self.get_object(pk)).data,
            status=status.HTTP_200_OK,
        )

    def put(self, request, pk, *args, **kwargs):
        membership = self.get_object(pk)
        serializer = StoreMembershipSerializer(membership, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, pk, *args, **kwargs):
        membership = self.get_object(pk)
        serializer = StoreMembershipSerializer(membership, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, pk, *args, **kwargs):
        self.get_object(pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
