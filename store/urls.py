from django.urls import path

from store.views import (
    BulkDeleteStoresView,
    MyStoresView,
    RoleListView,
    StoreDetailEditDeleteView,
    StoreListCreateView,
    StoreMembershipDetailEditDeleteView,
    StoreMembershipListCreateView,
)

urlpatterns = [
    path("", StoreListCreateView.as_view(), name="stores-list"),
    path("bulk-delete/", BulkDeleteStoresView.as_view(), name="stores-bulk-delete"),
    path("mine/", MyStoresView.as_view(), name="stores-mine"),
    path("roles/", RoleListView.as_view(), name="roles-list"),
    path(
        "memberships/",
        StoreMembershipListCreateView.as_view(),
        name="store-memberships-list",
    ),
    path(
        "memberships/<int:pk>/",
        StoreMembershipDetailEditDeleteView.as_view(),
        name="store-memberships-detail",
    ),
    path("<int:pk>/", StoreDetailEditDeleteView.as_view(), name="stores-detail"),
]
