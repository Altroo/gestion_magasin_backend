"""Allowlisted public column ordering, before pagination or list serialization."""

from decimal import Decimal
from django.db.models import (
    Case,
    CharField,
    Count,
    DecimalField,
    F,
    OuterRef,
    Subquery,
    TextField,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Lower, NullIf


def direct(names):
    return {name: F(name) for name in names.split()}


def fields_for(queryset, field, params):
    model = queryset.model._meta.label_lower
    fields = {
        "accounts.customuser": direct(
            "first_name last_name email gender is_staff is_active date_joined last_login"
        )
    }
    fields.update(
        {
            "attendance.attendancerecord": {
                **direct("date clock_in clock_out shift hours_worked status"),
                "employee_name": F("employee__full_name"),
                "store_name": F("store__name"),
            },
            "stock.purchase": {
                **direct("reference supplier_name purchase_date status subtotal"),
                "store_name": F("store__name"),
            },
            "sales.sale": {
                **direct("date_created payment_status status total"),
                "seller_email": F("seller__email"),
                "payment_mode_name": F("payment_mode__name"),
            },
            "finance.expense": {
                **direct("label expense_date payment_mode payment_status amount"),
                "store_name": F("store__name"),
                "category_name": F("category__name"),
            },
            "store.store": {
                **direct("name code address phone is_active"),
                "members_count": Count("memberships", distinct=True),
            },
            "stock.stocktransfer": {
                **direct("reference transfer_date status"),
                "target_store_name": F("target_store__name"),
            },
            "stock.stockaddrequest": {
                **direct("quantity unit_cost"),
                "product_name": F("product__name"),
                "store_name": F("store__name"),
                "requested_by_email": F("requested_by__email"),
            },
            "sales.promotion": {
                **direct("name selling_price status start_date end_date"),
                "store_name": F("store__name"),
            },
            "stock.inventorysession": {
                **direct("code title inventory_date status"),
                "store_name": F("store__name"),
            },
            "catalog.product": {
                **direct("reference barcode name counter_price is_active"),
                "category_name": F("category__name"),
                "unit_name": F("unit__name"),
            },
            "stock.stockbalance": {
                **direct("quantity average_cost date_updated"),
                "store_name": F("store__name"),
                "product_reference": F("product__reference"),
                "product_name": F("product__name"),
                "category_name": F("product__category__name"),
                "unit_name": F("product__unit__name"),
                "product_purchase_price": F("product__purchase_price"),
            },
        }
    )
    if model == "stock.stockbalance":
        queryset = queryset.alias(
            _sort_minimum=Coalesce(
                F("min_stock"), F("product__default_stock_alert"), Value(Decimal("0"))
            )
        )
        fields[model].update(
            effective_min_stock=F("_sort_minimum"),
            is_low_stock=Case(
                When(
                    _sort_minimum__gt=0,
                    quantity__lte=F("_sort_minimum"),
                    then=Value(True),
                ),
                default=Value(False),
            ),
        )
    if model == "catalog.product":
        from stock.models import StockBalance

        store_id = params.get("store") or params.get("store_id")
        minimum = F("default_stock_alert")
        available = Value(None, output_field=DecimalField())
        if store_id:
            balances = StockBalance.objects.filter(
                store_id=store_id, product_id=OuterRef("pk")
            ).order_by("pk")
            available = Coalesce(
                Subquery(balances.values("quantity")[:1]), Value(Decimal("0"))
            )
            # Match ProductSerializer's zero/default threshold fallback.
            minimum = Coalesce(
                NullIf(Subquery(balances.values("min_stock")[:1]), Value(Decimal("0"))),
                F("default_stock_alert"),
            )
        fields[model].update(available_stock=available, min_stock=minimum)
    return queryset, fields.get(model, {})


def apply_list_ordering(queryset, params):
    ordering = params.get("ordering", "")
    if not ordering or not hasattr(queryset, "model"):
        return queryset
    descending = ordering.startswith("-")
    field = ordering[1:] if descending else ordering
    queryset, fields = fields_for(queryset, field, params)
    expression = fields.get(field)
    if expression is None:
        return queryset
    resolved = expression.resolve_expression(queryset.query)
    if isinstance(resolved.output_field, (CharField, TextField)):
        expression = Lower(expression)
    queryset = queryset.alias(_list_ordering_value=expression)
    order = F("_list_ordering_value")
    return queryset.order_by(
        order.desc(nulls_last=True) if descending else order.asc(nulls_last=True),
        "-pk" if descending else "pk",
    )
