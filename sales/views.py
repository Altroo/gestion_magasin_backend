from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from catalog.models import Product
from sales.models import Customer, PaymentMode, Sale
from sales.serializers import (
    CustomerSerializer,
    PaymentModeSerializer,
    SaleCreateSerializer,
    SaleDashboardSerializer,
    SaleSerializer,
    SaleVoidSerializer,
)
from sales.services import create_sale, void_sale
from stock.models import StockBalance
from gestion_magasin_backend.utils import split_csv_query_value
from store.permissions import (
    MANAGEMENT_ROLES,
    WRITE_ROLES,
    get_store_from_request,
    user_has_store_access,
    user_store_ids,
)


class CustomerViewSet(viewsets.ModelViewSet):
    serializer_class = CustomerSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = Customer.objects.select_related("store")
        if not self.request.user.is_staff:
            qs = qs.filter(store_id__in=user_store_ids(self.request.user))
        store_id = self.request.query_params.get("store") or self.request.query_params.get("store_id")
        if store_id:
            qs = qs.filter(store_id=store_id)
        return qs


class PaymentModeViewSet(viewsets.ModelViewSet):
    queryset = PaymentMode.objects.all()
    serializer_class = PaymentModeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        if self.action in {"create", "update", "partial_update", "destroy"}:
            return [permissions.IsAdminUser()]
        return super().get_permissions()


class SaleViewSet(viewsets.ModelViewSet):
    serializer_class = SaleSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = Sale.objects.select_related(
            "store", "seller", "customer", "payment_mode"
        ).prefetch_related("lines", "lines__product")
        if not self.request.user.is_staff:
            qs = qs.filter(store_id__in=user_store_ids(self.request.user))
        store_id = self.request.query_params.get("store") or self.request.query_params.get("store_id")
        if store_id:
            qs = qs.filter(store_id=store_id)
        return self.apply_filters(qs)

    def apply_filters(self, qs):
        params = self.request.query_params
        search = params.get("search")
        if search:
            qs = qs.filter(
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
                qs = qs.filter(**{f"{field}__in": values})

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
                    qs = qs.filter(**{f"{field}__{lookup}": value})
            exact = params.get(param)
            if exact:
                qs = qs.filter(**{field: exact})

        numeric_fields = {
            "subtotal": "subtotal",
            "discount_amount": "discount_amount",
            "total": "total",
            "paid_amount": "paid_amount",
            "change_amount": "change_amount",
        }
        for param, field in numeric_fields.items():
            exact = params.get(param)
            if exact not in (None, ""):
                qs = qs.filter(**{field: exact})
            for suffix, lookup in {"gt": "gt", "gte": "gte", "lt": "lt", "lte": "lte", "ne": None}.items():
                value = params.get(f"{param}__{suffix}")
                if value in (None, ""):
                    continue
                if lookup is None:
                    qs = qs.exclude(**{field: value})
                else:
                    qs = qs.filter(**{f"{field}__{lookup}": value})

        date_after = params.get("date_created_after")
        date_before = params.get("date_created_before")
        if date_after:
            qs = qs.filter(date_created__date__gte=date_after)
        if date_before:
            qs = qs.filter(date_created__date__lte=date_before)
        return qs

    def create(self, request, *args, **kwargs):
        store = get_store_from_request(request, roles=WRITE_ROLES)
        serializer = SaleCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sale = create_sale(store=store, user=request.user, validated_data=serializer.validated_data)
        return Response(SaleSerializer(sale).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="sync-offline")
    def sync_offline(self, request):
        store = get_store_from_request(request, roles=WRITE_ROLES)
        payload = request.data.get("sales", [])
        if not isinstance(payload, list):
            return Response({"detail": "sales doit être une liste."}, status=status.HTTP_400_BAD_REQUEST)
        results = []
        errors = []
        for index, sale_payload in enumerate(payload):
            serializer = SaleCreateSerializer(data=sale_payload)
            if not serializer.is_valid():
                errors.append({"index": index, "errors": serializer.errors})
                continue
            try:
                sale = create_sale(store=store, user=request.user, validated_data=serializer.validated_data)
                results.append(SaleSerializer(sale).data)
            except Exception as exc:
                errors.append({"index": index, "errors": str(exc)})
        return Response({"results": results, "errors": errors}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="void")
    def void(self, request, pk=None):
        sale = self.get_object()
        if not user_has_store_access(request.user, sale.store_id, roles=MANAGEMENT_ROLES):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied("Rôle insuffisant pour ce magasin.")
        serializer = SaleVoidSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sale = void_sale(
            sale=sale,
            user=request.user,
            reason=serializer.validated_data.get("reason", ""),
        )
        return Response(SaleSerializer(sale).data)

    @action(detail=False, methods=["get"], url_path="dashboard")
    def dashboard(self, request):
        store = get_store_from_request(request)
        today = timezone.localdate()
        sales_qs = Sale.objects.filter(store=store, status=Sale.Statuses.CONFIRMED, date_created__date=today)
        aggregate = sales_qs.aggregate(sales_count=Count("id"), total_sales=Sum("total"))
        low_stock_count = sum(
            1 for balance in StockBalance.objects.filter(store=store).select_related("product") if balance.is_low_stock
        )
        data = {
            "sales_count": aggregate["sales_count"] or 0,
            "total_sales": aggregate["total_sales"] or Decimal("0"),
            "low_stock_count": low_stock_count,
            "products_count": Product.objects.filter(is_active=True).count(),
        }
        return Response(SaleDashboardSerializer(data).data)
