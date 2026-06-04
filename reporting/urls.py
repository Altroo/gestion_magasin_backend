from django.urls import path

from reporting.views import ActivityHistoryView, ReportExportView, StoreDashboardReportView

app_name = "reporting"

urlpatterns = [
    path("dashboard/", StoreDashboardReportView.as_view(), name="dashboard"),
    path("activity/", ActivityHistoryView.as_view(), name="activity"),
    path("export/<str:kind>/", ReportExportView.as_view(), name="export"),
]
