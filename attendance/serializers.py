from rest_framework import serializers

from attendance.models import AttendanceImportBatch, AttendanceRecord, Employee


class EmployeeSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source="store.name", read_only=True)

    class Meta:
        model = Employee
        fields = [
            "id",
            "store",
            "store_name",
            "user",
            "full_name",
            "position",
            "is_active",
            "date_created",
            "date_updated",
        ]
        read_only_fields = ["date_created", "date_updated"]


class AttendanceRecordSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source="store.name", read_only=True)
    employee_name = serializers.CharField(source="employee.full_name", read_only=True)
    created_by_email = serializers.CharField(source="created_by.email", read_only=True)

    class Meta:
        model = AttendanceRecord
        fields = [
            "id",
            "store",
            "store_name",
            "employee",
            "employee_name",
            "date",
            "clock_in",
            "break_start",
            "break_end",
            "clock_out",
            "shift",
            "hours_worked",
            "delay_minutes",
            "status",
            "responsible",
            "observations",
            "created_by",
            "created_by_email",
            "date_created",
            "date_updated",
        ]
        read_only_fields = ["hours_worked", "delay_minutes", "created_by", "date_created", "date_updated"]


class AttendanceImportBatchSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source="store.name", read_only=True)
    imported_by_email = serializers.CharField(source="imported_by.email", read_only=True)

    class Meta:
        model = AttendanceImportBatch
        fields = [
            "id",
            "store",
            "store_name",
            "file_name",
            "responsible",
            "week_start",
            "week_end",
            "imported_by",
            "imported_by_email",
            "imported_count",
            "skipped_count",
            "date_created",
        ]
        read_only_fields = ["date_created", "imported_count", "skipped_count", "imported_by"]
