from datetime import date, time
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


POINTAGE_HEADERS = [
    "Date",
    "Jour",
    "Nom salarié",
    "Heure entrée",
    "Début pause",
    "Fin pause",
    "Heure sortie",
    "Statut",
    "Shift",
    "Retard",
    "Observations",
]


def _format_time(value: time | None) -> str:
    if not value:
        return ""
    return f"{value.hour}H{value.minute:02d}" if value.minute else f"{value.hour}H"


def _format_delay(minutes: int | None) -> str:
    if not minutes:
        return "0:00"
    hours, remainder = divmod(int(minutes), 60)
    return f"{hours}:{remainder:02d}"


def _status_label(status: str | None) -> str:
    if status == "off":
        return "OFF"
    if status == "absent":
        return "ABSENT"
    return "ACTIVE"


def _shift_label(shift: str | None) -> str:
    if shift == "evening":
        return "EVENING"
    if shift == "off":
        return "OFF"
    return "MORNING"


def _day_label(value: date | None) -> str:
    return value.strftime("%A") if value else ""


def _auto_width(sheet):
    for column_cells in sheet.columns:
        column_letter = get_column_letter(column_cells[0].column)
        max_length = max(len(str(cell.value or "")) for cell in column_cells)
        sheet.column_dimensions[column_letter].width = min(max(max_length + 3, 12), 34)


def _style_sheet(sheet):
    blue_fill = PatternFill(start_color="CCE5FF", end_color="CCE5FF", fill_type="solid")
    header_fill = PatternFill(start_color="EAF3FF", end_color="EAF3FF", fill_type="solid")
    title_font = Font(bold=True, size=14)
    header_font = Font(bold=True)
    thin_border = Border(bottom=Side(style="thin", color="D9D9D9"))

    sheet.merge_cells("A2:K2")
    sheet["A2"].font = title_font
    sheet["A2"].fill = blue_fill
    sheet["A2"].alignment = Alignment(horizontal="center")

    for cell in sheet[3]:
        cell.font = header_font if cell.column in (1, 4, 7, 9) else Font()

    for cell in sheet[5]:
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border
        cell.alignment = Alignment(horizontal="center")

    for row in sheet.iter_rows(min_row=6):
        for cell in row:
            cell.border = thin_border
            cell.alignment = Alignment(vertical="center")

    _auto_width(sheet)


def build_attendance_workbook(records, *, responsible="", week_start=None, week_end=None) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Pointage"

    sheet.append([None] * len(POINTAGE_HEADERS))
    sheet.append(["FICHE DE POINTAGE HEBDOMADAIRE -MBR SOUTH", *([None] * 10)])
    sheet.append([
        "Responsable",
        responsible or "",
        None,
        "Semaine du",
        week_start or "",
        None,
        "au",
        week_end or "",
        "Envoyé le",
        date.today(),
        None,
    ])
    sheet.append([None] * len(POINTAGE_HEADERS))
    sheet.append(POINTAGE_HEADERS)

    for record in records:
        current_date = record.date
        clock_in = "OFF" if record.status == "off" else _format_time(record.clock_in)
        sheet.append([
            current_date,
            _day_label(current_date),
            record.employee.full_name,
            clock_in,
            _format_time(record.break_start),
            _format_time(record.break_end),
            _format_time(record.clock_out),
            _status_label(record.status),
            _shift_label(record.shift),
            _format_delay(record.delay_minutes),
            record.observations or "",
        ])

    _style_sheet(sheet)

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def build_attendance_import_template() -> bytes:
    class TemplateEmployee:
        full_name = "INES"

    class TemplateRecord:
        date = date.today()
        employee = TemplateEmployee()
        clock_in = time(9, 0)
        break_start = time(13, 30)
        break_end = time(14, 0)
        clock_out = time(17, 0)
        status = "present"
        shift = "morning"
        delay_minutes = 0
        observations = "NO"

    return build_attendance_workbook(
        [TemplateRecord()],
        responsible="Responsable",
        week_start=date.today(),
        week_end=date.today(),
    )
