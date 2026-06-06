from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from attendance.models import AttendanceImportBatch, AttendanceRecord, Employee
from gestion_magasin_backend.admin_history import register_history_admin


@admin.register(Employee)
class EmployeeAdmin(SimpleHistoryAdmin):
    list_display = ("full_name", "store", "position", "is_active")
    list_filter = ("store", "is_active")
    search_fields = ("full_name", "position")


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(SimpleHistoryAdmin):
    list_display = ("date", "employee", "store", "status", "hours_worked", "responsible")
    list_filter = ("store", "status", "date")
    search_fields = ("employee__full_name", "responsible", "observations")


@admin.register(AttendanceImportBatch)
class AttendanceImportBatchAdmin(SimpleHistoryAdmin):
    list_display = ("file_name", "store", "responsible", "imported_count", "skipped_count", "date_created")
    list_filter = ("store", "date_created")
    search_fields = ("file_name", "responsible")
    readonly_fields = ("date_created",)


register_history_admin(
    Employee,
    display_fields=("id", "full_name", "store", "position", "is_active"),
    list_filter=("store", "is_active"),
    search_fields=("full_name", "position", "store__name"),
)
register_history_admin(
    AttendanceRecord,
    display_fields=("id", "date", "employee", "store", "status", "hours_worked", "responsible"),
    list_filter=("store", "status", "date"),
    search_fields=("employee__full_name", "responsible", "observations", "store__name"),
)
register_history_admin(
    AttendanceImportBatch,
    display_fields=("id", "file_name", "store", "responsible", "imported_count", "skipped_count"),
    list_filter=("store",),
    search_fields=("file_name", "responsible"),
)
