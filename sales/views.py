from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q, Sum
from django.http import Http404
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog.models import Product
from gestion_magasin_backend.utils import CustomPagination, split_csv_query_value
from sales.models import Customer, PaymentMode, Promotion, PromotionLine, Sale
from sales.serializers import (
    CustomerSerializer,
    PaymentModeSerializer,
    PromotionCreateSerializer,
    PromotionSerializer,
    SaleCreateSerializer,
    SaleDashboardSerializer,
    SaleSerializer,
    SaleVoidSerializer,
)
from sales.services import create_sale, void_sale
from stock.models import StockBalance
from store.permissions import (
    MANAGEMENT_ROLES,
    WRITE_ROLES,
    get_store_from_request,
    user_has_store_access,
    user_store_ids,
)


def _paginate(request, queryset, serializer_class):
    paginator = CustomPagination()
    page = paginator.paginate_queryset(queryset, request)
    serializer = serializer_class(page, many=True, context={"request": request})
    return paginator.get_paginated_response(serializer.data)


def _customer_queryset(request):
    queryset = Customer.objects.select_related("store")
    if not request.user.is_staff:
        queryset = queryset.filter(store_id__in=user_store_ids(request.user))
    store_id = request.query_params.get("store") or request.query_params.get("store_id")
    if store_id:
        queryset = queryset.filter(store_id=store_id)
    return queryset


def _get_customer_for_user(request, pk):
    try:
        return _customer_queryset(request).get(pk=pk)
    except Customer.DoesNotExist:
        raise Http404(_("Aucun client ne correspond à la requête."))


def _ensure_store_write_access(user, store_id):
    if not user_has_store_access(user, store_id, roles=WRITE_ROLES):
        raise PermissionDenied("Rôle insuffisant pour ce magasin.")


def _ensure_store_management_access(user, store_id):
    if not user_has_store_access(user, store_id, roles=MANAGEMENT_ROLES):
        raise PermissionDenied("Rôle insuffisant pour ce magasin.")


def _ensure_promotion_create_permission(user):
    if user.is_staff or getattr(user, "can_create_promotion", False):
        return
    raise PermissionDenied("Vous n'avez pas les droits pour créer une promotion.")


class CustomerListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request, *args, **kwargs):
        return _paginate(request, _customer_queryset(request), CustomerSerializer)

    @staticmethod
    def post(request, *args, **kwargs):
        serializer = CustomerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _ensure_store_write_access(request.user, serializer.validated_data["store"].pk)
        customer = serializer.save()
        return Response(
            CustomerSerializer(customer).data, status=status.HTTP_201_CREATED
        )


class CustomerDetailEditDeleteView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, pk, *args, **kwargs):
        return Response(
            CustomerSerializer(_get_customer_for_user(request, pk)).data,
            status=status.HTTP_200_OK,
        )

    def put(self, request, pk, *args, **kwargs):
        customer = _get_customer_for_user(request, pk)
        _ensure_store_write_access(request.user, customer.store_id)
        serializer = CustomerSerializer(customer, data=request.data)
        serializer.is_valid(raise_exception=True)
        next_store = serializer.validated_data.get("store", customer.store)
        _ensure_store_write_access(request.user, next_store.pk)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, pk, *args, **kwargs):
        customer = _get_customer_for_user(request, pk)
        _ensure_store_write_access(request.user, customer.store_id)
        serializer = CustomerSerializer(customer, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        next_store = serializer.validated_data.get("store", customer.store)
        _ensure_store_write_access(request.user, next_store.pk)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, pk, *args, **kwargs):
        customer = _get_customer_for_user(request, pk)
        _ensure_store_management_access(request.user, customer.store_id)
        customer.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PaymentModeListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get_permissions(self):
        if self.request.method == "POST":
            return [permissions.IsAdminUser()]
        return super().get_permissions()

    @staticmethod
    def get(request, *args, **kwargs):
        return _paginate(request, PaymentMode.objects.all(), PaymentModeSerializer)

    @staticmethod
    def post(request, *args, **kwargs):
        serializer = PaymentModeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment_mode = serializer.save()
        return Response(
            PaymentModeSerializer(payment_mode).data, status=status.HTTP_201_CREATED
        )


class PaymentModeDetailEditDeleteView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get_permissions(self):
        if self.request.method in {"PUT", "PATCH", "DELETE"}:
            return [permissions.IsAdminUser()]
        return super().get_permissions()

    @staticmethod
    def get_object(pk):
        try:
            return PaymentMode.objects.get(pk=pk)
        except PaymentMode.DoesNotExist:
            raise Http404(_("Aucun mode de paiement ne correspond à la requête."))

    def get(self, request, pk, *args, **kwargs):
        return Response(
            PaymentModeSerializer(self.get_object(pk)).data, status=status.HTTP_200_OK
        )

    def put(self, request, pk, *args, **kwargs):
        serializer = PaymentModeSerializer(self.get_object(pk), data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, pk, *args, **kwargs):
        serializer = PaymentModeSerializer(
            self.get_object(pk), data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, pk, *args, **kwargs):
        self.get_object(pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


def _promotion_queryset(request):
    queryset = Promotion.objects.select_related("store", "created_by").prefetch_related(
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
            Q(name__icontains=search)
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


def _get_promotion_for_user(request, pk):
    try:
        return _promotion_queryset(request).get(pk=pk)
    except Promotion.DoesNotExist:
        raise Http404(_("Aucune promotion ne correspond à la requête."))


def _create_promotion_from_validated_data(*, store, user, data):
    lines_data = data.pop("lines")
    promotion = Promotion.objects.create(
        store=store,
        name=data["name"],
        selling_price=data["selling_price"],
        status=data.get("status", Promotion.Statuses.ACTIVE),
        start_date=data.get("start_date"),
        end_date=data.get("end_date"),
        note=data.get("note", ""),
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    for line_data in lines_data:
        product = Product.objects.filter(
            pk=line_data["product"], is_active=True
        ).first()
        if not product:
            raise ValidationError({"product": ["Article introuvable."]})
        PromotionLine.objects.create(
            promotion=promotion,
            product=product,
            quantity=line_data["quantity"],
        )
    return promotion


class PromotionListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request, *args, **kwargs):
        return _paginate(request, _promotion_queryset(request), PromotionSerializer)

    @staticmethod
    def post(request, *args, **kwargs):
        _ensure_promotion_create_permission(request.user)
        store = get_store_from_request(request, roles=WRITE_ROLES)
        serializer = PromotionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        promotion = _create_promotion_from_validated_data(
            store=store,
            user=request.user,
            data=dict(serializer.validated_data),
        )
        return Response(
            PromotionSerializer(promotion).data,
            status=status.HTTP_201_CREATED,
        )


class PromotionDetailEditDeleteView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, pk, *args, **kwargs):
        return Response(
            PromotionSerializer(_get_promotion_for_user(request, pk)).data,
            status=status.HTTP_200_OK,
        )

    def put(self, request, pk, *args, **kwargs):
        _ensure_promotion_create_permission(request.user)
        promotion = _get_promotion_for_user(request, pk)
        _ensure_store_write_access(request.user, promotion.store_id)
        serializer = PromotionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        lines_data = data.pop("lines")
        promotion.name = data["name"]
        promotion.selling_price = data["selling_price"]
        promotion.status = data.get("status", Promotion.Statuses.ACTIVE)
        promotion.start_date = data.get("start_date")
        promotion.end_date = data.get("end_date")
        promotion.note = data.get("note", "")
        promotion.save()
        promotion.lines.all().delete()
        for line_data in lines_data:
            product = Product.objects.filter(
                pk=line_data["product"], is_active=True
            ).first()
            if not product:
                raise ValidationError({"product": ["Article introuvable."]})
            PromotionLine.objects.create(
                promotion=promotion,
                product=product,
                quantity=line_data["quantity"],
            )
        return Response(PromotionSerializer(promotion).data, status=status.HTTP_200_OK)

    def patch(self, request, pk, *args, **kwargs):
        _ensure_promotion_create_permission(request.user)
        promotion = _get_promotion_for_user(request, pk)
        _ensure_store_write_access(request.user, promotion.store_id)
        if set(request.data.keys()) == {"status"}:
            status_value = request.data.get("status")
            if status_value not in Promotion.Statuses.values:
                return Response(
                    {"status": ["Statut invalide."]}, status=status.HTTP_400_BAD_REQUEST
                )
            promotion.status = status_value
            promotion.save(update_fields=["status", "date_updated"])
            return Response(
                PromotionSerializer(promotion).data, status=status.HTTP_200_OK
            )
        serializer = PromotionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        lines_data = data.pop("lines")
        promotion.name = data["name"]
        promotion.selling_price = data["selling_price"]
        promotion.status = data.get("status", Promotion.Statuses.ACTIVE)
        promotion.start_date = data.get("start_date")
        promotion.end_date = data.get("end_date")
        promotion.note = data.get("note", "")
        promotion.save()
        promotion.lines.all().delete()
        for line_data in lines_data:
            product = Product.objects.filter(
                pk=line_data["product"], is_active=True
            ).first()
            if not product:
                raise ValidationError({"product": ["Article introuvable."]})
            PromotionLine.objects.create(
                promotion=promotion,
                product=product,
                quantity=line_data["quantity"],
            )
        return Response(PromotionSerializer(promotion).data, status=status.HTTP_200_OK)

    def delete(self, request, pk, *args, **kwargs):
        _ensure_promotion_create_permission(request.user)
        promotion = _get_promotion_for_user(request, pk)
        _ensure_store_management_access(request.user, promotion.store_id)
        promotion.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class BulkDeletePromotionsView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def delete(request, *args, **kwargs):
        _ensure_promotion_create_permission(request.user)
        ids = request.data.get("ids")
        if not ids or not isinstance(ids, list):
            raise ValidationError({"ids": _("Une liste d'identifiants est requise.")})

        try:
            ids = [int(item) for item in ids]
        except (TypeError, ValueError):
            raise ValidationError({"ids": _("Les identifiants doivent être entiers.")})

        queryset = _promotion_queryset(request).filter(pk__in=ids)
        promotions = list(queryset)
        if len(promotions) != len(set(ids)):
            raise ValidationError({"ids": _("Certaines promotions sont introuvables.")})

        for store_id in {promotion.store_id for promotion in promotions}:
            _ensure_store_management_access(request.user, store_id)

        deleted, _deleted_breakdown = queryset.delete()
        return Response({"deleted": deleted}, status=status.HTTP_200_OK)


def _sale_queryset(request):
    queryset = Sale.objects.select_related(
        "store", "seller", "customer", "payment_mode"
    ).prefetch_related(
        "lines",
        "lines__product",
        "promotion_lines",
        "promotion_lines__promotion",
    )
    if not request.user.is_staff:
        queryset = queryset.filter(store_id__in=user_store_ids(request.user))
    store_id = request.query_params.get("store") or request.query_params.get("store_id")
    if store_id:
        queryset = queryset.filter(store_id=store_id)
    return _apply_sale_filters(request, queryset)


def _apply_sale_filters(request, queryset):
    params = request.query_params
    search = params.get("search")
    if search:
        queryset = queryset.filter(
            Q(store__name__icontains=search)
            | Q(seller__email__icontains=search)
            | Q(customer__full_name__icontains=search)
            | Q(lines__product__name__icontains=search)
            | Q(lines__product__reference__icontains=search)
            | Q(lines__product__barcode__icontains=search)
        ).distinct()

    for field in ("status", "payment_status"):
        values = split_csv_query_value(params.get(field))
        if values:
            queryset = queryset.filter(**{f"{field}__in": values})

    payment_mode_values = split_csv_query_value(
        params.get("payment_mode") or params.get("payment_mode_ids")
    )
    if payment_mode_values:
        queryset = queryset.filter(payment_mode_id__in=payment_mode_values)

    text_fields = {
        "store_name": "store__name",
        "seller_email": "seller__email",
        "customer_name": "customer__full_name",
        "payment_mode_name": "payment_mode__name",
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
        "subtotal": "subtotal",
        "discount_amount": "discount_amount",
        "total": "total",
        "paid_amount": "paid_amount",
        "change_amount": "change_amount",
    }
    numeric_lookups = {"gt": "gt", "gte": "gte", "lt": "lt", "lte": "lte", "ne": None}
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

    date_after = params.get("date_created_after")
    date_before = params.get("date_created_before")
    if date_after:
        queryset = queryset.filter(date_created__date__gte=date_after)
    if date_before:
        queryset = queryset.filter(date_created__date__lte=date_before)
    return queryset


def _sale_base_queryset(request):
    queryset = Sale.objects.select_related(
        "store", "seller", "customer", "payment_mode"
    ).prefetch_related(
        "lines",
        "lines__product",
        "promotion_lines",
        "promotion_lines__promotion",
    )
    if not request.user.is_staff:
        queryset = queryset.filter(store_id__in=user_store_ids(request.user))
    return queryset


def _get_sale_for_user(request, pk):
    try:
        return _sale_base_queryset(request).get(pk=pk)
    except Sale.DoesNotExist:
        raise Http404(_("Aucune vente ne correspond à la requête."))


class SaleListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request, *args, **kwargs):
        return _paginate(request, _sale_queryset(request), SaleSerializer)

    @staticmethod
    def post(request, *args, **kwargs):
        store = get_store_from_request(request, roles=WRITE_ROLES)
        serializer = SaleCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sale = create_sale(
            store=store, user=request.user, validated_data=serializer.validated_data
        )
        return Response(SaleSerializer(sale).data, status=status.HTTP_201_CREATED)


class SaleDetailEditDeleteView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, pk, *args, **kwargs):
        return Response(
            SaleSerializer(_get_sale_for_user(request, pk)).data,
            status=status.HTTP_200_OK,
        )

    def put(self, request, pk, *args, **kwargs):
        sale = _get_sale_for_user(request, pk)
        _ensure_store_management_access(request.user, sale.store_id)
        serializer = SaleSerializer(sale, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, pk, *args, **kwargs):
        sale = _get_sale_for_user(request, pk)
        _ensure_store_management_access(request.user, sale.store_id)
        serializer = SaleSerializer(sale, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, pk, *args, **kwargs):
        sale = _get_sale_for_user(request, pk)
        _ensure_store_management_access(request.user, sale.store_id)
        sale.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SaleSyncOfflineView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def post(request, *args, **kwargs):
        store = get_store_from_request(request, roles=WRITE_ROLES)
        payload = request.data.get("sales", [])
        if not isinstance(payload, list):
            return Response(
                {"detail": "sales doit être une liste."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        results = []
        errors = []
        for index, sale_payload in enumerate(payload):
            serializer = SaleCreateSerializer(data=sale_payload)
            if not serializer.is_valid():
                errors.append({"index": index, "errors": serializer.errors})
                continue
            try:
                sale = create_sale(
                    store=store,
                    user=request.user,
                    validated_data=serializer.validated_data,
                )
                results.append(SaleSerializer(sale).data)
            except Exception as exc:
                errors.append({"index": index, "errors": str(exc)})
        return Response(
            {"results": results, "errors": errors}, status=status.HTTP_200_OK
        )


class SaleVoidView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def post(request, pk, *args, **kwargs):
        sale = _get_sale_for_user(request, pk)
        _ensure_store_management_access(request.user, sale.store_id)
        serializer = SaleVoidSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sale = void_sale(
            sale=sale,
            user=request.user,
            reason=serializer.validated_data.get("reason", ""),
        )
        return Response(SaleSerializer(sale).data, status=status.HTTP_200_OK)


class SaleDashboardView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request, *args, **kwargs):
        store = get_store_from_request(request)
        today = timezone.localdate()
        sales_qs = Sale.objects.filter(
            store=store, status=Sale.Statuses.CONFIRMED, date_created__date=today
        )
        aggregate = sales_qs.aggregate(
            sales_count=Count("id"), total_sales=Sum("total")
        )
        low_stock_count = sum(
            1
            for balance in StockBalance.objects.filter(store=store).select_related(
                "product"
            )
            if balance.is_low_stock
        )
        data = {
            "sales_count": aggregate["sales_count"] or 0,
            "total_sales": aggregate["total_sales"] or Decimal("0"),
            "low_stock_count": low_stock_count,
            "products_count": Product.objects.filter(is_active=True).count(),
        }
        return Response(SaleDashboardSerializer(data).data, status=status.HTTP_200_OK)
