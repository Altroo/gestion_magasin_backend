from django.urls import path

from catalog.views import (
    BulkDeleteProductsView,
    CategoryDetailEditDeleteView,
    CategoryListCreateView,
    ProductDetailEditDeleteView,
    ProductImportBatchDetailView,
    ProductImportBatchListView,
    ProductImportWorkbookView,
    ProductListCreateView,
    ProductScanView,
)

app_name = "catalog"

urlpatterns = [
    path("categories/", CategoryListCreateView.as_view(), name="categories-list-create"),
    path("categories/<int:pk>/", CategoryDetailEditDeleteView.as_view(), name="categories-detail"),
    path("imports/", ProductImportBatchListView.as_view(), name="product-imports-list"),
    path("imports/<int:pk>/", ProductImportBatchDetailView.as_view(), name="product-imports-detail"),
    path("products/", ProductListCreateView.as_view(), name="products-list-create"),
    path("products/scan/", ProductScanView.as_view(), name="products-scan"),
    path("products/import-workbook/", ProductImportWorkbookView.as_view(), name="products-import-workbook"),
    path("products/bulk-delete/", BulkDeleteProductsView.as_view(), name="products-bulk-delete"),
    path("products/<int:pk>/", ProductDetailEditDeleteView.as_view(), name="products-detail"),
]
