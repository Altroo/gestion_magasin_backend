from django.conf import settings
from django.contrib import admin
from django.contrib.admin.sites import AlreadyRegistered


admin.site.site_url = settings.FRONTEND_URL or "/"

HISTORY_FIELDS = (
    "history_id",
    "history_date",
    "history_change_reason",
    "history_type",
    "history_user",
)


def _readonly_fields(model):
    return [
        field.name
        for field in model._meta.get_fields()
        if hasattr(field, "name")
        and getattr(field, "concrete", False)
        and not field.many_to_many
        and not field.one_to_many
    ] + list(HISTORY_FIELDS)


def _history_admin_class(model, display_fields, list_filter, search_fields):
    attrs = {
        "__doc__": f"Read-only admin for viewing historical {model.__name__} records.",
        "list_display": ("history_id", *display_fields, "history_type", "history_date", "history_user"),
        "list_filter": ("history_type", "history_date", *list_filter),
        "search_fields": search_fields,
        "readonly_fields": _readonly_fields(model),
        "ordering": ("-history_date", "-history_id"),
        "has_add_permission": lambda self, request: False,
        "has_delete_permission": lambda self, request, obj=None: False,
        "has_change_permission": lambda self, request, obj=None: False,
    }
    return type(f"Historical{model.__name__}Admin", (admin.ModelAdmin,), attrs)


def register_history_admin(model, *, display_fields=("id",), list_filter=(), search_fields=()):
    history_model = model.history.model
    admin_class = _history_admin_class(model, display_fields, list_filter, search_fields)
    try:
        admin.site.register(history_model, admin_class)
    except AlreadyRegistered:
        pass
