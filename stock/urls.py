from django.urls import include, path
from rest_framework.routers import DefaultRouter

from stock.views import StockBalanceViewSet, StockMovementViewSet

router = DefaultRouter()
router.register("balances", StockBalanceViewSet, basename="stock-balances")
router.register("movements", StockMovementViewSet, basename="stock-movements")

urlpatterns = [path("", include(router.urls))]

