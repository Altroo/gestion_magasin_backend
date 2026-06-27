from decimal import Decimal
from io import BytesIO

from django.http import HttpResponse
from django.utils.html import escape
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _format_number(value, decimals: int = 2) -> str:
    number = Decimal(str(value or "0"))
    return f"{number:,.{decimals}f}".replace(",", " ")


def _number_to_french_words(number: Decimal) -> str:
    units = [
        "",
        "un",
        "deux",
        "trois",
        "quatre",
        "cinq",
        "six",
        "sept",
        "huit",
        "neuf",
        "dix",
        "onze",
        "douze",
        "treize",
        "quatorze",
        "quinze",
        "seize",
        "dix-sept",
        "dix-huit",
        "dix-neuf",
    ]
    tens = [
        "",
        "",
        "vingt",
        "trente",
        "quarante",
        "cinquante",
        "soixante",
        "soixante",
        "quatre-vingt",
        "quatre-vingt",
    ]

    def below_100(n: int) -> str:
        if n < 20:
            return units[n]
        if n < 70:
            ten, unit = divmod(n, 10)
            if unit == 1 and ten != 8:
                return f"{tens[ten]} et un"
            if unit == 0:
                return "quatre-vingts" if ten == 8 else tens[ten]
            return f"{tens[ten]}-{units[unit]}"
        if n < 80:
            unit = n - 60
            return "soixante et onze" if unit == 11 else f"soixante-{units[unit]}"
        unit = n - 80
        return "quatre-vingts" if unit == 0 else f"quatre-vingt-{units[unit]}"

    def below_1000(n: int) -> str:
        if n < 100:
            return below_100(n)
        hundred, remainder = divmod(n, 100)
        if hundred == 1:
            return "cent" if remainder == 0 else f"cent {below_100(remainder)}"
        return f"{units[hundred]} cents" if remainder == 0 else f"{units[hundred]} cent {below_100(remainder)}"

    def full(n: int) -> str:
        if n == 0:
            return "zero"
        parts = []
        if n >= 1_000_000:
            millions, n = divmod(n, 1_000_000)
            parts.append("un million" if millions == 1 else f"{below_1000(millions)} millions")
        if n >= 1000:
            thousands, n = divmod(n, 1000)
            parts.append("mille" if thousands == 1 else f"{below_1000(thousands)} mille")
        if n > 0:
            parts.append(below_1000(n))
        return " ".join(parts)

    int_part = int(number)
    centimes = int((number - int_part) * 100)
    words = f"{full(int_part).upper()} DIRHAMS"
    if centimes:
        words += f" ET {full(centimes).upper()} CENTIMES"
    return words


def _styles():
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="DocTitle",
            parent=styles["Heading1"],
            fontSize=20,
            leading=24,
            alignment=TA_RIGHT,
            textColor=colors.HexColor("#1976d2"),
        )
    )
    styles.add(ParagraphStyle(name="DocDate", parent=styles["Normal"], fontSize=9, alignment=TA_RIGHT))
    styles.add(ParagraphStyle(name="SectionHeader", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#1976d2")))
    styles.add(ParagraphStyle(name="Small", parent=styles["Normal"], fontSize=8, leading=10))
    styles.add(ParagraphStyle(name="SmallCenter", parent=styles["Small"], alignment=TA_CENTER))
    styles.add(ParagraphStyle(name="SmallRight", parent=styles["Small"], alignment=TA_RIGHT))
    styles.add(ParagraphStyle(name="AmountWords", parent=styles["Normal"], fontSize=10, leading=13))
    return styles


def _parties_table(sale, styles, content_width):
    issuer = sale.store
    customer = sale.customer
    left_rows = [
        [Paragraph("<b>FACTURE CLIENT EMISE PAR</b>", styles["SectionHeader"])],
        [Paragraph(f"<b>{escape(issuer.name)}</b>", styles["Small"])],
    ]
    if issuer.address:
        left_rows.append([Paragraph(f"Adresse: {escape(issuer.address)}", styles["Small"])])
    if issuer.phone:
        left_rows.append([Paragraph(f"Tel: {escape(issuer.phone)}", styles["Small"])])

    right_rows = [[Paragraph("<b>DESTINATAIRE</b>", styles["SectionHeader"])]]
    if customer:
        right_rows.append([Paragraph(f"<b>{escape(customer.full_name)}</b>", styles["Small"])])
        if customer.phone:
            right_rows.append([Paragraph(f"Tel: {escape(customer.phone)}", styles["Small"])])
        if customer.email:
            right_rows.append([Paragraph(f"Email: {escape(customer.email)}", styles["Small"])])
    else:
        right_rows.append([Paragraph("<b>Client comptoir</b>", styles["Small"])])

    col_width = content_width / 2 - 0.25 * cm
    left = Table(left_rows, colWidths=[col_width])
    right = Table(right_rows, colWidths=[col_width])
    style = TableStyle(
        [
            ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#1976d2")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
    )
    left.setStyle(style)
    right.setStyle(style)
    table = Table([[left, right]], colWidths=[content_width / 2, content_width / 2])
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return table


def _lines_table(sale, styles, content_width):
    headers = ["Designation", "Qte", "TVA", "PRIX UNIT. HT", "Total HT"]
    data = [[Paragraph(f"<b>{item}</b>", styles["SmallCenter"]) for item in headers]]

    for line in sale.lines.select_related("product").all():
        designation = escape(line.product.name)
        if line.product.reference:
            designation = f"<b>{escape(line.product.reference)}</b><br/>{designation}"
        data.append(
            [
                Paragraph(designation, styles["Small"]),
                Paragraph(_format_number(line.quantity, 3), styles["SmallCenter"]),
                Paragraph("0%", styles["SmallCenter"]),
                Paragraph(f"{_format_number(line.unit_price)} MAD", styles["SmallCenter"]),
                Paragraph(f"{_format_number(line.total)} MAD", styles["SmallCenter"]),
            ]
        )

    for line in sale.promotion_lines.select_related("promotion").all():
        data.append(
            [
                Paragraph(f"<b>Promotion</b><br/>{escape(line.promotion.name)}", styles["Small"]),
                Paragraph(_format_number(line.quantity, 3), styles["SmallCenter"]),
                Paragraph("0%", styles["SmallCenter"]),
                Paragraph(f"{_format_number(line.unit_price)} MAD", styles["SmallCenter"]),
                Paragraph(f"{_format_number(line.total)} MAD", styles["SmallCenter"]),
            ]
        )

    fixed = 2 * cm + 1.8 * cm + 3 * cm + 3.7 * cm
    table = Table(
        data,
        colWidths=[content_width - fixed, 2 * cm, 1.8 * cm, 3 * cm, 3.7 * cm],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f5f5f5")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#333333")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e0e0e0")),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                ("TOPPADDING", (0, 1), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
            ]
        )
    )
    return table


def _totals_table(sale, styles):
    rows = [
        [Paragraph("<b>Total HT</b>", styles["Small"]), Paragraph(f"{_format_number(sale.subtotal)} MAD", styles["SmallRight"])],
    ]
    if sale.discount_amount:
        rows.append(
            [
                Paragraph("<b>Remise</b>", styles["Small"]),
                Paragraph(f"{_format_number(sale.discount_amount)} MAD", styles["SmallRight"]),
            ]
        )
    rows.extend(
        [
            [Paragraph("<b>TVA</b>", styles["Small"]), Paragraph("0.00 MAD", styles["SmallRight"])],
            [Paragraph("<b>Total TTC</b>", styles["Small"]), Paragraph(f"{_format_number(sale.total)} MAD", styles["SmallRight"])],
        ]
    )
    table = Table(rows, colWidths=[5 * cm, 4 * cm])
    table.hAlign = "RIGHT"
    table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LINEABOVE", (0, 0), (-1, 0), 1, colors.HexColor("#333333")),
                ("LINEBELOW", (0, -1), (-1, -1), 1, colors.HexColor("#333333")),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f0f0f0")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def build_sale_facture_pdf(sale):
    buffer = BytesIO()
    margin = 0.7 * cm
    content_width = A4[0] - 2 * margin
    styles = _styles()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=margin,
        leftMargin=margin,
        topMargin=margin,
        bottomMargin=1.3 * cm,
        title=f"Facture vente #{sale.pk}",
    )
    elements = [
        Table(
            [
                [
                    Paragraph(f"<b>{escape(sale.store.name)}</b>", styles["Small"]),
                    Paragraph(f"<b>FACTURE CLIENT N° {sale.pk}</b>", styles["DocTitle"]),
                ],
                ["", Paragraph(f"DATE DE LA FACTURE: {sale.date_created:%d/%m/%Y}", styles["DocDate"])],
            ],
            colWidths=[content_width / 2, content_width / 2],
        ),
        Spacer(1, 0.35 * cm),
        _parties_table(sale, styles, content_width),
        Spacer(1, 0.45 * cm),
        _lines_table(sale, styles, content_width),
        Spacer(1, 0.35 * cm),
        _totals_table(sale, styles),
        Spacer(1, 0.35 * cm),
        Paragraph("<b>ARRETEE LA PRESENTE FACTURE CLIENT A LA SOMME DE</b>", styles["SectionHeader"]),
        Spacer(1, 0.15 * cm),
        Paragraph(f"{_number_to_french_words(Decimal(sale.total))} TTC", styles["AmountWords"]),
    ]
    doc.build(elements)
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="facture-vente-{sale.pk}.pdf"'
    return response
