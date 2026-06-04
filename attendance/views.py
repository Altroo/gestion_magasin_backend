from django.core.exceptions import PermissionDenied
from django.db.models import Q, Sum
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from attendance.importers import import_attendance_from_workbook
from attendance.models import AttendanceImportBatch, AttendanceRecord, Employee
from attendance.serializers import (
    AttendanceImportBatchSerializer,
    AttendanceRecordSerializer,
    EmployeeSerializer,
)
from gestion_magasin_backend.utils import split_csv_query_value
from store.permissions import MANAGEMENT_ROLES, get_store_from_request, user_has_store_access, user_store_ids


class EmployeeViewSet(viewsets.ModelViewSet):
    serializer_class = EmployeeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = Employee.objects.select_related("store", "user")
        if not self.request.user.is_staff:
            qs = qs.filter(store_id__in=user_store_ids(self.request.user))
        store_id = self.request.query_params.get("store") or self.request.query_params.get("store_id")
        if store_id:
            qs = qs.filter(store_id=store_id)
        return qs


class AttendanceRecordViewSet(viewsets.ModelViewSet):
    serializer_class = AttendanceRecordSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = AttendanceRecord.objects.select_related("store", "employee", "created_by")
        if not self.request.user.is_staff:
            qs = qs.filter(store_id__in=user_store_ids(self.request.user))
        store_id = self.request.query_params.get("store") or self.request.query_params.get("store_id")
        employee_id = self.request.query_params.get("employee")
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")
        if store_id:
            qs = qs.filter(store_id=store_id)
        if employee_id:
            qs = qs.filter(employee_id=employee_id)
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        return self.apply_filters(qs)

    def apply_filters(self, qs):
        params = self.request.query_params
        search = params.get("search")
        if search:
            qs = qs.filter(
                Q(employee__full_name__icontains=search)
                | Q(responsible__icontains=search)
                | Q(observations__icontains=search)
                | Q(store__name__icontains=search)
            )
        for field in ("status",):
            values = split_csv_query_value(params.get(field))
            if values:
                qs = qs.filter(**{f"{field}__in": values})
        text_fields = {
            "store_name": "store__name",
            "employee_name": "employee__full_name",
            "responsible": "responsible",
            "observations": "observations",
            "created_by_email": "created_by__email",
        }
        for param, field in text_fields.items():
            for lookup in ("icontains", "istartswith", "iendswith"):
                value = params.get(f"{param}__{lookup}")
                if value:
                    qs = qs.filter(**{f"{field}__{lookup}": value})
            exact = params.get(param)
            if exact:
                qs = qs.filter(**{field: exact})
        for param, field in {"hours_worked": "hours_worked", "delay_minutes": "delay_minutes"}.items():
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
        date_after = params.get("date_after")
        date_before = params.get("date_before")
        if date_after:
            qs = qs.filter(date__gte=date_after)
        if date_before:
            qs = qs.filter(date__lte=date_before)
        return qs

    def perform_create(self, serializer):
        store = serializer.validated_data["store"]
        if not user_has_store_access(self.request.user, store.pk, roles=MANAGEMENT_ROLES):
            raise PermissionDenied("Rôle insuffisant pour ce magasin.")
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        store = serializer.validated_data.get("store", serializer.instance.store)
        if not user_has_store_access(self.request.user, store.pk, roles=MANAGEMENT_ROLES):
            raise PermissionDenied("Rôle insuffisant pour ce magasin.")
        serializer.save()

    def perform_destroy(self, instance):
        if not user_has_store_access(self.request.user, instance.store_id, roles=MANAGEMENT_ROLES):
            raise PermissionDenied("Rôle insuffisant pour ce magasin.")
        instance.delete()

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
        batch = import_attendance_from_workbook(
            file_obj,
            store=store,
            imported_by=request.user,
            file_name=file_obj.name,
        )
        return Response(AttendanceImportBatchSerializer(batch).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        store = get_store_from_request(request)
        qs = self.get_queryset().filter(store=store)
        totals = qs.values("employee", "employee__full_name").annotate(hours=Sum("hours_worked")).order_by("employee__full_name")
        return Response(list(totals))


class AttendanceImportBatchViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AttendanceImportBatchSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = AttendanceImportBatch.objects.select_related("store", "imported_by")
        if self.request.user.is_staff:
            return qs
        return qs.filter(store_id__in=user_store_ids(self.request.user))
