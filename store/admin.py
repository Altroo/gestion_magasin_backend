from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from gestion_magasin_backend.admin_history import register_history_admin
from store.models import Role, Store, StoreMembership


@admin.register(Role)
class RoleAdmin(SimpleHistoryAdmin):
    list_display = ("name", "code", "rank")
    search_fields = ("name", "code")


@admin.register(Store)
class StoreAdmin(SimpleHistoryAdmin):
    list_display = ("name", "code", "phone", "is_global_stock", "is_active")
    list_filter = ("is_global_stock", "is_active")
    search_fields = ("name", "code", "address", "phone")


@admin.register(StoreMembership)
class StoreMembershipAdmin(SimpleHistoryAdmin):
    list_display = ("user", "store", "role", "is_active")
    list_filter = ("store", "role", "is_active")
    search_fields = ("user__email", "user__first_name", "user__last_name", "store__name")


register_history_admin(
    Role,
    display_fields=("id", "name", "code", "rank"),
    search_fields=("name", "code"),
)
register_history_admin(
    Store,
    display_fields=("id", "name", "code", "is_global_stock", "is_active"),
    list_filter=("is_global_stock", "is_active"),
    search_fields=("name", "code", "address", "phone"),
)
register_history_admin(
    StoreMembership,
    display_fields=("id", "user", "store", "role", "is_active"),
    list_filter=("store", "role", "is_active"),
    search_fields=("user__email", "store__name"),
)
