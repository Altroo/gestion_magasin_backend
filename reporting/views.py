import csv
from datetime import timedelta
from io import BytesIO

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from attendance.models import AttendanceRecord
from catalog.models import Category, Product
from finance.models import Expense
from sales.models import Customer, Promotion, Sale
from stock.models import (
    InventorySession,
    Purchase,
    StockBalance,
    StockMovement,
    StockTransfer,
)
from store.models import Store
from store.permissions import get_store_from_request, user_store_ids


def _date_range(request, default_days=30):
    today = timezone.localdate()
    date_from = request.query_params.get("date_from")
    date_to = request.query_params.get("date_to")
    start = today - timedelta(days=default_days - 1)
    end = today
    if date_from:
        start = timezone.datetime.fromisoformat(date_from).date()
    if date_to:
        end = timezone.datetime.fromisoformat(date_to).date()
    return start, end


def _store_ids_for_request(request):
    raw_store = request.query_params.get("store") or request.query_params.get("store_id")
    if raw_store and str(raw_store).lower() != "all":
        return [get_store_from_request(request).pk]
    if request.user.is_staff:
        return None
    return user_store_ids(request.user)


def _apply_store_filter(queryset, store_ids):
    if store_ids is None:
        return queryset
    return queryset.filter(store_id__in=store_ids)


def _sum(queryset, field):
    return queryset.aggregate(total=Sum(field))["total"] or 0


def _dashboard_store_scope(request):
    raw_store = request.query_params.get("store") or request.query_params.get("store_id")
    if raw_store and str(raw_store).lower() != "all":
        store = get_store_from_request(request)
        return [store.pk], {"id": store.pk, "name": store.name}
    if request.user.is_staff:
        return None, {"id": None, "name": "Tous les magasins"}
    return user_store_ids(request.user), {"id": None, "name": "Tous les magasins"}


class StoreDashboardReportView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request, *args, **kwargs):
        date_from, date_to = _date_range(request)
        store_ids, store_payload = _dashboard_store_scope(request)

        sales = Sale.objects.filter(
            status=Sale.Statuses.CONFIRMED,
            date_created__date__gte=date_from,
            date_created__date__lte=date_to,
        )
        sales = _apply_store_filter(sales, store_ids)
        expenses = _apply_store_filter(
            Expense.objects.filter(expense_date__gte=date_from, expense_date__lte=date_to),
            store_ids,
        )
        purchases = Purchase.objects.filter(
            purchase_date__gte=date_from,
            purchase_date__lte=date_to,
            status=Purchase.Statuses.RECEIVED,
        )
        purchases = _apply_store_filter(purchases, store_ids)
        attendance = _apply_store_filter(
            AttendanceRecord.objects.filter(date__gte=date_from, date__lte=date_to),
            store_ids,
        )

        low_stock_count = sum(
            1
            for balance in _apply_store_filter(
                StockBalance.objects.select_related("product", "store"),
                store_ids,
            )
            if balance.is_low_stock
        )
        today = timezone.localdate()
        expiring_count = Product.objects.filter(
            expiration_date__isnull=False,
            expiration_date__gte=today,
            expiration_date__lte=today + timedelta(days=30),
        ).count()
        expired_count = Product.objects.filter(expiration_date__isnull=False, expiration_date__lt=today).count()

        sales_trend = (
            sales.annotate(day=TruncDate("date_created"))
            .values("day")
            .annotate(total=Sum("total"), count=Count("id"))
            .order_by("day")
        )
        attendance_trend = (
            attendance.values("date")
            .annotate(hours=Sum("hours_worked"), delay=Sum("delay_minutes"))
            .order_by("date")
        )

        sales_total = _sum(sales, "total")
        expenses_total = _sum(expenses, "amount")
        purchases_total = _sum(purchases, "subtotal")
        transfers = StockTransfer.objects.filter(
            transfer_date__gte=date_from,
            transfer_date__lte=date_to,
        )
        if store_ids is not None:
            transfers = transfers.filter(
                Q(source_store_id__in=store_ids) | Q(target_store_id__in=store_ids)
            )

        return Response(
            {
                "store": store_payload,
                "period": {"date_from": date_from, "date_to": date_to},
                "kpis": {
                    "sales_count": sales.count(),
                    "sales_total": sales_total,
                    "expenses_total": expenses_total,
                    "purchases_total": purchases_total,
                    "net_total": sales_total - expenses_total - purchases_total,
                    "low_stock_count": low_stock_count,
                    "expired_count": expired_count,
                    "expiring_count": expiring_count,
                    "products_count": Product.objects.filter(is_active=True).count(),
                    "categories_count": Category.objects.filter(is_active=True).count(),
                    "customers_count": _apply_store_filter(
                        Customer.objects.filter(is_active=True),
                        store_ids,
                    ).count(),
                    "promotions_active_count": _apply_store_filter(
                        Promotion.objects.filter(status=Promotion.Statuses.ACTIVE),
                        store_ids,
                    ).count(),
                    "transfers_count": transfers.count(),
                    "attendance_hours": _sum(attendance, "hours_worked"),
                    "attendance_delay_minutes": _sum(attendance, "delay_minutes"),
                },
                "sales_trend": [
                    {"date": item["day"], "total": item["total"] or 0, "count": item["count"]}
                    for item in sales_trend
                ],
                "attendance_trend": [
                    {"date": item["date"], "hours": item["hours"] or 0, "delay": item["delay"] or 0}
                    for item in attendance_trend
                ],
                "stock_alerts": [
                    {
                        "id": balance.pk,
                        "product": balance.product.name,
                        "quantity": balance.quantity,
                        "min_stock": balance.effective_min_stock,
                    }
                    for balance in _apply_store_filter(
                        StockBalance.objects.select_related("product", "store"),
                        store_ids,
                    )
                    if balance.is_low_stock
                ][:10],
            },
            status=status.HTTP_200_OK,
        )


def _queryset_for_export(kind, request):
    date_from, date_to = _date_range(request)
    store_ids = _store_ids_for_request(request)
    if kind == "sales":
        queryset = Sale.objects.select_related("store", "seller", "customer").filter(
            date_created__date__gte=date_from,
            date_created__date__lte=date_to,
        )
        queryset = _apply_store_filter(queryset, store_ids)
        return (
            ["ID", "Magasin", "Date", "Vendeur", "Client", "Statut", "Total"],
            [
                [
                    item.pk,
                    item.store.name,
                    item.date_created.date(),
                    item.seller.email if item.seller else "",
                    item.customer.full_name if item.customer else "",
                    item.status,
                    item.total,
                ]
                for item in queryset
            ],
        )
    if kind == "stock":
        queryset = StockBalance.objects.select_related("store", "product", "product__category")
        queryset = _apply_store_filter(queryset, store_ids)
        return (
            ["ID", "Magasin", "Article", "Reference", "Code barre", "Famille", "Quantite", "Stock minimum"],
            [
                [
                    item.pk,
                    item.store.name,
                    item.product.name,
                    item.product.reference or "",
                    item.product.barcode or "",
                    item.product.category.name if item.product.category else "",
                    item.quantity,
                    item.effective_min_stock,
                ]
                for item in queryset
            ],
        )
    if kind == "attendance":
        queryset = AttendanceRecord.objects.select_related("store", "employee").filter(date__gte=date_from, date__lte=date_to)
        queryset = _apply_store_filter(queryset, store_ids)
        return (
            ["ID", "Magasin", "Employe", "Date", "Statut", "Heures", "Retard"],
            [[item.pk, item.store.name, item.employee.full_name, item.date, item.status, item.hours_worked, item.delay_minutes] for item in queryset],
        )
    if kind == "expenses":
        queryset = Expense.objects.select_related("store", "category").filter(expense_date__gte=date_from, expense_date__lte=date_to)
        queryset = _apply_store_filter(queryset, store_ids)
        return (
            ["ID", "Magasin", "Date", "Poste", "Libelle", "Statut paiement", "Montant"],
            [[item.pk, item.store.name, item.expense_date, item.category.name, item.label, item.payment_status, item.amount] for item in queryset],
        )
    if kind == "purchases":
        queryset = Purchase.objects.select_related("store").filter(purchase_date__gte=date_from, purchase_date__lte=date_to)
        queryset = _apply_store_filter(queryset, store_ids)
        return (
            ["ID", "Magasin", "Date", "Fournisseur", "Reference", "Statut", "Total"],
            [[item.pk, item.store.name, item.purchase_date, item.supplier_name, item.reference, item.status, item.subtotal] for item in queryset],
        )
    if kind == "inventory":
        queryset = InventorySession.objects.select_related("store").filter(inventory_date__gte=date_from, inventory_date__lte=date_to)
        queryset = _apply_store_filter(queryset, store_ids)
        return (
            ["ID", "Magasin", "Date", "Code", "Titre", "Statut"],
            [[item.pk, item.store.name, item.inventory_date, item.code, item.title, item.status] for item in queryset],
        )
    if kind == "movements":
        queryset = StockMovement.objects.select_related("store", "product").filter(date_created__date__gte=date_from, date_created__date__lte=date_to)
        queryset = _apply_store_filter(queryset, store_ids)
        return (
            ["ID", "Magasin", "Date", "Article", "Type", "Quantite", "Solde apres"],
            [[item.pk, item.store.name, item.date_created.date(), item.product.name, item.movement_type, item.quantity, item.balance_after] for item in queryset],
        )
    if kind == "promotions":
        queryset = Promotion.objects.select_related("store").filter(date_created__date__gte=date_from, date_created__date__lte=date_to)
        queryset = _apply_store_filter(queryset, store_ids)
        return (
            ["ID", "Magasin", "Nom", "Statut", "Prix vente", "Date debut", "Date fin"],
            [[item.pk, item.store.name, item.name, item.status, item.selling_price, item.start_date or "", item.end_date or ""] for item in queryset],
        )
    if kind == "transfers":
        queryset = StockTransfer.objects.select_related("source_store", "target_store").filter(transfer_date__gte=date_from, transfer_date__lte=date_to)
        if store_ids is not None:
            queryset = queryset.filter(Q(source_store_id__in=store_ids) | Q(target_store_id__in=store_ids))
        return (
            ["ID", "Source", "Destination", "Date", "Reference", "Statut"],
            [[item.pk, item.source_store.name, item.target_store.name, item.transfer_date, item.reference, item.status] for item in queryset],
        )
    return None


def _csv_response(kind, headers, rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{kind}.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(headers)
    writer.writerows(rows)
    return response


def _pdf_response(kind, headers, rows):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=24, leftMargin=24, topMargin=24, bottomMargin=24)
    styles = getSampleStyleSheet()
    data = [headers] + [[str(value) for value in row] for row in rows[:200]]
    table = Table(data, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story = [Paragraph(f"E.B.H Gestion Magasin - {kind}", styles["Title"]), Spacer(1, 12), table]
    doc.build(story)
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{kind}.pdf"'
    return response


class ReportExportView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @staticmethod
    def get(request, kind, *args, **kwargs):
        result = _queryset_for_export(kind, request)
        if result is None:
            return Response({"detail": "Export inconnu."}, status=status.HTTP_404_NOT_FOUND)
        headers, rows = result
        export_format = request.query_params.get("format", "csv").lower()
        if export_format == "pdf":
            return _pdf_response(kind, headers, rows)
        return _csv_response(kind, headers, rows)


class ActivityHistoryView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    @staticmethod
    def get(request, *args, **kwargs):
        models = [Store, Product, Category, StockBalance, StockMovement, StockTransfer, Purchase, InventorySession, Sale, Customer, Promotion, AttendanceRecord, Expense]
        entries = []
        for model in models:
            manager = getattr(model, "history", None)
            if manager is None:
                continue
            for row in manager.select_related("history_user").order_by("-history_date")[:30]:
                entries.append(
                    {
                        "model": model._meta.verbose_name,
                        "object_id": getattr(row, "id", None),
                        "history_type": row.history_type,
                        "history_date": row.history_date,
                        "history_user": row.history_user.email if row.history_user else "",
                        "label": str(row.instance) if hasattr(row, "instance") else str(row),
                    }
                )
        entries.sort(key=lambda item: item["history_date"], reverse=True)
        return Response({"results": entries[:100]}, status=status.HTTP_200_OK)
