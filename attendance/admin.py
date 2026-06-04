from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from attendance.models import AttendanceImportBatch, AttendanceRecord, Employee


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
class AttendanceImportBatchAdmin(admin.ModelAdmin):
    list_display = ("file_name", "store", "responsible", "imported_count", "skipped_count", "date_created")
    list_filter = ("store", "date_created")
    search_fields = ("file_name", "responsible")
    readonly_fields = ("date_created",)

