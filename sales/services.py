from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from sales.models import (
    Customer,
    CustomerCreditLedger,
    PaymentMode,
    Sale,
    SaleLine,
    SalePromotionLine,
)
from sales.serializers import resolve_product, resolve_promotion
from stock.services import apply_return_stock, apply_sale_stock


def _decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value or "0"))


def _payment_mode(validated_data) -> PaymentMode | None:
    if validated_data.get("payment_mode"):
        return PaymentMode.objects.filter(pk=validated_data["payment_mode"]).first()
    code = validated_data.get("payment_mode_code")
    if code:
        mode, _ = PaymentMode.objects.get_or_create(
            code=code,
            defaults={"name": code.replace("_", " ").title(), "is_credit": code == "credit"},
        )
        return mode
    return PaymentMode.objects.filter(code="cash").first()


@transaction.atomic
def create_sale(*, store, user, validated_data) -> Sale:
    idempotency_key = validated_data.get("idempotency_key") or None
    if idempotency_key:
        existing = Sale.objects.filter(
            store=store,
            idempotency_key=idempotency_key,
        ).prefetch_related("lines", "promotion_lines").first()
        if existing:
            return existing

    customer = None
    if validated_data.get("customer"):
        customer = Customer.objects.filter(
            pk=validated_data["customer"], store=store, is_active=True
        ).first()
        if not customer:
            raise ValidationError({"customer": ["Client introuvable pour ce magasin."]})

    payment_mode = _payment_mode(validated_data)
    lines_payload = validated_data.get("lines") or []
    promotion_lines_payload = validated_data.get("promotion_lines") or []
    prepared_lines = []
    prepared_promotion_lines = []
    subtotal = Decimal("0")
    for item in lines_payload:
        product = resolve_product(item["product"])
        quantity = _decimal(item["quantity"])
        unit_price = _decimal(item.get("unit_price") or product.counter_price)
        line_total = quantity * unit_price
        subtotal += line_total
        prepared_lines.append(
            {
                "product": product,
                "quantity": quantity,
                "unit_price": unit_price,
                "total": line_total,
            }
        )
    for item in promotion_lines_payload:
        promotion = resolve_promotion(item["promotion"])
        if promotion.store_id != store.pk:
            raise ValidationError({"promotion": ["Promotion introuvable pour ce magasin."]})
        if not promotion.lines.exists():
            raise ValidationError({"promotion": ["Promotion sans articles."]})
        quantity = _decimal(item["quantity"])
        unit_price = _decimal(item.get("unit_price") or promotion.selling_price)
        line_total = quantity * unit_price
        subtotal += line_total
        prepared_promotion_lines.append(
            {
                "promotion": promotion,
                "quantity": quantity,
                "unit_price": unit_price,
                "total": line_total,
            }
        )

    discount_amount = max(_decimal(validated_data.get("discount_amount")), Decimal("0"))
    total = max(subtotal - discount_amount, Decimal("0"))
    paid_amount = _decimal(validated_data.get("paid_amount") or total)
    payment_status = validated_data.get("payment_status") or Sale.PaymentStatuses.PAID
    if payment_mode and payment_mode.is_credit:
        payment_status = Sale.PaymentStatuses.IN_PROGRESS

    sale = Sale.objects.create(
        store=store,
        seller=user if getattr(user, "is_authenticated", False) else None,
        customer=customer,
        payment_mode=payment_mode,
        payment_status=payment_status,
        subtotal=subtotal,
        discount_amount=discount_amount,
        total=total,
        paid_amount=paid_amount,
        change_amount=max(paid_amount - total, Decimal("0")),
        idempotency_key=idempotency_key,
        offline_created_at=validated_data.get("offline_created_at"),
        note=validated_data.get("note", ""),
    )

    for item in prepared_lines:
        SaleLine.objects.create(sale=sale, **item)
        apply_sale_stock(
            store=store,
            product=item["product"],
            quantity=item["quantity"],
            user=user,
            source_id=sale.pk,
        )
    for item in prepared_promotion_lines:
        SalePromotionLine.objects.create(sale=sale, **item)
        for component in item["promotion"].lines.select_related("product"):
            apply_sale_stock(
                store=store,
                product=component.product,
                quantity=component.quantity * item["quantity"],
                user=user,
                source_id=sale.pk,
            )

    if customer and payment_status == Sale.PaymentStatuses.IN_PROGRESS:
        CustomerCreditLedger.objects.create(
            customer=customer,
            sale=sale,
            amount=total,
            note=f"Crédit vente #{sale.pk}",
            created_by=user if getattr(user, "is_authenticated", False) else None,
        )

    return sale


@transaction.atomic
def void_sale(*, sale: Sale, user, reason: str = "") -> Sale:
    if sale.status == Sale.Statuses.VOID:
        return sale
    sale.status = Sale.Statuses.VOID
    sale.void_reason = reason
    sale.voided_by = user if getattr(user, "is_authenticated", False) else None
    sale.voided_at = timezone.now()
    sale.save(update_fields=["status", "void_reason", "voided_by", "voided_at", "date_updated"])
    for line in sale.lines.select_related("product"):
        apply_return_stock(
            store=sale.store,
            product=line.product,
            quantity=line.quantity,
            user=user,
            source_id=sale.pk,
        )
    for line in sale.promotion_lines.select_related("promotion").prefetch_related(
        "promotion__lines",
        "promotion__lines__product",
    ):
        for component in line.promotion.lines.all():
            apply_return_stock(
                store=sale.store,
                product=component.product,
                quantity=component.quantity * line.quantity,
                user=user,
                source_id=sale.pk,
            )
    return sale
