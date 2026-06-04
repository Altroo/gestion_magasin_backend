from django.urls import include, path
from rest_framework.routers import DefaultRouter

from sales.views import CustomerViewSet, PaymentModeViewSet, SaleViewSet

router = DefaultRouter()
router.register("customers", CustomerViewSet, basename="customers")
router.register("payment-modes", PaymentModeViewSet, basename="payment-modes")
router.register("", SaleViewSet, basename="sales")

urlpatterns = [path("", include(router.urls))]

