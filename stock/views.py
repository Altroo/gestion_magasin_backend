import json

from django.core.exceptions import PermissionDenied
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog.models import Product
from gestion_magasin_backend.utils import CustomPagination, parse_bool_csv_query_value
from notification.models import Notification, NotificationPreference
from notification.tasks import _broadcast
from stock.filters import (
    InventorySessionFilter,
    PurchaseFilter,
    StockAddRequestFilter,
    StockBalanceFilter,
    StockMovementFilter,
    StockTransferFilter,
)
from store.models import Role, Store
from stock.models import (
    InventoryLine,
    InventorySession,
    Purchase,
    PurchaseLine,
    StockAddRequest,
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
    StockAddRequestDecisionSerializer,
    StockAddRequestSerializer,
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
    WRITE_ROLES,
    get_global_stock_store_from_request,
    get_store_from_request,
    user_has_store_access,
    user_store_ids,
)

User = get_user_model()


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
    low_values = set(parse_bool_csv_query_value(request.query_params.get("low")))

    queryset = StockBalanceFilter(request.query_params, queryset=queryset).qs
    if low_values == {True}:
        return [balance for balance in queryset if balance.is_low_stock]
    if low_values == {False}:
        return [balance for balance in queryset if not balance.is_low_stock]
    return queryset


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


def _ensure_stock_approval_access(user, store_id):
    if not user_has_store_access(user, store_id, roles={Role.Codes.DIRECTION}):
        raise PermissionDenied("Seule la direction peut valider les demandes d'ajout de stock.")


def _stock_add_request_queryset(request):
    queryset = StockAddRequest.objects.select_related(
        "store",
        "product",
        "requested_by",
        "reviewed_by",
    )
    if not request.user.is_staff:
        direction_store_ids = set(user_store_ids(request.user, roles={Role.Codes.DIRECTION}))
        allowed_store_ids = set(user_store_ids(request.user))
        queryset = queryset.filter(
            Q(store_id__in=direction_store_ids)
            | Q(store_id__in=allowed_store_ids, requested_by=request.user)
        )

    return StockAddRequestFilter(request.query_params, queryset=queryset).qs


def _get_stock_add_request_for_user(request, pk):
    try:
        return _stock_add_request_queryset(request).get(pk=pk)
    except StockAddRequest.DoesNotExist:
        raise Http404(_("Aucune demande d'ajout de stock ne correspond à la requête."))


def _stock_add_request_recipients(stock_request):
    member_ids = stock_request.store.memberships.filter(
        is_active=True,
        role__code=Role.Codes.DIRECTION,
        user__is_active=True,
    ).values_list("user_id", flat=True)
    staff_ids = User.objects.filter(
        is_staff=True,
        is_active=True,
    ).values_list("id", flat=True)
    return User.objects.filter(
        id__in=set(member_ids).union(set(staff_ids))
    ).exclude(pk=stock_request.requested_by_id).distinct()


def _notify_stock_add_request(stock_request):
    for user in _stock_add_request_recipients(stock_request):
        preference, _ = NotificationPreference.objects.get_or_create(user=user)
        if not preference.notify_stock_add_requests:
            continue
        notification = Notification.objects.create(
            user=user,
            store=stock_request.store,
            product=stock_request.product,
            title=f"Demande ajout stock - {stock_request.product.name}",
            message=(
                f"{stock_request.requested_by or 'Un utilisateur'} demande "
                f"{stock_request.quantity} unité(s) de {stock_request.product.name} "
                f"pour {stock_request.store.name}."
            ),
            notification_type=Notification.Types.STOCK_ADD_REQUEST,
            object_id=stock_request.pk,
        )
        _broadcast(user.pk, notification)


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
        _ensure_stock_approval_access(request.user, store.pk)
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


class StockAddRequestListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request, *args, **kwargs):
        return _paginate(
            request,
            _stock_add_request_queryset(request),
            StockAddRequestSerializer,
        )

    @staticmethod
    def post(request, *args, **kwargs):
        store = get_store_from_request(request, roles=WRITE_ROLES)
        serializer = StockAddRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        product = Product.objects.filter(
            pk=serializer.validated_data["product"].pk,
            is_active=True,
        ).first()
        if not product:
            raise ValidationError({"product": ["Article introuvable."]})
        stock_request = serializer.save(
            store=store,
            product=product,
            requested_by=request.user if request.user.is_authenticated else None,
        )
        transaction.on_commit(lambda: _notify_stock_add_request(stock_request))
        return Response(
            StockAddRequestSerializer(stock_request).data,
            status=status.HTTP_201_CREATED,
        )


class StockAddRequestDetailView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request, pk, *args, **kwargs):
        return Response(
            StockAddRequestSerializer(_get_stock_add_request_for_user(request, pk)).data,
            status=status.HTTP_200_OK,
        )


class StockAddRequestApproveView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    @transaction.atomic
    def post(request, pk, *args, **kwargs):
        stock_request = _get_stock_add_request_for_user(request, pk)
        _ensure_stock_approval_access(request.user, stock_request.store_id)
        _approve_stock_add_request(stock_request, request.user)
        return Response(StockAddRequestSerializer(stock_request).data, status=status.HTTP_200_OK)


def _approve_stock_add_request(stock_request, user):
    if stock_request.status != StockAddRequest.Statuses.PENDING:
        raise ValidationError({"status": ["Cette demande est déjà traitée."]})
    apply_stock_movement(
        store=stock_request.store,
        product=stock_request.product,
        quantity=stock_request.quantity,
        movement_type=StockMovement.Types.PURCHASE,
        user=user,
        unit_cost=stock_request.unit_cost,
        source_type="stock_add_request",
        source_id=stock_request.pk,
        note=stock_request.note,
    )
    stock_request.status = StockAddRequest.Statuses.APPROVED
    stock_request.reviewed_by = user
    stock_request.reviewed_at = timezone.now()
    stock_request.save(update_fields=["status", "reviewed_by", "reviewed_at", "date_updated"])
    return stock_request


class StockAddRequestBulkApproveView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    @transaction.atomic
    def post(request, *args, **kwargs):
        ids = request.data.get("ids")
        if not ids or not isinstance(ids, list):
            raise ValidationError({"ids": "Une liste d'identifiants est requise."})
        try:
            request_ids = [int(item) for item in ids]
        except (TypeError, ValueError):
            raise ValidationError({"ids": "Les identifiants doivent être des entiers."})

        stock_requests = list(_stock_add_request_queryset(request).filter(pk__in=request_ids))
        if len(stock_requests) != len(set(request_ids)):
            raise ValidationError({"ids": "Certaines demandes sont introuvables."})
        for stock_request in stock_requests:
            _ensure_stock_approval_access(request.user, stock_request.store_id)
        for stock_request in stock_requests:
            _approve_stock_add_request(stock_request, request.user)
        return Response({"approved": len(stock_requests)}, status=status.HTTP_200_OK)


class StockAddRequestRejectView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def post(request, pk, *args, **kwargs):
        stock_request = _get_stock_add_request_for_user(request, pk)
        _ensure_stock_approval_access(request.user, stock_request.store_id)
        if stock_request.status != StockAddRequest.Statuses.PENDING:
            raise ValidationError({"status": ["Cette demande est déjà traitée."]})
        serializer = StockAddRequestDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        stock_request.status = StockAddRequest.Statuses.REJECTED
        stock_request.reviewed_by = request.user
        stock_request.reviewed_at = timezone.now()
        stock_request.rejection_reason = serializer.validated_data.get("rejection_reason", "")
        stock_request.save(update_fields=["status", "reviewed_by", "reviewed_at", "rejection_reason", "date_updated"])
        return Response(StockAddRequestSerializer(stock_request).data, status=status.HTTP_200_OK)


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
    return StockMovementFilter(request.query_params, queryset=queryset).qs


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
    return StockTransferFilter(request.query_params, queryset=queryset).qs


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
    return PurchaseFilter(request.query_params, queryset=queryset).qs


def _get_purchase_for_user(request, pk):
    try:
        return _purchase_queryset(request).get(pk=pk)
    except Purchase.DoesNotExist:
        raise Http404(_("Aucun achat ne correspond à la requête."))


def _data_with_json_lines(request):
    data = {key: value for key, value in request.data.items()}
    lines = data.get("lines")
    if isinstance(lines, str):
        try:
            data["lines"] = json.loads(lines)
        except json.JSONDecodeError as exc:
            raise ValidationError({"lines": ["Format des lignes invalide."]}) from exc
    return data


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
        invoice_file=data.get("invoice_file"),
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
    parser_classes = (JSONParser, MultiPartParser, FormParser)

    @staticmethod
    def get(request, *args, **kwargs):
        return _paginate(request, _purchase_queryset(request), PurchaseSerializer)

    @staticmethod
    def post(request, *args, **kwargs):
        serializer = PurchaseCreateSerializer(data=_data_with_json_lines(request))
        serializer.is_valid(raise_exception=True)
        store = get_store_from_request(request, roles=MANAGEMENT_ROLES)
        purchase = _create_purchase_from_validated_data(
            store=store,
            user=request.user,
            data=dict(serializer.validated_data),
        )
        return Response(
            PurchaseSerializer(purchase, context={"request": request}).data, status=status.HTTP_201_CREATED
        )


class PurchaseDetailEditDeleteView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    parser_classes = (JSONParser, MultiPartParser, FormParser)

    def get(self, request, pk, *args, **kwargs):
        return Response(
            PurchaseSerializer(_get_purchase_for_user(request, pk), context={"request": request}).data,
            status=status.HTTP_200_OK,
        )

    def put(self, request, pk, *args, **kwargs):
        purchase = _get_purchase_for_user(request, pk)
        _ensure_store_management_access(request.user, purchase.store_id)
        if purchase.status == Purchase.Statuses.RECEIVED:
            raise ValidationError(
                {"status": ["Un achat réceptionné ne peut plus être modifié."]}
            )
        serializer = PurchaseCreateSerializer(data=_data_with_json_lines(request))
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
            if "invoice_file" in data:
                purchase.invoice_file = data.get("invoice_file")
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
        return Response(PurchaseSerializer(purchase, context={"request": request}).data, status=status.HTTP_200_OK)

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
    return InventorySessionFilter(request.query_params, queryset=queryset).qs


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
