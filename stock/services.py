from decimal import Decimal

from django.db import transaction
from rest_framework.exceptions import ValidationError

from catalog.models import Product
from stock.models import StockBalance, StockMovement


def _decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value or "0"))


def get_locked_balance(store, product: Product) -> StockBalance:
    balance, _ = StockBalance.objects.select_for_update().get_or_create(
        store=store,
        product=product,
        defaults={
            "quantity": Decimal("0"),
            "min_stock": product.default_stock_alert,
            "average_cost": product.purchase_price,
        },
    )
    return balance


def _notify_low_stock(balance: StockBalance) -> None:
    from notification.tasks import notify_low_stock_if_needed

    transaction.on_commit(lambda: notify_low_stock_if_needed.delay(balance.pk))


@transaction.atomic
def apply_stock_movement(
    *,
    store,
    product: Product,
    quantity,
    movement_type: str,
    user=None,
    unit_cost=None,
    source_type: str = "",
    source_id: int | None = None,
    note: str = "",
    allow_negative: bool = False,
) -> StockMovement:
    delta = _decimal(quantity)
    if delta == 0:
        raise ValidationError({"quantity": ["La quantité doit être différente de zéro."]})

    balance = get_locked_balance(store, product)
    next_quantity = balance.quantity + delta
    if next_quantity < 0 and not allow_negative:
        raise ValidationError(
            {
                "quantity": [
                    f"Stock insuffisant pour {product.name}. Disponible: {balance.quantity}."
                ]
            }
        )

    balance.quantity = next_quantity
    if unit_cost is not None and delta > 0:
        balance.average_cost = _decimal(unit_cost)
    balance.save(update_fields=["quantity", "average_cost", "date_updated"])

    movement = StockMovement.objects.create(
        store=store,
        product=product,
        movement_type=movement_type,
        quantity=delta,
        balance_after=balance.quantity,
        unit_cost=_decimal(unit_cost if unit_cost is not None else product.purchase_price),
        source_type=source_type,
        source_id=source_id,
        note=note,
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    _notify_low_stock(balance)
    return movement


def apply_sale_stock(*, store, product: Product, quantity, user=None, source_id=None):
    return apply_stock_movement(
        store=store,
        product=product,
        quantity=-abs(_decimal(quantity)),
        movement_type=StockMovement.Types.SALE,
        user=user,
        unit_cost=product.purchase_price,
        source_type="sale",
        source_id=source_id,
    )


def apply_return_stock(*, store, product: Product, quantity, user=None, source_id=None):
    return apply_stock_movement(
        store=store,
        product=product,
        quantity=abs(_decimal(quantity)),
        movement_type=StockMovement.Types.RETURN,
        user=user,
        unit_cost=product.purchase_price,
        source_type="sale_return",
        source_id=source_id,
    )

