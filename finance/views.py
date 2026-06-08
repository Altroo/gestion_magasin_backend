from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework import permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from finance.filters import ExpenseCategoryFilter, ExpenseFilter
from finance.models import Expense, ExpenseCategory
from finance.serializers import ExpenseCategorySerializer, ExpenseSerializer
from gestion_magasin_backend.utils import CustomPagination
from store.permissions import MANAGEMENT_ROLES, get_store_from_request, user_has_store_access, user_store_ids


def _category_queryset(request):
    queryset = ExpenseCategory.objects.all().order_by("name")
    return ExpenseCategoryFilter(request.query_params, queryset=queryset).qs


def _expense_queryset(request):
    queryset = Expense.objects.select_related("store", "category", "created_by")
    if not request.user.is_staff:
        queryset = queryset.filter(store_id__in=user_store_ids(request.user))

    return ExpenseFilter(request.query_params, queryset=queryset).qs.order_by(
        "-expense_date", "-id"
    )


def _get_expense_for_user(request, pk: int) -> Expense:
    try:
        return _expense_queryset(request).get(pk=pk)
    except Expense.DoesNotExist as exc:
        raise Http404("Aucune dépense ne correspond à la requête.") from exc


def _ensure_expense_management_access(request, expense: Expense) -> None:
    if not user_has_store_access(request.user, expense.store_id, roles=MANAGEMENT_ROLES):
        raise PermissionDenied("Rôle insuffisant pour ce magasin.")


class ExpenseCategoryListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request):
        paginator = CustomPagination()
        page = paginator.paginate_queryset(_category_queryset(request), request)
        serializer = ExpenseCategorySerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @staticmethod
    def post(request):
        serializer = ExpenseCategorySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        category = serializer.save()
        return Response(ExpenseCategorySerializer(category).data, status=status.HTTP_201_CREATED)


class ExpenseCategoryDetailEditDeleteView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get_object(pk: int) -> ExpenseCategory:
        try:
            return ExpenseCategory.objects.get(pk=pk)
        except ExpenseCategory.DoesNotExist as exc:
            raise Http404("Aucun poste de dépense ne correspond à la requête.") from exc

    def get(self, request, pk):
        category = self.get_object(pk)
        return Response(ExpenseCategorySerializer(category).data)

    def put(self, request, pk):
        category = self.get_object(pk)
        serializer = ExpenseCategorySerializer(category, data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(ExpenseCategorySerializer(serializer.save()).data)

    def patch(self, request, pk):
        category = self.get_object(pk)
        serializer = ExpenseCategorySerializer(category, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return Response(ExpenseCategorySerializer(serializer.save()).data)

    def delete(self, request, pk):
        category = self.get_object(pk)
        category.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ExpenseListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    parser_classes = (JSONParser, MultiPartParser, FormParser)

    @staticmethod
    def get(request):
        paginator = CustomPagination()
        page = paginator.paginate_queryset(_expense_queryset(request), request)
        serializer = ExpenseSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)

    @staticmethod
    def post(request):
        store = get_store_from_request(request, roles=MANAGEMENT_ROLES)
        serializer = ExpenseSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        expense = serializer.save(
            store=store,
            created_by=request.user if request.user.is_authenticated else None,
        )
        return Response(ExpenseSerializer(expense, context={"request": request}).data, status=status.HTTP_201_CREATED)


class ExpenseDetailEditDeleteView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    parser_classes = (JSONParser, MultiPartParser, FormParser)

    @staticmethod
    def get(request, pk):
        expense = _get_expense_for_user(request, pk)
        return Response(ExpenseSerializer(expense, context={"request": request}).data)

    @staticmethod
    def put(request, pk):
        expense = _get_expense_for_user(request, pk)
        _ensure_expense_management_access(request, expense)
        serializer = ExpenseSerializer(expense, data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        next_store = serializer.validated_data.get("store", expense.store)
        if not user_has_store_access(request.user, next_store.pk, roles=MANAGEMENT_ROLES):
            raise PermissionDenied("Rôle insuffisant pour ce magasin.")
        return Response(ExpenseSerializer(serializer.save(), context={"request": request}).data)

    @staticmethod
    def patch(request, pk):
        expense = _get_expense_for_user(request, pk)
        _ensure_expense_management_access(request, expense)
        serializer = ExpenseSerializer(expense, data=request.data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        next_store = serializer.validated_data.get("store", expense.store)
        if not user_has_store_access(request.user, next_store.pk, roles=MANAGEMENT_ROLES):
            raise PermissionDenied("Rôle insuffisant pour ce magasin.")
        return Response(ExpenseSerializer(serializer.save(), context={"request": request}).data)

    @staticmethod
    def delete(request, pk):
        expense = _get_expense_for_user(request, pk)
        if not request.user.is_staff and expense.store_id not in user_store_ids(request.user, roles=MANAGEMENT_ROLES):
            raise PermissionDenied("Rôle insuffisant pour ce magasin.")
        expense.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class BulkDeleteExpensesView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def delete(request):
        ids = request.data.get("ids")
        if not ids or not isinstance(ids, list):
            raise ValidationError({"ids": "Une liste d'identifiants est requise."})
        queryset = Expense.objects.filter(pk__in=ids)
        if not request.user.is_staff:
            queryset = queryset.filter(store_id__in=user_store_ids(request.user, roles=MANAGEMENT_ROLES))
        deleted, _ = queryset.delete()
        if deleted == 0:
            raise PermissionDenied("Aucune dépense à supprimer.")
        return Response({"deleted": deleted}, status=status.HTTP_200_OK)
