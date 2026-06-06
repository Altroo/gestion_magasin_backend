from django.urls import path

from sales.views import (
    CustomerDetailEditDeleteView,
    CustomerListCreateView,
    PaymentModeDetailEditDeleteView,
    PaymentModeListCreateView,
    BulkDeletePromotionsView,
    PromotionDetailEditDeleteView,
    PromotionListCreateView,
    SaleDashboardView,
    SaleDetailEditDeleteView,
    SaleListCreateView,
    SaleSyncOfflineView,
    SaleVoidView,
)

app_name = "sales"

urlpatterns = [
    path("customers/", CustomerListCreateView.as_view(), name="customers-list-create"),
    path("customers/<int:pk>/", CustomerDetailEditDeleteView.as_view(), name="customers-detail"),
    path("payment-modes/", PaymentModeListCreateView.as_view(), name="payment-modes-list-create"),
    path("payment-modes/<int:pk>/", PaymentModeDetailEditDeleteView.as_view(), name="payment-modes-detail"),
    path("promotions/", PromotionListCreateView.as_view(), name="promotions-list-create"),
    path("promotions/bulk-delete/", BulkDeletePromotionsView.as_view(), name="promotions-bulk-delete"),
    path("promotions/<int:pk>/", PromotionDetailEditDeleteView.as_view(), name="promotions-detail"),
    path("sync-offline/", SaleSyncOfflineView.as_view(), name="sales-sync-offline"),
    path("dashboard/", SaleDashboardView.as_view(), name="sales-dashboard"),
    path("<int:pk>/void/", SaleVoidView.as_view(), name="sales-void"),
    path("<int:pk>/", SaleDetailEditDeleteView.as_view(), name="sales-detail"),
    path("", SaleListCreateView.as_view(), name="sales-list-create"),
]
