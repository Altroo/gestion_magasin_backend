from django.core.exceptions import PermissionDenied
from django.db.models import Sum
from django.http import Http404, HttpResponse
from django.utils.translation import gettext_lazy as _
from rest_framework import permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from attendance.filters import AttendanceRecordFilter, EmployeeFilter
from attendance.importers import import_attendance_from_workbook
from attendance.models import AttendanceImportBatch, AttendanceRecord, Employee
from attendance.serializers import (
    AttendanceImportBatchSerializer,
    AttendanceRecordSerializer,
    EmployeeSerializer,
)
from attendance.workbooks import build_attendance_workbook
from gestion_magasin_backend.utils import CustomPagination
from store.permissions import MANAGEMENT_ROLES, get_store_from_request, user_has_store_access, user_store_ids


def _paginate(request, queryset, serializer_class):
    paginator = CustomPagination()
    page = paginator.paginate_queryset(queryset, request)
    serializer = serializer_class(page, many=True, context={"request": request})
    return paginator.get_paginated_response(serializer.data)


def _ensure_management_access(user, store_id):
    if not user_has_store_access(user, store_id, roles=MANAGEMENT_ROLES):
        raise PermissionDenied("Rôle insuffisant pour ce magasin.")


def _employee_queryset(request):
    queryset = Employee.objects.select_related("store", "user")
    if not request.user.is_staff:
        queryset = queryset.filter(store_id__in=user_store_ids(request.user))
    return EmployeeFilter(request.query_params, queryset=queryset).qs


def _get_employee_for_user(request, pk):
    try:
        return _employee_queryset(request).get(pk=pk)
    except Employee.DoesNotExist:
        raise Http404(_("Aucun employé ne correspond à la requête."))


class EmployeeListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request, *args, **kwargs):
        return _paginate(request, _employee_queryset(request), EmployeeSerializer)

    @staticmethod
    def post(request, *args, **kwargs):
        serializer = EmployeeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _ensure_management_access(request.user, serializer.validated_data["store"].pk)
        employee = serializer.save()
        return Response(EmployeeSerializer(employee).data, status=status.HTTP_201_CREATED)


class EmployeeDetailEditDeleteView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, pk, *args, **kwargs):
        return Response(EmployeeSerializer(_get_employee_for_user(request, pk)).data, status=status.HTTP_200_OK)

    def put(self, request, pk, *args, **kwargs):
        employee = _get_employee_for_user(request, pk)
        _ensure_management_access(request.user, employee.store_id)
        serializer = EmployeeSerializer(employee, data=request.data)
        serializer.is_valid(raise_exception=True)
        next_store = serializer.validated_data.get("store", employee.store)
        _ensure_management_access(request.user, next_store.pk)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, pk, *args, **kwargs):
        employee = _get_employee_for_user(request, pk)
        _ensure_management_access(request.user, employee.store_id)
        serializer = EmployeeSerializer(employee, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        next_store = serializer.validated_data.get("store", employee.store)
        _ensure_management_access(request.user, next_store.pk)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, pk, *args, **kwargs):
        employee = _get_employee_for_user(request, pk)
        _ensure_management_access(request.user, employee.store_id)
        employee.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


def _attendance_queryset(request):
    queryset = AttendanceRecord.objects.select_related("store", "employee", "created_by")
    if not request.user.is_staff:
        queryset = queryset.filter(store_id__in=user_store_ids(request.user))
    return AttendanceRecordFilter(request.query_params, queryset=queryset).qs


def _attendance_base_queryset(request):
    queryset = AttendanceRecord.objects.select_related("store", "employee", "created_by")
    if not request.user.is_staff:
        queryset = queryset.filter(store_id__in=user_store_ids(request.user))
    return queryset


def _get_attendance_for_user(request, pk):
    try:
        return _attendance_base_queryset(request).get(pk=pk)
    except AttendanceRecord.DoesNotExist:
        raise Http404(_("Aucun pointage ne correspond à la requête."))


class AttendanceRecordListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request, *args, **kwargs):
        return _paginate(request, _attendance_queryset(request), AttendanceRecordSerializer)

    @staticmethod
    def post(request, *args, **kwargs):
        serializer = AttendanceRecordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        store = serializer.validated_data["store"]
        _ensure_management_access(request.user, store.pk)
        record = serializer.save(created_by=request.user)
        return Response(AttendanceRecordSerializer(record).data, status=status.HTTP_201_CREATED)


class AttendanceRecordDetailEditDeleteView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, pk, *args, **kwargs):
        return Response(AttendanceRecordSerializer(_get_attendance_for_user(request, pk)).data, status=status.HTTP_200_OK)

    def put(self, request, pk, *args, **kwargs):
        record = _get_attendance_for_user(request, pk)
        _ensure_management_access(request.user, record.store_id)
        serializer = AttendanceRecordSerializer(record, data=request.data)
        serializer.is_valid(raise_exception=True)
        next_store = serializer.validated_data.get("store", record.store)
        _ensure_management_access(request.user, next_store.pk)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, pk, *args, **kwargs):
        record = _get_attendance_for_user(request, pk)
        _ensure_management_access(request.user, record.store_id)
        serializer = AttendanceRecordSerializer(record, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        next_store = serializer.validated_data.get("store", record.store)
        _ensure_management_access(request.user, next_store.pk)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, pk, *args, **kwargs):
        record = _get_attendance_for_user(request, pk)
        _ensure_management_access(request.user, record.store_id)
        record.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class BulkDeleteAttendanceRecordsView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def delete(request, *args, **kwargs):
        ids = request.data.get("ids")
        if not ids or not isinstance(ids, list):
            raise ValidationError({"ids": _("Une liste d'identifiants est requise.")})

        try:
            ids = [int(item) for item in ids]
        except (TypeError, ValueError):
            raise ValidationError({"ids": _("Les identifiants doivent être entiers.")})

        queryset = _attendance_base_queryset(request).filter(pk__in=ids)
        records = list(queryset)
        if len(records) != len(set(ids)):
            raise ValidationError({"ids": _("Certains pointages sont introuvables.")})

        for store_id in {record.store_id for record in records}:
            _ensure_management_access(request.user, store_id)

        deleted, _deleted_breakdown = queryset.delete()
        return Response({"deleted": deleted}, status=status.HTTP_200_OK)


class AttendanceImportWorkbookView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    parser_classes = (MultiPartParser,)

    @staticmethod
    def post(request, *args, **kwargs):
        store = get_store_from_request(request, roles=MANAGEMENT_ROLES)
        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response({"detail": "Fichier requis."}, status=status.HTTP_400_BAD_REQUEST)
        batch = import_attendance_from_workbook(
            file_obj,
            store=store,
            imported_by=request.user,
            file_name=file_obj.name,
        )
        return Response(AttendanceImportBatchSerializer(batch).data, status=status.HTTP_201_CREATED)


class AttendanceExportWorkbookView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request, *args, **kwargs):
        responsible = " ".join(
            part for part in (request.user.first_name, request.user.last_name) if part
        ) or request.user.email
        records = list(
            _attendance_queryset(request)
            .select_related("store", "employee")
            .order_by("date", "employee__full_name")
        )
        dates = [record.date for record in records if record.date]
        content = build_attendance_workbook(
            records,
            responsible=responsible,
            week_start=min(dates) if dates else None,
            week_end=max(dates) if dates else None,
        )
        response = HttpResponse(
            content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="pointage.xlsx"'
        return response


class SendAttendanceImportGuideEmailView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def post(request, *args, **kwargs):
        from account.tasks import send_attendance_import_guide_email

        get_store_from_request(request, roles=MANAGEMENT_ROLES)
        send_attendance_import_guide_email.apply_async((request.user.pk, request.user.email))
        return Response(
            {"message": _("Email envoyé avec succès.")},
            status=status.HTTP_200_OK,
        )


class AttendanceSummaryView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request, *args, **kwargs):
        store = get_store_from_request(request)
        queryset = _attendance_queryset(request).filter(store=store)
        totals = (
            queryset.values("employee", "employee__full_name")
            .annotate(hours=Sum("hours_worked"))
            .order_by("employee__full_name")
        )
        return Response(list(totals), status=status.HTTP_200_OK)


def _attendance_import_queryset(request):
    queryset = AttendanceImportBatch.objects.select_related("store", "imported_by")
    if request.user.is_staff:
        return queryset
    return queryset.filter(store_id__in=user_store_ids(request.user))


class AttendanceImportBatchListView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request, *args, **kwargs):
        return _paginate(request, _attendance_import_queryset(request), AttendanceImportBatchSerializer)


class AttendanceImportBatchDetailView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request, pk, *args, **kwargs):
        try:
            batch = _attendance_import_queryset(request).get(pk=pk)
        except AttendanceImportBatch.DoesNotExist:
            raise Http404(_("Aucun import pointage ne correspond à la requête."))
        return Response(AttendanceImportBatchSerializer(batch).data, status=status.HTTP_200_OK)
