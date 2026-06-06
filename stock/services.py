from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from catalog.models import Product
from stock.models import (
    InventorySession,
    Purchase,
    StockBalance,
    StockMovement,
    StockTransfer,
)
from store.models import Store


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


@transaction.atomic
def validate_stock_transfer(*, transfer: StockTransfer, user=None, source_store=None) -> StockTransfer:
    if transfer.status == StockTransfer.Statuses.VALIDATED:
        raise ValidationError({"status": ["Ce transfert est déjà validé."]})
    if transfer.status == StockTransfer.Statuses.CANCELLED:
        raise ValidationError({"status": ["Un transfert annulé ne peut pas être validé."]})
    if transfer.target_store.is_global_stock:
        raise ValidationError({"target_store": ["Le magasin destination doit être un magasin de vente."]})
    if not transfer.lines.exists():
        raise ValidationError({"lines": ["Le transfert doit contenir au moins une ligne."]})
    source_store = source_store or Store.objects.filter(is_global_stock=True, is_active=True).first()
    if not source_store:
        raise ValidationError({"store": ["Le stock MBR n'est pas configuré."]})

    for line in transfer.lines.select_related("product"):
        apply_stock_movement(
            store=source_store,
            product=line.product,
            quantity=-abs(_decimal(line.quantity)),
            movement_type=StockMovement.Types.TRANSFER_OUT,
            user=user,
            unit_cost=line.product.purchase_price,
            source_type="stock_transfer",
            source_id=transfer.pk,
            note=transfer.reference,
        )
        apply_stock_movement(
            store=transfer.target_store,
            product=line.product,
            quantity=abs(_decimal(line.quantity)),
            movement_type=StockMovement.Types.TRANSFER_IN,
            user=user,
            unit_cost=line.product.purchase_price,
            source_type="stock_transfer",
            source_id=transfer.pk,
            note=transfer.reference,
        )

    transfer.status = StockTransfer.Statuses.VALIDATED
    transfer.validated_by = user if getattr(user, "is_authenticated", False) else None
    transfer.validated_at = timezone.now()
    transfer.save(update_fields=["status", "validated_by", "validated_at", "date_updated"])
    return transfer


@transaction.atomic
def receive_purchase(*, purchase: Purchase, user=None) -> Purchase:
    if purchase.status == Purchase.Statuses.RECEIVED:
        raise ValidationError({"status": ["Cet achat est déjà réceptionné."]})
    if purchase.status == Purchase.Statuses.CANCELLED:
        raise ValidationError({"status": ["Un achat annulé ne peut pas être réceptionné."]})
    if not purchase.lines.exists():
        raise ValidationError({"lines": ["L'achat doit contenir au moins une ligne."]})

    for line in purchase.lines.select_related("product"):
        apply_stock_movement(
            store=purchase.store,
            product=line.product,
            quantity=line.quantity,
            movement_type=StockMovement.Types.PURCHASE,
            user=user,
            unit_cost=line.unit_cost,
            source_type="purchase",
            source_id=purchase.pk,
            note=purchase.reference or purchase.supplier_name,
        )

    purchase.status = Purchase.Statuses.RECEIVED
    purchase.received_by = user if getattr(user, "is_authenticated", False) else None
    purchase.received_at = timezone.now()
    purchase.save(update_fields=["status", "received_by", "received_at", "date_updated"])
    return purchase


@transaction.atomic
def validate_inventory_session(*, session: InventorySession, user=None) -> InventorySession:
    if session.status == InventorySession.Statuses.VALIDATED:
        raise ValidationError({"status": ["Cet inventaire est déjà validé."]})
    if session.status == InventorySession.Statuses.CANCELLED:
        raise ValidationError({"status": ["Un inventaire annulé ne peut pas être validé."]})
    if not session.lines.exists():
        raise ValidationError({"lines": ["L'inventaire doit contenir au moins une ligne."]})

    for line in session.lines.select_related("product"):
        current_balance = get_locked_balance(session.store, line.product)
        adjustment = _decimal(line.counted_quantity) - current_balance.quantity
        if adjustment == 0:
            continue
        apply_stock_movement(
            store=session.store,
            product=line.product,
            quantity=adjustment,
            movement_type=StockMovement.Types.INVENTORY,
            user=user,
            unit_cost=line.product.purchase_price,
            source_type="inventory",
            source_id=session.pk,
            note=session.code,
            allow_negative=False,
        )

    session.status = InventorySession.Statuses.VALIDATED
    session.validated_by = user if getattr(user, "is_authenticated", False) else None
    session.validated_at = timezone.now()
    session.save(update_fields=["status", "validated_by", "validated_at", "date_updated"])
    return session
