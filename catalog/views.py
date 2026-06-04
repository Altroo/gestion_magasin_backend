from django.db.models import Prefetch, Q
from django.core.exceptions import PermissionDenied
from rest_framework.exceptions import ValidationError
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from catalog.importers import import_products_from_workbook
from catalog.models import Category, Product, ProductImportBatch
from catalog.serializers import (
    CategorySerializer,
    ProductImportBatchSerializer,
    ProductSerializer,
)
from gestion_magasin_backend.utils import parse_bool_csv_query_value
from stock.models import StockBalance
from store.permissions import MANAGEMENT_ROLES, get_store_from_request, user_store_ids


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ["code", "name"]


class ProductViewSet(viewsets.ModelViewSet):
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ["reference", "barcode", "name", "category__name"]

    def get_queryset(self):
        qs = Product.objects.select_related("category").all()
        search = self.request.query_params.get("search")
        store_id = self.request.query_params.get("store") or self.request.query_params.get("store_id")

        if search:
            qs = qs.filter(
                Q(reference__icontains=search)
                | Q(barcode__icontains=search)
                | Q(name__icontains=search)
            )
        qs = self.apply_filters(qs)
        if store_id:
            allowed = set(user_store_ids(self.request.user))
            if self.request.user.is_staff or int(store_id) in allowed:
                balances = StockBalance.objects.filter(store_id=store_id)
                qs = qs.prefetch_related(
                    Prefetch("stock_balances", queryset=balances, to_attr="selected_balances")
                )
        return qs

    def apply_filters(self, qs):
        params = self.request.query_params
        text_fields = {
            "reference": "reference",
            "barcode": "barcode",
            "name": "name",
            "category_name": "category__name",
            "unit": "unit",
        }
        for param, field in text_fields.items():
            for lookup in ("icontains", "istartswith", "iendswith"):
                value = params.get(f"{param}__{lookup}")
                if value:
                    qs = qs.filter(**{f"{field}__{lookup}": value})
            exact = params.get(param)
            if exact:
                qs = qs.filter(**{field: exact})

        bool_values = parse_bool_csv_query_value(params.get("is_active"))
        if bool_values:
            qs = qs.filter(is_active__in=bool_values)

        compliance_values = parse_bool_csv_query_value(params.get("compliance_required"))
        if compliance_values:
            qs = qs.filter(compliance_required__in=compliance_values)

        numeric_fields = {
            "purchase_price": "purchase_price",
            "wholesale_price": "wholesale_price",
            "detail_price": "detail_price",
            "counter_price": "counter_price",
            "default_stock_alert": "default_stock_alert",
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

        expiration_after = params.get("expiration_date_after")
        expiration_before = params.get("expiration_date_before")
        if expiration_after:
            qs = qs.filter(expiration_date__gte=expiration_after)
        if expiration_before:
            qs = qs.filter(expiration_date__lte=expiration_before)

        return qs

    def ensure_management_access(self, request):
        if request.user.is_staff:
            return
        get_store_from_request(request, roles=MANAGEMENT_ROLES)

    def perform_create(self, serializer):
        self.ensure_management_access(self.request)
        serializer.save()

    def perform_update(self, serializer):
        self.ensure_management_access(self.request)
        serializer.save()

    def perform_destroy(self, instance):
        self.ensure_management_access(self.request)
        instance.delete()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["store_id"] = self.request.query_params.get("store") or self.request.query_params.get("store_id")
        return context

    @action(detail=False, methods=["get"], url_path="scan")
    def scan(self, request):
        code = request.query_params.get("code", "").strip()
        if not code:
            return Response({"detail": "Code barre requis."}, status=status.HTTP_400_BAD_REQUEST)
        store = get_store_from_request(request)
        product = (
            Product.objects.select_related("category")
            .filter(Q(barcode=code) | Q(reference=code), is_active=True)
            .first()
        )
        if not product:
            return Response({"detail": "Article introuvable."}, status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(product, context={"request": request, "store_id": store.pk})
        return Response(serializer.data)

    @action(
        detail=False,
        methods=["post"],
        parser_classes=[MultiPartParser],
        url_path="import-workbook",
    )
    def import_workbook(self, request):
        store = get_store_from_request(request, roles=MANAGEMENT_ROLES)
        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response({"detail": "Fichier requis."}, status=status.HTTP_400_BAD_REQUEST)
        batch = import_products_from_workbook(
            file_obj,
            store=store,
            imported_by=request.user,
            file_name=file_obj.name,
        )
        return Response(ProductImportBatchSerializer(batch).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["delete"], url_path="bulk-delete")
    def bulk_delete(self, request):
        self.ensure_management_access(request)
        ids = request.data.get("ids")
        if not ids or not isinstance(ids, list):
            raise ValidationError({"ids": "Une liste d'identifiants est requise."})
        try:
            product_ids = [int(item) for item in ids]
        except (TypeError, ValueError):
            raise ValidationError({"ids": "Les identifiants doivent être des entiers."})
        deleted, _ = Product.objects.filter(pk__in=product_ids).delete()
        if deleted == 0:
            raise PermissionDenied("Aucun article à supprimer.")
        return Response({"deleted": deleted}, status=status.HTTP_200_OK)


class ProductImportBatchViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ProductImportBatchSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = ProductImportBatch.objects.select_related("store", "imported_by")
        if self.request.user.is_staff:
            return qs
        return qs.filter(store_id__in=user_store_ids(self.request.user))
