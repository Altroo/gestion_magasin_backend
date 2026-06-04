from django.urls import include, path
from rest_framework.routers import DefaultRouter

from attendance.views import AttendanceImportBatchViewSet, AttendanceRecordViewSet, EmployeeViewSet

router = DefaultRouter()
router.register("employees", EmployeeViewSet, basename="employees")
router.register("imports", AttendanceImportBatchViewSet, basename="attendance-imports")
router.register("", AttendanceRecordViewSet, basename="attendance")

urlpatterns = [path("", include(router.urls))]

