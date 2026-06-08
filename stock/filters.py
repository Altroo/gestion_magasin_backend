import django_filters

from gestion_magasin_backend.filter_utils import (
    CSVInFilter,
    ExcludeGlobalStockFilter,
    IExactCSVOrFilter,
    IntCSVInFilter,
    NotEqualFilter,
    QueryParamAliasMixin,
    SearchFilter,
    numeric_lookup_filter,
    text_lookup_filter,
)
from stock.models import (
    InventorySession,
    Purchase,
    StockAddRequest,
    StockBalance,
    StockMovement,
    StockTransfer,
)


class StockBalanceFilter(QueryParamAliasMixin, django_filters.FilterSet):
    filter_aliases = {"store": ("store", "store_id")}

    search = SearchFilter(
        fields=(
            "product__name",
            "product__reference",
            "product__barcode",
            "store__name",
        )
    )
    store = django_filters.CharFilter(field_name="store_id")
    store_ids = IntCSVInFilter(field_name="store_id")
    category_ids = IntCSVInFilter(field_name="product__category_id")
    unit_ids = IntCSVInFilter(field_name="product__unit_id")
    exclude_global_stock = ExcludeGlobalStockFilter()
    product_name = text_lookup_filter("product__name", "exact")
    product_name__icontains = text_lookup_filter("product__name", "icontains")
    product_name__istartswith = text_lookup_filter("product__name", "istartswith")
    product_name__iendswith = text_lookup_filter("product__name", "iendswith")
    product_reference = text_lookup_filter("product__reference", "exact")
    product_reference__icontains = text_lookup_filter(
        "product__reference", "icontains"
    )
    product_reference__istartswith = text_lookup_filter(
        "product__reference", "istartswith"
    )
    product_reference__iendswith = text_lookup_filter(
        "product__reference", "iendswith"
    )
    product_barcode = text_lookup_filter("product__barcode", "exact")
    product_barcode__icontains = text_lookup_filter("product__barcode", "icontains")
    product_barcode__istartswith = text_lookup_filter(
        "product__barcode", "istartswith"
    )
    product_barcode__iendswith = text_lookup_filter("product__barcode", "iendswith")
    category_name = text_lookup_filter("product__category__name", "exact")
    category_name__icontains = text_lookup_filter(
        "product__category__name", "icontains"
    )
    unit_name = text_lookup_filter("product__unit__name", "exact")
    unit_name__icontains = text_lookup_filter("product__unit__name", "icontains")
    store_name = text_lookup_filter("store__name", "exact")
    store_name__icontains = text_lookup_filter("store__name", "icontains")
    quantity = numeric_lookup_filter("quantity", "exact")
    quantity__gt = numeric_lookup_filter("quantity", "gt")
    quantity__gte = numeric_lookup_filter("quantity", "gte")
    quantity__lt = numeric_lookup_filter("quantity", "lt")
    quantity__lte = numeric_lookup_filter("quantity", "lte")
    quantity__ne = NotEqualFilter(field_name="quantity")
    min_stock = numeric_lookup_filter("min_stock", "exact")
    min_stock__gt = numeric_lookup_filter("min_stock", "gt")
    min_stock__gte = numeric_lookup_filter("min_stock", "gte")
    min_stock__lt = numeric_lookup_filter("min_stock", "lt")
    min_stock__lte = numeric_lookup_filter("min_stock", "lte")
    min_stock__ne = NotEqualFilter(field_name="min_stock")
    average_cost = numeric_lookup_filter("average_cost", "exact")
    average_cost__gt = numeric_lookup_filter("average_cost", "gt")
    average_cost__gte = numeric_lookup_filter("average_cost", "gte")
    average_cost__lt = numeric_lookup_filter("average_cost", "lt")
    average_cost__lte = numeric_lookup_filter("average_cost", "lte")
    average_cost__ne = NotEqualFilter(field_name="average_cost")

    class Meta:
        model = StockBalance
        fields = []


class StockAddRequestFilter(QueryParamAliasMixin, django_filters.FilterSet):
    filter_aliases = {"store": ("store", "store_id")}

    search = SearchFilter(
        fields=(
            "store__name",
            "product__name",
            "product__reference",
            "product__barcode",
            "note",
        ),
        use_distinct=True,
    )
    store = django_filters.CharFilter(field_name="store_id")
    store_ids = IntCSVInFilter(field_name="store_id")
    product = django_filters.CharFilter(field_name="product_id")
    product_ids = IntCSVInFilter(field_name="product_id")
    status = CSVInFilter(field_name="status")
    requested_by = django_filters.CharFilter(field_name="requested_by_id")
    reviewed_by = django_filters.CharFilter(field_name="reviewed_by_id")
    note = text_lookup_filter("note", "exact")
    note__icontains = text_lookup_filter("note", "icontains")
    quantity = numeric_lookup_filter("quantity", "exact")
    quantity__gt = numeric_lookup_filter("quantity", "gt")
    quantity__gte = numeric_lookup_filter("quantity", "gte")
    quantity__lt = numeric_lookup_filter("quantity", "lt")
    quantity__lte = numeric_lookup_filter("quantity", "lte")
    quantity__ne = NotEqualFilter(field_name="quantity")
    unit_cost = numeric_lookup_filter("unit_cost", "exact")
    unit_cost__gt = numeric_lookup_filter("unit_cost", "gt")
    unit_cost__gte = numeric_lookup_filter("unit_cost", "gte")
    unit_cost__lt = numeric_lookup_filter("unit_cost", "lt")
    unit_cost__lte = numeric_lookup_filter("unit_cost", "lte")
    unit_cost__ne = NotEqualFilter(field_name="unit_cost")

    class Meta:
        model = StockAddRequest
        fields = []


class StockMovementFilter(QueryParamAliasMixin, django_filters.FilterSet):
    filter_aliases = {"store": ("store", "store_id")}

    search = SearchFilter(
        fields=("store__name", "product__name", "product__reference", "note")
    )
    store = django_filters.CharFilter(field_name="store_id")
    store_ids = IntCSVInFilter(field_name="store_id")
    product = django_filters.CharFilter(field_name="product_id")
    product_ids = IntCSVInFilter(field_name="product_id")
    movement_type = CSVInFilter(field_name="movement_type")
    source_type = text_lookup_filter("source_type", "exact")
    source_type__icontains = text_lookup_filter("source_type", "icontains")
    source_id = django_filters.CharFilter(field_name="source_id")
    date_created_after = django_filters.CharFilter(
        field_name="date_created", lookup_expr="gte"
    )
    date_created_before = django_filters.CharFilter(
        field_name="date_created", lookup_expr="lte"
    )
    quantity = numeric_lookup_filter("quantity", "exact")
    quantity__gt = numeric_lookup_filter("quantity", "gt")
    quantity__gte = numeric_lookup_filter("quantity", "gte")
    quantity__lt = numeric_lookup_filter("quantity", "lt")
    quantity__lte = numeric_lookup_filter("quantity", "lte")
    quantity__ne = NotEqualFilter(field_name="quantity")
    balance_after = numeric_lookup_filter("balance_after", "exact")
    balance_after__gt = numeric_lookup_filter("balance_after", "gt")
    balance_after__gte = numeric_lookup_filter("balance_after", "gte")
    balance_after__lt = numeric_lookup_filter("balance_after", "lt")
    balance_after__lte = numeric_lookup_filter("balance_after", "lte")
    balance_after__ne = NotEqualFilter(field_name="balance_after")
    unit_cost = numeric_lookup_filter("unit_cost", "exact")
    unit_cost__gt = numeric_lookup_filter("unit_cost", "gt")
    unit_cost__gte = numeric_lookup_filter("unit_cost", "gte")
    unit_cost__lt = numeric_lookup_filter("unit_cost", "lt")
    unit_cost__lte = numeric_lookup_filter("unit_cost", "lte")
    unit_cost__ne = NotEqualFilter(field_name="unit_cost")

    class Meta:
        model = StockMovement
        fields = []


class StockTransferFilter(QueryParamAliasMixin, django_filters.FilterSet):
    filter_aliases = {
        "store": ("store", "store_id"),
        "target_store_ids": ("target_store_ids", "target_store", "target_store_id"),
    }

    search = SearchFilter(
        fields=(
            "reference",
            "note",
            "target_store__name",
            "lines__product__name",
            "lines__product__reference",
        ),
        use_distinct=True,
    )
    store = django_filters.CharFilter(field_name="target_store_id")
    target_store_ids = IntCSVInFilter(field_name="target_store_id")
    status = CSVInFilter(field_name="status")
    transfer_date_after = django_filters.CharFilter(
        field_name="transfer_date", lookup_expr="gte"
    )
    transfer_date_before = django_filters.CharFilter(
        field_name="transfer_date", lookup_expr="lte"
    )
    reference = text_lookup_filter("reference", "exact")
    reference__icontains = text_lookup_filter("reference", "icontains")
    note = text_lookup_filter("note", "exact")
    note__icontains = text_lookup_filter("note", "icontains")
    target_store_name = text_lookup_filter("target_store__name", "exact")
    target_store_name__icontains = text_lookup_filter(
        "target_store__name", "icontains"
    )

    class Meta:
        model = StockTransfer
        fields = []


class PurchaseFilter(QueryParamAliasMixin, django_filters.FilterSet):
    filter_aliases = {
        "store": ("store", "store_id"),
        "store_ids": ("store_ids", "stores"),
        "supplier_names": ("supplier_names", "suppliers"),
    }

    search = SearchFilter(
        fields=(
            "reference",
            "supplier_name",
            "note",
            "lines__product__name",
            "lines__product__reference",
        ),
        use_distinct=True,
    )
    store = django_filters.CharFilter(field_name="store_id")
    store_ids = IntCSVInFilter(field_name="store_id")
    supplier_names = IExactCSVOrFilter(field_name="supplier_name")
    status = CSVInFilter(field_name="status")
    purchase_date_after = django_filters.CharFilter(
        field_name="purchase_date", lookup_expr="gte"
    )
    purchase_date_before = django_filters.CharFilter(
        field_name="purchase_date", lookup_expr="lte"
    )
    reference = text_lookup_filter("reference", "exact")
    reference__icontains = text_lookup_filter("reference", "icontains")
    supplier_name = text_lookup_filter("supplier_name", "exact")
    supplier_name__icontains = text_lookup_filter("supplier_name", "icontains")
    note = text_lookup_filter("note", "exact")
    note__icontains = text_lookup_filter("note", "icontains")
    subtotal = numeric_lookup_filter("subtotal", "exact")
    subtotal__gt = numeric_lookup_filter("subtotal", "gt")
    subtotal__gte = numeric_lookup_filter("subtotal", "gte")
    subtotal__lt = numeric_lookup_filter("subtotal", "lt")
    subtotal__lte = numeric_lookup_filter("subtotal", "lte")
    subtotal__ne = NotEqualFilter(field_name="subtotal")

    class Meta:
        model = Purchase
        fields = []


class InventorySessionFilter(QueryParamAliasMixin, django_filters.FilterSet):
    filter_aliases = {"store": ("store", "store_id")}

    search = SearchFilter(
        fields=(
            "code",
            "title",
            "note",
            "lines__product__name",
            "lines__product__reference",
        ),
        use_distinct=True,
    )
    store = django_filters.CharFilter(field_name="store_id")
    store_ids = IntCSVInFilter(field_name="store_id")
    status = CSVInFilter(field_name="status")
    inventory_date_after = django_filters.CharFilter(
        field_name="inventory_date", lookup_expr="gte"
    )
    inventory_date_before = django_filters.CharFilter(
        field_name="inventory_date", lookup_expr="lte"
    )
    code = text_lookup_filter("code", "exact")
    code__icontains = text_lookup_filter("code", "icontains")
    title = text_lookup_filter("title", "exact")
    title__icontains = text_lookup_filter("title", "icontains")
    note = text_lookup_filter("note", "exact")
    note__icontains = text_lookup_filter("note", "icontains")

    class Meta:
        model = InventorySession
        fields = []
