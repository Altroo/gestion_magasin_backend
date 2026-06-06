from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog.models import Product
from gestion_magasin_backend.utils import CustomPagination, parse_bool_csv_query_value
from store.models import Store
from stock.models import (
    InventoryLine,
    InventorySession,
    Purchase,
    PurchaseLine,
    StockBalance,
    StockMovement,
    StockTransfer,
    StockTransferLine,
)
from stock.serializers import (
    InventorySessionCreateSerializer,
    InventorySessionSerializer,
    PurchaseCreateSerializer,
    PurchaseSerializer,
    StockAdjustmentSerializer,
    StockBalanceSerializer,
    StockMovementSerializer,
    StockThresholdSerializer,
    StockTransferCreateSerializer,
    StockTransferSerializer,
)
from stock.services import (
    apply_stock_movement,
    receive_purchase,
    validate_inventory_session,
)
from stock.services import validate_stock_transfer
from store.permissions import (
    MANAGEMENT_ROLES,
    get_global_stock_store_from_request,
    get_store_from_request,
    user_has_store_access,
    user_store_ids,
)


def _paginate(request, queryset, serializer_class):
    paginator = CustomPagination()
    page = paginator.paginate_queryset(queryset, request)
    serializer = serializer_class(page, many=True, context={"request": request})
    return paginator.get_paginated_response(serializer.data)


def _stock_balance_base_queryset(request):
    queryset = StockBalance.objects.select_related(
        "store", "product", "product__category", "product__unit"
    )
    if request.user.is_staff:
        return queryset
    return queryset.filter(store_id__in=user_store_ids(request.user))


def _stock_balance_queryset(request):
    queryset = _stock_balance_base_queryset(request)
    store_id = request.query_params.get("store") or request.query_params.get("store_id")
    search = request.query_params.get("search")
    low_values = set(parse_bool_csv_query_value(request.query_params.get("low")))

    if store_id:
        queryset = queryset.filter(store_id=store_id)
    if search:
        queryset = queryset.filter(
            Q(product__name__icontains=search)
            | Q(product__reference__icontains=search)
            | Q(product__barcode__icontains=search)
            | Q(store__name__icontains=search)
        )

    queryset = _apply_stock_balance_filters(request, queryset)
    if low_values == {True}:
        return [balance for balance in queryset if balance.is_low_stock]
    if low_values == {False}:
        return [balance for balance in queryset if not balance.is_low_stock]
    return queryset


def _apply_stock_balance_filters(request, queryset):
    params = request.query_params
    store_ids = _parse_int_csv(params.get("store_ids"))
    category_ids = _parse_int_csv(params.get("category_ids"))
    unit_ids = _parse_int_csv(params.get("unit_ids"))
    exclude_global_values = set(parse_bool_csv_query_value(params.get("exclude_global_stock")))
    if store_ids:
        queryset = queryset.filter(store_id__in=store_ids)
    if exclude_global_values == {True}:
        queryset = queryset.filter(store__is_global_stock=False)
    elif exclude_global_values == {False}:
        queryset = queryset.filter(store__is_global_stock=True)
    if category_ids:
        queryset = queryset.filter(product__category_id__in=category_ids)
    if unit_ids:
        queryset = queryset.filter(product__unit_id__in=unit_ids)

    text_fields = {
        "product_name": "product__name",
        "product_reference": "product__reference",
        "product_barcode": "product__barcode",
        "category_name": "product__category__name",
        "unit_name": "product__unit__name",
        "store_name": "store__name",
    }
    for param, field in text_fields.items():
        for lookup in ("icontains", "istartswith", "iendswith"):
            value = params.get(f"{param}__{lookup}")
            if value:
                queryset = queryset.filter(**{f"{field}__{lookup}": value})
        exact = params.get(param)
        if exact:
            queryset = queryset.filter(**{field: exact})

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
            queryset = queryset.filter(**{field: exact})
        for suffix, lookup in numeric_lookups.items():
            value = params.get(f"{param}__{suffix}")
            if value in (None, ""):
                continue
            if lookup is None:
                queryset = queryset.exclude(**{field: value})
            else:
                queryset = queryset.filter(**{f"{field}__{lookup}": value})
    return queryset


def _parse_int_csv(value):
    if not value:
        return []
    ids = []
    for item in str(value).split(","):
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids


def _get_stock_balance_for_user(request, pk):
    try:
        return _stock_balance_base_queryset(request).get(pk=pk)
    except StockBalance.DoesNotExist:
        raise Http404(_("Aucun solde stock ne correspond à la requête."))


def _ensure_balance_management_access(user, balance):
    if not user_has_store_access(user, balance.store_id, roles=MANAGEMENT_ROLES):
        raise PermissionDenied("Rôle insuffisant pour ce magasin.")


def _ensure_store_management_access(user, store_id):
    if not user_has_store_access(user, store_id, roles=MANAGEMENT_ROLES):
        raise PermissionDenied("Rôle insuffisant pour ce magasin.")


def _ensure_global_stock_store(store):
    if not store.is_global_stock:
        raise PermissionDenied("Les entrées de stock doivent utiliser MBR Stock.")


def _target_store_for_transfer(request, store_id):
    try:
        store = Store.objects.get(pk=store_id, is_active=True, is_global_stock=False)
    except Store.DoesNotExist as exc:
        raise ValidationError(
            {"target_store": ["Magasin destination invalide."]}
        ) from exc
    if not user_has_store_access(request.user, store.pk, roles=MANAGEMENT_ROLES):
        raise PermissionDenied("Rôle insuffisant pour ce magasin.")
    return store


class StockBalanceListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get_permissions(self):
        if self.request.method == "POST":
            return [permissions.IsAdminUser()]
        return super().get_permissions()

    @staticmethod
    def get(request, *args, **kwargs):
        return _paginate(
            request, _stock_balance_queryset(request), StockBalanceSerializer
        )

    @staticmethod
    def post(request, *args, **kwargs):
        serializer = StockBalanceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _ensure_global_stock_store(serializer.validated_data["store"])
        balance = serializer.save()
        return Response(
            StockBalanceSerializer(balance).data, status=status.HTTP_201_CREATED
        )


class StockBalanceDetailEditDeleteView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, pk, *args, **kwargs):
        balance = _get_stock_balance_for_user(request, pk)
        return Response(StockBalanceSerializer(balance).data, status=status.HTTP_200_OK)

    def put(self, request, pk, *args, **kwargs):
        balance = _get_stock_balance_for_user(request, pk)
        _ensure_balance_management_access(request.user, balance)
        serializer = StockBalanceSerializer(balance, data=request.data)
        serializer.is_valid(raise_exception=True)
        next_store = serializer.validated_data.get("store", balance.store)
        _ensure_global_stock_store(next_store)
        if not user_has_store_access(
            request.user, next_store.pk, roles=MANAGEMENT_ROLES
        ):
            raise PermissionDenied("Rôle insuffisant pour ce magasin.")
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, pk, *args, **kwargs):
        balance = _get_stock_balance_for_user(request, pk)
        _ensure_balance_management_access(request.user, balance)
        serializer = StockBalanceSerializer(balance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        next_store = serializer.validated_data.get("store", balance.store)
        if set(request.data.keys()) - {"min_stock"}:
            _ensure_global_stock_store(next_store)
        if not user_has_store_access(
            request.user, next_store.pk, roles=MANAGEMENT_ROLES
        ):
            raise PermissionDenied("Rôle insuffisant pour ce magasin.")
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, pk, *args, **kwargs):
        balance = _get_stock_balance_for_user(request, pk)
        _ensure_balance_management_access(request.user, balance)
        balance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class StockAdjustmentView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def post(request, *args, **kwargs):
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
        return Response(
            StockMovementSerializer(movement).data, status=status.HTTP_201_CREATED
        )


class StockThresholdUpdateView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def patch(request, pk, *args, **kwargs):
        balance = _get_stock_balance_for_user(request, pk)
        _ensure_balance_management_access(request.user, balance)
        serializer = StockThresholdSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        balance.min_stock = serializer.validated_data["min_stock"]
        balance.save(update_fields=["min_stock", "date_updated"])
        return Response(StockBalanceSerializer(balance).data, status=status.HTTP_200_OK)


class BulkDeleteStockBalancesView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def delete(request, *args, **kwargs):
        ids = request.data.get("ids")
        if not ids or not isinstance(ids, list):
            raise ValidationError({"ids": "Une liste d'identifiants est requise."})
        try:
            balance_ids = [int(item) for item in ids]
        except (TypeError, ValueError):
            raise ValidationError({"ids": "Les identifiants doivent être des entiers."})

        queryset = StockBalance.objects.filter(pk__in=balance_ids)
        if not request.user.is_staff:
            queryset = queryset.filter(
                store_id__in=user_store_ids(request.user, roles=MANAGEMENT_ROLES)
            )
        deleted, _deleted_breakdown = queryset.delete()
        if deleted == 0:
            raise PermissionDenied("Aucun solde stock à supprimer.")
        return Response({"deleted": deleted}, status=status.HTTP_200_OK)


def _stock_movement_queryset(request):
    queryset = StockMovement.objects.select_related("store", "product", "created_by")
    if not request.user.is_staff:
        queryset = queryset.filter(store_id__in=user_store_ids(request.user))
    store_id = request.query_params.get("store") or request.query_params.get("store_id")
    if store_id:
        queryset = queryset.filter(store_id=store_id)
    return queryset


class StockMovementListView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request, *args, **kwargs):
        return _paginate(
            request, _stock_movement_queryset(request), StockMovementSerializer
        )


class StockMovementDetailView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request, pk, *args, **kwargs):
        try:
            movement = _stock_movement_queryset(request).get(pk=pk)
        except StockMovement.DoesNotExist:
            raise Http404(_("Aucun mouvement stock ne correspond à la requête."))
        return Response(
            StockMovementSerializer(movement).data, status=status.HTTP_200_OK
        )


def _stock_transfer_queryset(request):
    queryset = StockTransfer.objects.select_related(
        "target_store",
        "created_by",
        "validated_by",
    ).prefetch_related("lines", "lines__product")
    if not request.user.is_staff:
        allowed_ids = user_store_ids(request.user)
        queryset = queryset.filter(target_store_id__in=allowed_ids)
    store_id = request.query_params.get("store") or request.query_params.get("store_id")
    if store_id:
        queryset = queryset.filter(target_store_id=store_id)
    target_store_ids = _parse_int_csv(
        request.query_params.get("target_store_ids")
        or request.query_params.get("target_store")
        or request.query_params.get("target_store_id")
    )
    if target_store_ids:
        queryset = queryset.filter(target_store_id__in=target_store_ids)

    search = request.query_params.get("search")
    if search:
        queryset = queryset.filter(
            Q(reference__icontains=search)
            | Q(note__icontains=search)
            | Q(target_store__name__icontains=search)
            | Q(lines__product__name__icontains=search)
            | Q(lines__product__reference__icontains=search)
        ).distinct()

    status_value = request.query_params.get("status")
    if status_value:
        queryset = queryset.filter(
            status__in=[
                item.strip() for item in str(status_value).split(",") if item.strip()
            ]
        )
    return queryset


def _get_stock_transfer_for_user(request, pk):
    try:
        return _stock_transfer_queryset(request).get(pk=pk)
    except StockTransfer.DoesNotExist:
        raise Http404(_("Aucun transfert stock ne correspond à la requête."))


@transaction.atomic
def _create_transfer_from_validated_data(*, source_store, target_store, user, data):
    lines_data = data.pop("lines")
    should_validate = data.get("status") == StockTransfer.Statuses.VALIDATED
    if should_validate:
        data["status"] = StockTransfer.Statuses.DRAFT
    transfer = StockTransfer.objects.create(
        target_store=target_store,
        reference=data.get("reference", ""),
        transfer_date=data.get("transfer_date") or timezone.localdate(),
        status=data.get("status", StockTransfer.Statuses.DRAFT),
        note=data.get("note", ""),
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    for line_data in lines_data:
        try:
            product = Product.objects.get(pk=line_data["product"], is_active=True)
        except Product.DoesNotExist as exc:
            raise ValidationError({"product": ["Article introuvable."]}) from exc
        StockTransferLine.objects.create(
            transfer=transfer,
            product=product,
            quantity=line_data["quantity"],
        )
    if should_validate:
        transfer = validate_stock_transfer(transfer=transfer, user=user, source_store=source_store)
    return transfer


class StockTransferListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request, *args, **kwargs):
        return _paginate(
            request, _stock_transfer_queryset(request), StockTransferSerializer
        )

    @staticmethod
    def post(request, *args, **kwargs):
        source_store = get_global_stock_store_from_request(request, roles=MANAGEMENT_ROLES)
        serializer = StockTransferCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target_store = _target_store_for_transfer(
            request,
            serializer.validated_data["target_store"],
        )
        transfer = _create_transfer_from_validated_data(
            source_store=source_store,
            target_store=target_store,
            user=request.user,
            data=dict(serializer.validated_data),
        )
        return Response(
            StockTransferSerializer(transfer).data,
            status=status.HTTP_201_CREATED,
        )


class StockTransferDetailEditDeleteView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, pk, *args, **kwargs):
        return Response(
            StockTransferSerializer(_get_stock_transfer_for_user(request, pk)).data,
            status=status.HTTP_200_OK,
        )

    def put(self, request, pk, *args, **kwargs):
        transfer = _get_stock_transfer_for_user(request, pk)
        source_store = get_global_stock_store_from_request(request, roles=MANAGEMENT_ROLES)
        if transfer.status == StockTransfer.Statuses.VALIDATED:
            raise ValidationError(
                {"status": ["Un transfert validé ne peut plus être modifié."]}
            )
        serializer = StockTransferCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target_store = _target_store_for_transfer(
            request,
            serializer.validated_data["target_store"],
        )
        with transaction.atomic():
            transfer.lines.all().delete()
            data = dict(serializer.validated_data)
            lines_data = data.pop("lines")
            transfer.target_store = target_store
            transfer.reference = data.get("reference", "")
            transfer.transfer_date = data.get("transfer_date") or transfer.transfer_date
            transfer.status = data.get("status", StockTransfer.Statuses.DRAFT)
            transfer.note = data.get("note", "")
            transfer.save()
            for line_data in lines_data:
                product = Product.objects.get(pk=line_data["product"], is_active=True)
                StockTransferLine.objects.create(
                    transfer=transfer,
                    product=product,
                    quantity=line_data["quantity"],
                )
        if transfer.status == StockTransfer.Statuses.VALIDATED:
            transfer.status = StockTransfer.Statuses.DRAFT
            transfer.save(update_fields=["status", "date_updated"])
            transfer = validate_stock_transfer(transfer=transfer, user=request.user, source_store=source_store)
        return Response(
            StockTransferSerializer(transfer).data, status=status.HTTP_200_OK
        )

    def delete(self, request, pk, *args, **kwargs):
        transfer = _get_stock_transfer_for_user(request, pk)
        get_global_stock_store_from_request(request, roles=MANAGEMENT_ROLES)
        if transfer.status == StockTransfer.Statuses.VALIDATED:
            raise ValidationError(
                {"status": ["Un transfert validé ne peut pas être supprimé."]}
            )
        transfer.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class StockTransferValidateView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def post(request, pk, *args, **kwargs):
        transfer = _get_stock_transfer_for_user(request, pk)
        source_store = get_global_stock_store_from_request(request, roles=MANAGEMENT_ROLES)
        transfer = validate_stock_transfer(transfer=transfer, user=request.user, source_store=source_store)
        return Response(
            StockTransferSerializer(transfer).data, status=status.HTTP_200_OK
        )


class BulkDeleteStockTransfersView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def delete(request, *args, **kwargs):
        ids = request.data.get("ids")
        if not ids or not isinstance(ids, list):
            raise ValidationError({"ids": "Une liste d'identifiants est requise."})
        queryset = StockTransfer.objects.filter(pk__in=ids).exclude(
            status=StockTransfer.Statuses.VALIDATED
        )
        if not request.user.is_staff:
            queryset = queryset.filter(
                target_store_id__in=user_store_ids(request.user, roles=MANAGEMENT_ROLES)
            )
        deleted, _deleted_breakdown = queryset.delete()
        if deleted == 0:
            raise PermissionDenied("Aucun transfert à supprimer.")
        return Response({"deleted": deleted}, status=status.HTTP_200_OK)


def _purchase_queryset(request):
    queryset = Purchase.objects.select_related(
        "store", "created_by", "received_by"
    ).prefetch_related(
        "lines",
        "lines__product",
    )
    if not request.user.is_staff:
        queryset = queryset.filter(store_id__in=user_store_ids(request.user))
    store_id = request.query_params.get("store") or request.query_params.get("store_id")
    if store_id:
        queryset = queryset.filter(store_id=store_id)
    store_ids = _parse_int_csv(
        request.query_params.get("store_ids")
        or request.query_params.get("stores")
    )
    if store_ids:
        queryset = queryset.filter(store_id__in=store_ids)
    supplier_names = [
        item.strip()
        for item in str(
            request.query_params.get("supplier_names")
            or request.query_params.get("suppliers")
            or ""
        ).split(",")
        if item.strip()
    ]
    if supplier_names:
        supplier_query = Q()
        for supplier_name in supplier_names:
            supplier_query |= Q(supplier_name__iexact=supplier_name)
        queryset = queryset.filter(supplier_query)

    search = request.query_params.get("search")
    if search:
        queryset = queryset.filter(
            Q(reference__icontains=search)
            | Q(supplier_name__icontains=search)
            | Q(note__icontains=search)
            | Q(lines__product__name__icontains=search)
            | Q(lines__product__reference__icontains=search)
        ).distinct()

    for field in ("status",):
        value = request.query_params.get(field)
        if value:
            queryset = queryset.filter(
                **{
                    f"{field}__in": [
                        item.strip() for item in str(value).split(",") if item.strip()
                    ]
                }
            )

    date_after = request.query_params.get("purchase_date_after")
    date_before = request.query_params.get("purchase_date_before")
    if date_after:
        queryset = queryset.filter(purchase_date__gte=date_after)
    if date_before:
        queryset = queryset.filter(purchase_date__lte=date_before)
    return queryset


def _get_purchase_for_user(request, pk):
    try:
        return _purchase_queryset(request).get(pk=pk)
    except Purchase.DoesNotExist:
        raise Http404(_("Aucun achat ne correspond à la requête."))


@transaction.atomic
def _create_purchase_from_validated_data(*, store, user, data):
    lines_data = data.pop("lines")
    should_receive = data.get("status") == Purchase.Statuses.RECEIVED
    if should_receive:
        data["status"] = Purchase.Statuses.DRAFT
    purchase = Purchase.objects.create(
        store=store,
        supplier_name=data.get("supplier_name", ""),
        reference=data.get("reference", ""),
        purchase_date=data.get("purchase_date") or timezone.localdate(),
        status=data.get("status", Purchase.Statuses.DRAFT),
        note=data.get("note", ""),
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    subtotal = 0
    for line_data in lines_data:
        try:
            product = Product.objects.get(pk=line_data["product"], is_active=True)
        except Product.DoesNotExist as exc:
            raise ValidationError({"product": ["Article introuvable."]}) from exc
        line = PurchaseLine.objects.create(
            purchase=purchase,
            product=product,
            quantity=line_data["quantity"],
            unit_cost=line_data["unit_cost"],
        )
        subtotal += line.total
    purchase.subtotal = subtotal
    purchase.save(update_fields=["subtotal", "date_updated"])
    if should_receive:
        purchase = receive_purchase(purchase=purchase, user=user)
    return purchase


class PurchaseListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request, *args, **kwargs):
        return _paginate(request, _purchase_queryset(request), PurchaseSerializer)

    @staticmethod
    def post(request, *args, **kwargs):
        serializer = PurchaseCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        store = get_store_from_request(request, roles=MANAGEMENT_ROLES)
        purchase = _create_purchase_from_validated_data(
            store=store,
            user=request.user,
            data=dict(serializer.validated_data),
        )
        return Response(
            PurchaseSerializer(purchase).data, status=status.HTTP_201_CREATED
        )


class PurchaseDetailEditDeleteView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, pk, *args, **kwargs):
        return Response(
            PurchaseSerializer(_get_purchase_for_user(request, pk)).data,
            status=status.HTTP_200_OK,
        )

    def put(self, request, pk, *args, **kwargs):
        purchase = _get_purchase_for_user(request, pk)
        _ensure_store_management_access(request.user, purchase.store_id)
        if purchase.status == Purchase.Statuses.RECEIVED:
            raise ValidationError(
                {"status": ["Un achat réceptionné ne peut plus être modifié."]}
            )
        serializer = PurchaseCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            next_store = get_store_from_request(request, roles=MANAGEMENT_ROLES)
            purchase.lines.all().delete()
            data = dict(serializer.validated_data)
            lines_data = data.pop("lines")
            purchase.store = next_store
            purchase.supplier_name = data.get("supplier_name", "")
            purchase.reference = data.get("reference", "")
            purchase.purchase_date = data.get("purchase_date") or purchase.purchase_date
            purchase.status = data.get("status", Purchase.Statuses.DRAFT)
            purchase.note = data.get("note", "")
            subtotal = 0
            for line_data in lines_data:
                product = Product.objects.get(pk=line_data["product"], is_active=True)
                line = PurchaseLine.objects.create(
                    purchase=purchase,
                    product=product,
                    quantity=line_data["quantity"],
                    unit_cost=line_data["unit_cost"],
                )
                subtotal += line.total
            purchase.subtotal = subtotal
            purchase.save()
        if purchase.status == Purchase.Statuses.RECEIVED:
            purchase.status = Purchase.Statuses.DRAFT
            purchase.save(update_fields=["status", "date_updated"])
            purchase = receive_purchase(purchase=purchase, user=request.user)
        return Response(PurchaseSerializer(purchase).data, status=status.HTTP_200_OK)

    def delete(self, request, pk, *args, **kwargs):
        purchase = _get_purchase_for_user(request, pk)
        _ensure_store_management_access(request.user, purchase.store_id)
        if purchase.status == Purchase.Statuses.RECEIVED:
            raise ValidationError(
                {"status": ["Un achat réceptionné ne peut pas être supprimé."]}
            )
        purchase.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PurchaseReceiveView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def post(request, pk, *args, **kwargs):
        purchase = _get_purchase_for_user(request, pk)
        _ensure_store_management_access(request.user, purchase.store_id)
        purchase = receive_purchase(purchase=purchase, user=request.user)
        return Response(PurchaseSerializer(purchase).data, status=status.HTTP_200_OK)


class BulkDeletePurchasesView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def delete(request, *args, **kwargs):
        ids = request.data.get("ids")
        if not ids or not isinstance(ids, list):
            raise ValidationError({"ids": "Une liste d'identifiants est requise."})
        queryset = Purchase.objects.filter(pk__in=ids).exclude(
            status=Purchase.Statuses.RECEIVED
        )
        if not request.user.is_staff:
            queryset = queryset.filter(
                store_id__in=user_store_ids(request.user, roles=MANAGEMENT_ROLES)
            )
        deleted, _deleted_breakdown = queryset.delete()
        if deleted == 0:
            raise PermissionDenied("Aucun achat à supprimer.")
        return Response({"deleted": deleted}, status=status.HTTP_200_OK)


def _inventory_queryset(request):
    queryset = InventorySession.objects.select_related(
        "store", "created_by", "validated_by"
    ).prefetch_related(
        "lines",
        "lines__product",
    )
    if not request.user.is_staff:
        queryset = queryset.filter(store_id__in=user_store_ids(request.user))
    store_id = request.query_params.get("store") or request.query_params.get("store_id")
    if store_id:
        queryset = queryset.filter(store_id=store_id)

    search = request.query_params.get("search")
    if search:
        queryset = queryset.filter(
            Q(code__icontains=search)
            | Q(title__icontains=search)
            | Q(note__icontains=search)
            | Q(lines__product__name__icontains=search)
            | Q(lines__product__reference__icontains=search)
        ).distinct()

    status_value = request.query_params.get("status")
    if status_value:
        queryset = queryset.filter(
            status__in=[
                item.strip() for item in str(status_value).split(",") if item.strip()
            ]
        )
    return queryset


def _get_inventory_for_user(request, pk):
    try:
        return _inventory_queryset(request).get(pk=pk)
    except InventorySession.DoesNotExist:
        raise Http404(_("Aucun inventaire ne correspond à la requête."))


@transaction.atomic
def _create_inventory_from_validated_data(*, store, user, data):
    lines_data = data.pop("lines")
    should_validate = data.get("status") == InventorySession.Statuses.VALIDATED
    if should_validate:
        data["status"] = InventorySession.Statuses.DRAFT
    session = InventorySession.objects.create(
        store=store,
        code=data["code"],
        title=data["title"],
        inventory_date=data.get("inventory_date") or timezone.localdate(),
        status=data.get("status", InventorySession.Statuses.DRAFT),
        note=data.get("note", ""),
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    for line_data in lines_data:
        try:
            product = Product.objects.get(pk=line_data["product"], is_active=True)
        except Product.DoesNotExist as exc:
            raise ValidationError({"product": ["Article introuvable."]}) from exc
        expected_quantity = line_data.get("expected_quantity")
        if expected_quantity is None:
            expected_quantity = (
                StockBalance.objects.filter(store=store, product=product)
                .values_list("quantity", flat=True)
                .first()
                or 0
            )
        InventoryLine.objects.create(
            session=session,
            product=product,
            expected_quantity=expected_quantity,
            counted_quantity=line_data["counted_quantity"],
            note=line_data.get("note", ""),
        )
    if should_validate:
        session = validate_inventory_session(session=session, user=user)
    return session


class InventorySessionListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request, *args, **kwargs):
        return _paginate(
            request, _inventory_queryset(request), InventorySessionSerializer
        )

    @staticmethod
    def post(request, *args, **kwargs):
        store = get_store_from_request(request, roles=MANAGEMENT_ROLES)
        serializer = InventorySessionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = _create_inventory_from_validated_data(
            store=store,
            user=request.user,
            data=dict(serializer.validated_data),
        )
        return Response(
            InventorySessionSerializer(session).data, status=status.HTTP_201_CREATED
        )


class InventorySessionDetailEditDeleteView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, pk, *args, **kwargs):
        return Response(
            InventorySessionSerializer(_get_inventory_for_user(request, pk)).data,
            status=status.HTTP_200_OK,
        )

    def put(self, request, pk, *args, **kwargs):
        session = _get_inventory_for_user(request, pk)
        _ensure_store_management_access(request.user, session.store_id)
        if session.status == InventorySession.Statuses.VALIDATED:
            raise ValidationError(
                {"status": ["Un inventaire validé ne peut plus être modifié."]}
            )
        serializer = InventorySessionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            session.lines.all().delete()
            data = dict(serializer.validated_data)
            lines_data = data.pop("lines")
            should_validate = data.get("status") == InventorySession.Statuses.VALIDATED
            session.code = data.get("code", session.code)
            session.title = data.get("title", session.title)
            session.inventory_date = (
                data.get("inventory_date") or session.inventory_date
            )
            session.status = (
                InventorySession.Statuses.DRAFT
                if should_validate
                else data.get("status", InventorySession.Statuses.DRAFT)
            )
            session.note = data.get("note", "")
            session.save()
            for line_data in lines_data:
                try:
                    product = Product.objects.get(
                        pk=line_data["product"], is_active=True
                    )
                except Product.DoesNotExist as exc:
                    raise ValidationError(
                        {"product": ["Article introuvable."]}
                    ) from exc
                expected_quantity = line_data.get("expected_quantity")
                if expected_quantity is None:
                    expected_quantity = (
                        StockBalance.objects.filter(
                            store=session.store, product=product
                        )
                        .values_list("quantity", flat=True)
                        .first()
                        or 0
                    )
                InventoryLine.objects.create(
                    session=session,
                    product=product,
                    expected_quantity=expected_quantity,
                    counted_quantity=line_data["counted_quantity"],
                    note=line_data.get("note", ""),
                )
            if should_validate:
                session = validate_inventory_session(session=session, user=request.user)
        return Response(
            InventorySessionSerializer(session).data, status=status.HTTP_200_OK
        )

    def delete(self, request, pk, *args, **kwargs):
        session = _get_inventory_for_user(request, pk)
        _ensure_store_management_access(request.user, session.store_id)
        if session.status == InventorySession.Statuses.VALIDATED:
            raise ValidationError(
                {"status": ["Un inventaire validé ne peut pas être supprimé."]}
            )
        session.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class InventorySessionValidateView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def post(request, pk, *args, **kwargs):
        session = _get_inventory_for_user(request, pk)
        _ensure_store_management_access(request.user, session.store_id)
        session = validate_inventory_session(session=session, user=request.user)
        return Response(
            InventorySessionSerializer(session).data, status=status.HTTP_200_OK
        )


class BulkDeleteInventorySessionsView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def delete(request, *args, **kwargs):
        ids = request.data.get("ids")
        if not ids or not isinstance(ids, list):
            raise ValidationError({"ids": "Une liste d'identifiants est requise."})
        queryset = InventorySession.objects.filter(pk__in=ids).exclude(
            status=InventorySession.Statuses.VALIDATED
        )
        if not request.user.is_staff:
            queryset = queryset.filter(
                store_id__in=user_store_ids(request.user, roles=MANAGEMENT_ROLES)
            )
        deleted, _deleted_breakdown = queryset.delete()
        if deleted == 0:
            raise PermissionDenied("Aucun inventaire à supprimer.")
        return Response({"deleted": deleted}, status=status.HTTP_200_OK)
