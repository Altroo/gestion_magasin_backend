from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch, Q
from django.http import Http404
from django.utils.translation import gettext_lazy as _
from rest_framework import permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog.importers import import_products_from_workbook
from catalog.models import Category, Product, ProductImportBatch, ProductUnit
from catalog.serializers import (
    CategorySerializer,
    ProductImportBatchSerializer,
    ProductSerializer,
    ProductUnitSerializer,
)
from gestion_magasin_backend.utils import CustomPagination, parse_bool_csv_query_value
from stock.models import StockBalance
from store.permissions import (
    MANAGEMENT_ROLES,
    get_global_stock_store_from_request,
    get_store_from_request,
    user_store_ids,
)


def _paginate(request, queryset, serializer_class, context=None):
    paginator = CustomPagination()
    page = paginator.paginate_queryset(queryset, request)
    serializer = serializer_class(
        page, many=True, context=context or {"request": request}
    )
    return paginator.get_paginated_response(serializer.data)


def _category_queryset(request):
    queryset = Category.objects.all()
    search = request.query_params.get("search")
    if search:
        queryset = queryset.filter(
            Q(code__icontains=search) | Q(name__icontains=search)
        )

    for param, field in {"code": "code", "name": "name"}.items():
        for lookup in ("icontains", "istartswith", "iendswith"):
            value = request.query_params.get(f"{param}__{lookup}")
            if value:
                queryset = queryset.filter(**{f"{field}__{lookup}": value})
        exact = request.query_params.get(param)
        if exact:
            queryset = queryset.filter(**{field: exact})

    is_active_values = parse_bool_csv_query_value(request.query_params.get("is_active"))
    if is_active_values:
        queryset = queryset.filter(is_active__in=is_active_values)
    return queryset


def _unit_queryset(request):
    queryset = ProductUnit.objects.all()
    search = request.query_params.get("search")
    if search:
        queryset = queryset.filter(
            Q(code__icontains=search) | Q(name__icontains=search)
        )

    for param, field in {"code": "code", "name": "name"}.items():
        for lookup in ("icontains", "istartswith", "iendswith"):
            value = request.query_params.get(f"{param}__{lookup}")
            if value:
                queryset = queryset.filter(**{f"{field}__{lookup}": value})
        exact = request.query_params.get(param)
        if exact:
            queryset = queryset.filter(**{field: exact})

    is_active_values = parse_bool_csv_query_value(request.query_params.get("is_active"))
    if is_active_values:
        queryset = queryset.filter(is_active__in=is_active_values)
    return queryset


def _product_queryset(request):
    queryset = Product.objects.select_related("category", "unit").all()
    search = request.query_params.get("search")
    store_id = request.query_params.get("store") or request.query_params.get("store_id")

    if search:
        queryset = queryset.filter(
            Q(reference__icontains=search)
            | Q(barcode__icontains=search)
            | Q(name__icontains=search)
        )

    queryset = _apply_product_filters(request, queryset)
    if store_id:
        allowed = set(user_store_ids(request.user))
        if request.user.is_staff or int(store_id) in allowed:
            balances = StockBalance.objects.filter(store_id=store_id)
            queryset = queryset.prefetch_related(
                Prefetch(
                    "stock_balances", queryset=balances, to_attr="selected_balances"
                )
            )
    return queryset


def _apply_product_filters(request, queryset):
    params = request.query_params
    category_ids = _parse_int_csv(params.get("category_ids"))
    unit_ids = _parse_int_csv(params.get("unit_ids"))
    if category_ids:
        queryset = queryset.filter(category_id__in=category_ids)
    if unit_ids:
        queryset = queryset.filter(unit_id__in=unit_ids)

    text_fields = {
        "reference": "reference",
        "barcode": "barcode",
        "name": "name",
        "category_name": "category__name",
        "unit_name": "unit__name",
    }
    for param, field in text_fields.items():
        for lookup in ("icontains", "istartswith", "iendswith"):
            value = params.get(f"{param}__{lookup}")
            if value:
                queryset = queryset.filter(**{f"{field}__{lookup}": value})
        exact = params.get(param)
        if exact:
            queryset = queryset.filter(**{field: exact})

    bool_values = parse_bool_csv_query_value(params.get("is_active"))
    if bool_values:
        queryset = queryset.filter(is_active__in=bool_values)

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
            queryset = queryset.filter(**{field: exact})
        for suffix, lookup in numeric_lookups.items():
            value = params.get(f"{param}__{suffix}")
            if value in (None, ""):
                continue
            if lookup is None:
                queryset = queryset.exclude(**{field: value})
            else:
                queryset = queryset.filter(**{f"{field}__{lookup}": value})

    expiration_after = params.get("expiration_date_after")
    expiration_before = params.get("expiration_date_before")
    if expiration_after:
        queryset = queryset.filter(expiration_date__gte=expiration_after)
    if expiration_before:
        queryset = queryset.filter(expiration_date__lte=expiration_before)

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


def _ensure_product_management_access(request):
    if request.user.is_staff:
        return
    get_store_from_request(request, roles=MANAGEMENT_ROLES)


def _product_serializer_context(request):
    return {
        "request": request,
        "store_id": request.query_params.get("store")
        or request.query_params.get("store_id"),
    }


def _get_product(pk):
    try:
        return Product.objects.select_related("category", "unit").get(pk=pk)
    except Product.DoesNotExist:
        raise Http404(_("Aucun article ne correspond à la requête."))


class CategoryListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request, *args, **kwargs):
        return _paginate(request, _category_queryset(request), CategorySerializer)

    @staticmethod
    def post(request, *args, **kwargs):
        serializer = CategorySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        category = serializer.save()
        return Response(
            CategorySerializer(category).data, status=status.HTTP_201_CREATED
        )


class CategoryDetailEditDeleteView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get_object(pk):
        try:
            return Category.objects.get(pk=pk)
        except Category.DoesNotExist:
            raise Http404(_("Aucune famille article ne correspond à la requête."))

    def get(self, request, pk, *args, **kwargs):
        return Response(
            CategorySerializer(self.get_object(pk)).data, status=status.HTTP_200_OK
        )

    def put(self, request, pk, *args, **kwargs):
        category = self.get_object(pk)
        serializer = CategorySerializer(category, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, pk, *args, **kwargs):
        category = self.get_object(pk)
        serializer = CategorySerializer(category, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, pk, *args, **kwargs):
        self.get_object(pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProductUnitListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request, *args, **kwargs):
        return _paginate(request, _unit_queryset(request), ProductUnitSerializer)

    @staticmethod
    def post(request, *args, **kwargs):
        serializer = ProductUnitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        unit = serializer.save()
        return Response(
            ProductUnitSerializer(unit).data, status=status.HTTP_201_CREATED
        )


class ProductUnitDetailEditDeleteView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get_object(pk):
        try:
            return ProductUnit.objects.get(pk=pk)
        except ProductUnit.DoesNotExist:
            raise Http404(_("Aucune unité article ne correspond à la requête."))

    def get(self, request, pk, *args, **kwargs):
        return Response(
            ProductUnitSerializer(self.get_object(pk)).data, status=status.HTTP_200_OK
        )

    def put(self, request, pk, *args, **kwargs):
        unit = self.get_object(pk)
        serializer = ProductUnitSerializer(unit, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, pk, *args, **kwargs):
        unit = self.get_object(pk)
        serializer = ProductUnitSerializer(unit, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, pk, *args, **kwargs):
        self.get_object(pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProductListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request, *args, **kwargs):
        return _paginate(
            request,
            _product_queryset(request),
            ProductSerializer,
            context=_product_serializer_context(request),
        )

    @staticmethod
    def post(request, *args, **kwargs):
        _ensure_product_management_access(request)
        serializer = ProductSerializer(
            data=request.data, context=_product_serializer_context(request)
        )
        serializer.is_valid(raise_exception=True)
        product = serializer.save()
        return Response(
            ProductSerializer(
                product, context=_product_serializer_context(request)
            ).data,
            status=status.HTTP_201_CREATED,
        )


class ProductDetailEditDeleteView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, pk, *args, **kwargs):
        serializer = ProductSerializer(
            _get_product(pk), context=_product_serializer_context(request)
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, pk, *args, **kwargs):
        _ensure_product_management_access(request)
        serializer = ProductSerializer(
            _get_product(pk),
            data=request.data,
            context=_product_serializer_context(request),
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, pk, *args, **kwargs):
        _ensure_product_management_access(request)
        serializer = ProductSerializer(
            _get_product(pk),
            data=request.data,
            partial=True,
            context=_product_serializer_context(request),
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, pk, *args, **kwargs):
        _ensure_product_management_access(request)
        _get_product(pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProductScanView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request, *args, **kwargs):
        code = request.query_params.get("code", "").strip()
        if not code:
            return Response(
                {"detail": "Code barre requis."}, status=status.HTTP_400_BAD_REQUEST
            )
        store = get_store_from_request(request)
        product = (
            Product.objects.select_related("category")
            .filter(Q(barcode=code) | Q(reference=code), is_active=True)
            .first()
        )
        if not product:
            return Response(
                {"detail": "Article introuvable."}, status=status.HTTP_404_NOT_FOUND
            )
        serializer = ProductSerializer(
            product, context={"request": request, "store_id": store.pk}
        )
        return Response(serializer.data, status=status.HTTP_200_OK)


class ProductImportWorkbookView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    parser_classes = (MultiPartParser,)

    @staticmethod
    def post(request, *args, **kwargs):
        store = get_global_stock_store_from_request(request, roles=MANAGEMENT_ROLES)
        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response(
                {"detail": "Fichier requis."}, status=status.HTTP_400_BAD_REQUEST
            )
        batch = import_products_from_workbook(
            file_obj,
            store=store,
            imported_by=request.user,
            file_name=file_obj.name,
        )
        return Response(
            ProductImportBatchSerializer(batch).data, status=status.HTTP_201_CREATED
        )


class SendCSVExampleEmailView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def post(request, *args, **kwargs):
        from account.tasks import send_csv_example_email

        _ensure_product_management_access(request)
        send_csv_example_email.apply_async((request.user.pk, request.user.email))
        return Response(
            {"message": _("Email envoyé avec succès.")},
            status=status.HTTP_200_OK,
        )


class BulkDeleteProductsView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def delete(request, *args, **kwargs):
        _ensure_product_management_access(request)
        ids = request.data.get("ids")
        if not ids or not isinstance(ids, list):
            raise ValidationError({"ids": "Une liste d'identifiants est requise."})
        try:
            product_ids = [int(item) for item in ids]
        except (TypeError, ValueError):
            raise ValidationError({"ids": "Les identifiants doivent être des entiers."})
        deleted, _deleted_breakdown = Product.objects.filter(
            pk__in=product_ids
        ).delete()
        if deleted == 0:
            raise PermissionDenied("Aucun article à supprimer.")
        return Response({"deleted": deleted}, status=status.HTTP_200_OK)


def _product_import_queryset(request):
    queryset = ProductImportBatch.objects.select_related("store", "imported_by")
    if request.user.is_staff:
        return queryset
    return queryset.filter(store_id__in=user_store_ids(request.user))


class ProductImportBatchListView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request, *args, **kwargs):
        return _paginate(
            request, _product_import_queryset(request), ProductImportBatchSerializer
        )


class ProductImportBatchDetailView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request, pk, *args, **kwargs):
        try:
            batch = _product_import_queryset(request).get(pk=pk)
        except ProductImportBatch.DoesNotExist:
            raise Http404(_("Aucun import article ne correspond à la requête."))
        return Response(
            ProductImportBatchSerializer(batch).data, status=status.HTTP_200_OK
        )
