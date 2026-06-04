from django.urls import path

from attendance.views import (
    AttendanceImportBatchDetailView,
    AttendanceImportBatchListView,
    AttendanceImportWorkbookView,
    AttendanceRecordDetailEditDeleteView,
    AttendanceRecordListCreateView,
    AttendanceSummaryView,
    EmployeeDetailEditDeleteView,
    EmployeeListCreateView,
)

app_name = "attendance"

urlpatterns = [
    path("employees/", EmployeeListCreateView.as_view(), name="employees-list-create"),
    path("employees/<int:pk>/", EmployeeDetailEditDeleteView.as_view(), name="employees-detail"),
    path("imports/", AttendanceImportBatchListView.as_view(), name="attendance-imports-list"),
    path("imports/<int:pk>/", AttendanceImportBatchDetailView.as_view(), name="attendance-imports-detail"),
    path("import-workbook/", AttendanceImportWorkbookView.as_view(), name="attendance-import-workbook"),
    path("summary/", AttendanceSummaryView.as_view(), name="attendance-summary"),
    path("<int:pk>/", AttendanceRecordDetailEditDeleteView.as_view(), name="attendance-detail"),
    path("", AttendanceRecordListCreateView.as_view(), name="attendance-list-create"),
]
