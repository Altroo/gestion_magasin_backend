import csv
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.http import FileResponse, HttpResponse
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
        purchases_trend = (
            purchases.values("purchase_date")
            .annotate(total=Sum("subtotal"), count=Count("id"))
            .order_by("purchase_date")
        )
        expenses_trend = (
            expenses.values("expense_date")
            .annotate(total=Sum("amount"), count=Count("id"))
            .order_by("expense_date")
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
            transfers = transfers.filter(target_store_id__in=store_ids)
        inventories = InventorySession.objects.filter(
            inventory_date__gte=date_from,
            inventory_date__lte=date_to,
        )
        inventories = _apply_store_filter(inventories, store_ids)
        promotions = Promotion.objects.filter(
            date_created__date__gte=date_from,
            date_created__date__lte=date_to,
        )
        promotions = _apply_store_filter(promotions, store_ids)
        balances = list(
            _apply_store_filter(
                StockBalance.objects.select_related("product", "store"),
                store_ids,
            )
        )
        stock_by_store_map = {}
        low_stock_by_store_map = {}
        for balance in balances:
            store_name = balance.store.name
            stock_by_store_map[store_name] = stock_by_store_map.get(store_name, 0) + balance.quantity
            if balance.is_low_stock:
                low_stock_by_store_map[store_name] = low_stock_by_store_map.get(store_name, 0) + 1

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
                "purchases_trend": [
                    {"date": item["purchase_date"], "total": item["total"] or 0, "count": item["count"]}
                    for item in purchases_trend
                ],
                "expenses_trend": [
                    {"date": item["expense_date"], "total": item["total"] or 0, "count": item["count"]}
                    for item in expenses_trend
                ],
                "attendance_trend": [
                    {"date": item["date"], "hours": item["hours"] or 0, "delay": item["delay"] or 0}
                    for item in attendance_trend
                ],
                "stock_by_store": [
                    {"store": store, "quantity": quantity}
                    for store, quantity in sorted(stock_by_store_map.items(), key=lambda item: item[0])[:12]
                ],
                "low_stock_by_store": [
                    {"store": store, "count": count}
                    for store, count in sorted(low_stock_by_store_map.items(), key=lambda item: item[1], reverse=True)[:12]
                ],
                "transfers_by_status": [
                    {"status": item["status"], "count": item["count"]}
                    for item in transfers.values("status").annotate(count=Count("id")).order_by("status")
                ],
                "inventory_by_status": [
                    {"status": item["status"], "count": item["count"]}
                    for item in inventories.values("status").annotate(count=Count("id")).order_by("status")
                ],
                "promotions_by_status": [
                    {"status": item["status"], "count": item["count"]}
                    for item in promotions.values("status").annotate(count=Count("id")).order_by("status")
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
        queryset = StockTransfer.objects.select_related("target_store").filter(transfer_date__gte=date_from, transfer_date__lte=date_to)
        if store_ids is not None:
            queryset = queryset.filter(target_store_id__in=store_ids)
        return (
            ["ID", "Destination", "Date", "Reference", "Statut"],
            [[item.pk, item.target_store.name, item.transfer_date, item.reference, item.status] for item in queryset],
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


REPORT_TITLES = {
    "sales": "Rapport des ventes",
    "stock": "Rapport du stock",
    "attendance": "Rapport de pointage",
    "expenses": "Rapport des dépenses",
    "purchases": "Rapport des achats",
    "inventory": "Rapport d'inventaire",
    "movements": "Rapport des mouvements de stock",
    "promotions": "Rapport des promotions",
    "transfers": "Rapport des transferts de stock",
}

REPORT_ACCENTS = {
    "sales": "#047857",
    "stock": "#1d4ed8",
    "attendance": "#0f766e",
    "expenses": "#b91c1c",
    "purchases": "#1d4ed8",
    "inventory": "#6d28d9",
    "movements": "#334155",
    "promotions": "#c2410c",
    "transfers": "#475569",
}

STATUS_LABELS = {
    "active": "Active",
    "absent": "Absent",
    "cancelled": "Annulé",
    "confirmed": "Confirmée",
    "credit": "Crédit",
    "draft": "Brouillon",
    "expired": "Expirée",
    "off": "Repos",
    "paid": "Payée",
    "payable": "À payer",
    "present": "Présent",
    "received": "Réceptionnée",
    "validated": "Validé",
    "void": "Annulée",
    "adjustment": "Ajustement",
    "import": "Import",
    "inventory": "Inventaire",
    "purchase": "Achat",
    "return": "Retour",
    "sale": "Vente",
    "transfer_in": "Transfert entrant",
    "transfer_out": "Transfert sortant",
}


def _pdf_store_label(request):
    raw_store = request.query_params.get("store") or request.query_params.get("store_id")
    if raw_store and str(raw_store).lower() != "all":
        try:
            return get_store_from_request(request).name
        except Exception:
            return "Magasin sélectionné"
    return "Tous les magasins"


def _is_number(value):
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def _format_pdf_value(value):
    if value is None:
        return "-"
    if isinstance(value, Decimal):
        return f"{value:,.2f}".replace(",", " ").replace(".", ",")
    if isinstance(value, float):
        return f"{value:,.2f}".replace(",", " ").replace(".", ",")
    if hasattr(value, "strftime"):
        return value.strftime("%d/%m/%Y")
    text = str(value)
    return STATUS_LABELS.get(text, text) or "-"


def _pdf_text(value):
    return escape(str(value), {"'": "&apos;", '"': "&quot;"})


def _summary_total(headers, rows):
    total_indexes = [
        index
        for index, header in enumerate(headers)
        if any(keyword in header.lower() for keyword in ["total", "montant", "prix vente", "heures", "quantite"])
    ]
    if not total_indexes:
        return None
    index = total_indexes[-1]
    total = Decimal("0")
    has_numeric = False
    for row in rows:
        value = row[index] if index < len(row) else None
        if _is_number(value):
            total += Decimal(str(value))
            has_numeric = True
    if not has_numeric:
        return None
    return headers[index], total


def _column_widths(headers, available_width):
    weights = []
    for header in headers:
        normalized = header.lower()
        if normalized in {"id"}:
            weights.append(0.55)
        elif any(keyword in normalized for keyword in ["date", "statut", "code"]):
            weights.append(1.05)
        elif any(keyword in normalized for keyword in ["total", "montant", "prix", "quantite", "stock", "heures", "retard"]):
            weights.append(1.1)
        elif any(keyword in normalized for keyword in ["article", "client", "fournisseur", "libelle", "employe"]):
            weights.append(1.85)
        else:
            weights.append(1.35)
    weight_sum = sum(weights) or 1
    return [available_width * weight / weight_sum for weight in weights]


def _report_footer(title):
    def _draw(canvas, doc):
        from reportlab.lib import colors
        from reportlab.lib.units import cm

        canvas.saveState()
        width, _height = doc.pagesize
        canvas.setStrokeColor(colors.HexColor("#d1d5db"))
        canvas.setLineWidth(0.5)
        canvas.line(doc.leftMargin, 1.0 * cm, width - doc.rightMargin, 1.0 * cm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(doc.leftMargin, 0.55 * cm, "E.B.H Gestion Magasin")
        canvas.drawCentredString(width / 2, 0.55 * cm, title)
        canvas.drawRightString(width - doc.rightMargin, 0.55 * cm, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    return _draw


def _pdf_response(kind, headers, rows, request):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = BytesIO()
    page_size = landscape(A4)
    title = REPORT_TITLES.get(kind, f"Rapport {kind}")
    accent = colors.HexColor(REPORT_ACCENTS.get(kind, "#1d4ed8"))
    date_from, date_to = _date_range(request)
    store_label = _pdf_store_label(request)
    generated_at = timezone.localtime(timezone.now()).strftime("%d/%m/%Y %H:%M")
    content_width = page_size[0] - (1.1 * cm * 2)

    doc = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        rightMargin=1.1 * cm,
        leftMargin=1.1 * cm,
        topMargin=0.9 * cm,
        bottomMargin=1.35 * cm,
        title=title,
        author="E.B.H Gestion Magasin",
    )
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            "ReportBrand",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=13,
            textColor=colors.HexColor("#0f172a"),
        )
    )
    styles.add(
        ParagraphStyle(
            "ReportTitle",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=accent,
            alignment=2,
        )
    )
    styles.add(
        ParagraphStyle(
            "ReportMeta",
            parent=styles["Normal"],
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#475569"),
        )
    )
    styles.add(
        ParagraphStyle(
            "ReportCell",
            parent=styles["Normal"],
            fontSize=7.2,
            leading=9,
            textColor=colors.HexColor("#111827"),
        )
    )
    styles.add(
        ParagraphStyle(
            "ReportHeaderCell",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.4,
            leading=9,
            textColor=colors.white,
        )
    )

    header_table = Table(
        [
            [
                Paragraph("E.B.H<br/>Gestion Magasin", styles["ReportBrand"]),
                Paragraph(title, styles["ReportTitle"]),
            ]
        ],
        colWidths=[content_width * 0.34, content_width * 0.66],
    )
    header_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#f8fafc")),
                ("LINEBELOW", (0, 0), (-1, -1), 1.1, accent),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )

    total_label_value = _summary_total(headers, rows)
    summary_cells = [
        Paragraph(f"<b>Période</b><br/>{date_from.strftime('%d/%m/%Y')} - {date_to.strftime('%d/%m/%Y')}", styles["ReportMeta"]),
        Paragraph(f"<b>Magasin</b><br/>{_pdf_text(store_label)}", styles["ReportMeta"]),
        Paragraph(f"<b>Lignes</b><br/>{len(rows)}", styles["ReportMeta"]),
        Paragraph(f"<b>Généré le</b><br/>{generated_at}", styles["ReportMeta"]),
    ]
    if total_label_value:
        label, total = total_label_value
        summary_cells.append(Paragraph(f"<b>{_pdf_text(label)}</b><br/>{_pdf_text(_format_pdf_value(total))}", styles["ReportMeta"]))

    summary_table = Table([summary_cells], colWidths=[content_width / len(summary_cells)] * len(summary_cells))
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#dbeafe")),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#e5e7eb")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )

    table_rows = [[Paragraph(f"<b>{_pdf_text(header)}</b>", styles["ReportHeaderCell"]) for header in headers]]
    if rows:
        for row in rows[:500]:
            table_rows.append(
                [
                    Paragraph(_pdf_text(_format_pdf_value(row[index] if index < len(row) else "")), styles["ReportCell"])
                    for index, _header in enumerate(headers)
                ]
            )
    else:
        table_rows.append([Paragraph("Aucune donnée disponible pour cette période.", styles["ReportCell"])] + [""] * (len(headers) - 1))

    report_table = Table(
        table_rows,
        colWidths=_column_widths(headers, content_width),
        repeatRows=1,
        hAlign="LEFT",
    )
    report_style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("LINEBELOW", (0, 0), (-1, 0), 1, accent),
    ]
    for index, header in enumerate(headers):
        if any(keyword in header.lower() for keyword in ["total", "montant", "prix", "quantite", "stock", "heures", "retard"]):
            report_style.append(("ALIGN", (index, 1), (index, -1), "RIGHT"))
    report_table.setStyle(TableStyle(report_style))

    story = [
        header_table,
        Spacer(1, 0.28 * cm),
        summary_table,
        Spacer(1, 0.32 * cm),
        KeepTogether(
            [
                Paragraph(
                    "Détail du rapport",
                    ParagraphStyle(
                        "ReportSection",
                        parent=styles["Normal"],
                        fontName="Helvetica-Bold",
                        fontSize=10,
                        textColor=colors.HexColor("#0f172a"),
                    ),
                ),
                Spacer(1, 0.12 * cm),
            ]
        ),
        report_table,
    ]
    if len(rows) > 500:
        story.extend(
            [
                Spacer(1, 0.15 * cm),
                Paragraph("Affichage limité aux 500 premières lignes.", styles["ReportMeta"]),
            ]
        )

    doc.build(story, onFirstPage=_report_footer(title), onLaterPages=_report_footer(title))
    filename = f"{kind}.pdf"
    buffer.seek(0)
    response = FileResponse(buffer, as_attachment=False, filename=filename, content_type="application/pdf")
    response["X-Content-Type-Options"] = "nosniff"
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
            return _pdf_response(kind, headers, rows, request)
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
