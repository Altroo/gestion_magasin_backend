from django.urls import include, path
from rest_framework.routers import DefaultRouter

from catalog.views import CategoryViewSet, ProductImportBatchViewSet, ProductViewSet

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="categories")
router.register("imports", ProductImportBatchViewSet, basename="product-imports")
router.register("products", ProductViewSet, basename="products")

urlpatterns = [path("", include(router.urls))]

