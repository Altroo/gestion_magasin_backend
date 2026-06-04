from django.db.models import Q
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from catalog.models import Product
from stock.models import StockBalance, StockMovement
from stock.serializers import (
    StockAdjustmentSerializer,
    StockBalanceSerializer,
    StockMovementSerializer,
    StockThresholdSerializer,
)
from stock.services import apply_stock_movement
from gestion_magasin_backend.utils import parse_bool_csv_query_value
from store.permissions import (
    MANAGEMENT_ROLES,
    get_store_from_request,
    user_has_store_access,
    user_store_ids,
)


class StockBalanceViewSet(viewsets.ModelViewSet):
    serializer_class = StockBalanceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = StockBalance.objects.select_related("store", "product", "product__category")
        if self.request.user.is_staff:
            allowed_qs = qs
        else:
            allowed_qs = qs.filter(store_id__in=user_store_ids(self.request.user))

        store_id = self.request.query_params.get("store") or self.request.query_params.get("store_id")
        search = self.request.query_params.get("search")
        low = self.request.query_params.get("low")
        low_values = set(parse_bool_csv_query_value(low))

        if store_id:
            allowed_qs = allowed_qs.filter(store_id=store_id)
        if search:
            allowed_qs = allowed_qs.filter(
                Q(product__name__icontains=search)
                | Q(product__reference__icontains=search)
                | Q(product__barcode__icontains=search)
            )
        allowed_qs = self.apply_filters(allowed_qs)
        if low_values == {True}:
            allowed_qs = [
                balance for balance in allowed_qs if balance.is_low_stock
            ]
        elif low_values == {False}:
            allowed_qs = [
                balance for balance in allowed_qs if not balance.is_low_stock
            ]
        return allowed_qs

    def apply_filters(self, qs):
        params = self.request.query_params
        text_fields = {
            "product_name": "product__name",
            "product_reference": "product__reference",
            "product_barcode": "product__barcode",
            "category_name": "product__category__name",
            "store_name": "store__name",
        }
        for param, field in text_fields.items():
            for lookup in ("icontains", "istartswith", "iendswith"):
                value = params.get(f"{param}__{lookup}")
                if value:
                    qs = qs.filter(**{f"{field}__{lookup}": value})
            exact = params.get(param)
            if exact:
                qs = qs.filter(**{field: exact})

        numeric_fields = {
            "quantity": "quantity",
            "min_stock": "min_stock",
            "average_cost": "average_cost",
        }
        numeric_lookups = {
            "gt": "gt",
            "gte": "gte",
            "lt": "lt",
            "lte": "lte",
            "ne": None,
        }
        for param, field in numeric_fields.items():
            exact = params.get(param)
            if exact not in (None, ""):
                qs = qs.filter(**{field: exact})
            for suffix, lookup in numeric_lookups.items():
                value = params.get(f"{param}__{suffix}")
                if value in (None, ""):
                    continue
                if lookup is None:
                    qs = qs.exclude(**{field: value})
                else:
                    qs = qs.filter(**{f"{field}__{lookup}": value})

        return qs

    def get_permissions(self):
        if self.action == "create":
            return [permissions.IsAdminUser()]
        return super().get_permissions()

    def perform_destroy(self, instance):
        if not user_has_store_access(self.request.user, instance.store_id, roles=MANAGEMENT_ROLES):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied("Rôle insuffisant pour ce magasin.")
        instance.delete()

    @action(detail=False, methods=["post"], url_path="adjust")
    def adjust(self, request):
        store = get_store_from_request(request, roles=MANAGEMENT_ROLES)
        serializer = StockAdjustmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        product = Product.objects.get(pk=serializer.validated_data["product"])
        movement = apply_stock_movement(
            store=store,
            product=product,
            quantity=serializer.validated_data["quantity"],
            movement_type=serializer.validated_data["movement_type"],
            user=request.user,
            unit_cost=serializer.validated_data.get("unit_cost"),
            note=serializer.validated_data.get("note", ""),
            allow_negative=serializer.validated_data.get("allow_negative", False),
        )
        return Response(StockMovementSerializer(movement).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["patch"], url_path="threshold")
    def threshold(self, request, pk=None):
        balance = self.get_object()
        if not user_has_store_access(request.user, balance.store_id, roles=MANAGEMENT_ROLES):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied("Rôle insuffisant pour ce magasin.")
        serializer = StockThresholdSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        balance.min_stock = serializer.validated_data["min_stock"]
        balance.save(update_fields=["min_stock", "date_updated"])
        return Response(StockBalanceSerializer(balance).data)

    @action(detail=False, methods=["delete"], url_path="bulk-delete")
    def bulk_delete(self, request):
        ids = request.data.get("ids")
        if not ids or not isinstance(ids, list):
            raise ValidationError({"ids": "Une liste d'identifiants est requise."})
        try:
            balance_ids = [int(item) for item in ids]
        except (TypeError, ValueError):
            raise ValidationError({"ids": "Les identifiants doivent être des entiers."})

        qs = StockBalance.objects.filter(pk__in=balance_ids)
        if not request.user.is_staff:
            qs = qs.filter(store_id__in=user_store_ids(request.user, roles=MANAGEMENT_ROLES))
        deleted, _ = qs.delete()
        if deleted == 0:
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied("Aucun solde stock à supprimer.")
        return Response({"deleted": deleted}, status=status.HTTP_200_OK)


class StockMovementViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = StockMovementSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = StockMovement.objects.select_related("store", "product", "created_by")
        if not self.request.user.is_staff:
            qs = qs.filter(store_id__in=user_store_ids(self.request.user))
        store_id = self.request.query_params.get("store") or self.request.query_params.get("store_id")
        if store_id:
            qs = qs.filter(store_id=store_id)
        return qs
