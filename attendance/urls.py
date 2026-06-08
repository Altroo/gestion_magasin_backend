from django.urls import path

from attendance.views import (
    AttendanceImportBatchDetailView,
    AttendanceImportBatchListView,
    AttendanceExportWorkbookView,
    AttendanceImportWorkbookView,
    AttendanceRecordDetailEditDeleteView,
    AttendanceRecordListCreateView,
    AttendanceSummaryView,
    BulkDeleteAttendanceRecordsView,
    EmployeeDetailEditDeleteView,
    EmployeeListCreateView,
    SendAttendanceImportGuideEmailView,
)

app_name = "attendance"

urlpatterns = [
    path("employees/", EmployeeListCreateView.as_view(), name="employees-list-create"),
    path("employees/<int:pk>/", EmployeeDetailEditDeleteView.as_view(), name="employees-detail"),
    path("imports/", AttendanceImportBatchListView.as_view(), name="attendance-imports-list"),
    path("imports/<int:pk>/", AttendanceImportBatchDetailView.as_view(), name="attendance-imports-detail"),
    path("import-workbook/", AttendanceImportWorkbookView.as_view(), name="attendance-import-workbook"),
    path("export-workbook/", AttendanceExportWorkbookView.as_view(), name="attendance-export-workbook"),
    path("send-import-guide-email/", SendAttendanceImportGuideEmailView.as_view(), name="attendance-send-import-guide-email"),
    path("summary/", AttendanceSummaryView.as_view(), name="attendance-summary"),
    path("bulk-delete/", BulkDeleteAttendanceRecordsView.as_view(), name="attendance-bulk-delete"),
    path("<int:pk>/", AttendanceRecordDetailEditDeleteView.as_view(), name="attendance-detail"),
    path("", AttendanceRecordListCreateView.as_view(), name="attendance-list-create"),
]
