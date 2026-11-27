from __future__ import annotations

import csv
import io
from datetime import date, datetime

import openpyxl
import xlrd

from core.domain.exceptions import PayloadTooLargeError, ValidationDomainError
from core.domain.value_objects import ImportType

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_DATA_ROWS = 10_000
SUPPORTED_EXTENSIONS = ("csv", "xlsx", "xls")


def normalize_import_type(raw_type: str) -> str:
    cleaned = str(raw_type or "").strip().lower()
    if cleaned == "cashflow":
        return ImportType.SETTLED.value
    if cleaned in {item.value for item in ImportType}:
        return cleaned
    raise ValidationDomainError(
        "Selecione o tipo de dados.",
        fields={"type": ["Use receivable, payable, settled ou cashflow."]},
    )


def _format_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def _decode_csv(raw_bytes: bytes) -> str:
    if b"\x00" in raw_bytes or raw_bytes.startswith(b"PK\x03\x04") or raw_bytes.startswith(
        b"\xd0\xcf\x11\xe0"
    ):
        raise ValidationDomainError(
            "O conteúdo não corresponde ao formato CSV.",
            fields={"file": ["Envie um arquivo CSV válido."]},
        )
    try:
        return raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw_bytes.decode("cp1252", errors="replace")


def _detect_csv_delimiter(sample_text: str) -> str:
    first_line = next((line for line in sample_text.splitlines() if line.strip()), "")
    if first_line.count(";") > first_line.count(","):
        return ";"
    if first_line.count("\t") > first_line.count(","):
        return "\t"
    return ","


def _read_csv_rows(raw_bytes: bytes) -> list[list[str]]:
    text = _decode_csv(raw_bytes)
    delimiter = _detect_csv_delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return [[_format_cell(cell) for cell in row] for row in reader]


def _read_xlsx_rows(raw_bytes: bytes) -> list[list[str]]:
    if not raw_bytes.startswith(b"PK\x03\x04"):
        raise ValidationDomainError(
            "O conteúdo não corresponde ao formato XLSX.",
            fields={"file": ["Arquivo XLSX inválido ou corrompido."]},
        )
    try:
        wb = openpyxl.load_workbook(
            io.BytesIO(raw_bytes),
            read_only=True,
            data_only=True,
        )
        try:
            sheet = wb.worksheets[0]
            rows: list[list[str]] = []
            for idx, row in enumerate(sheet.iter_rows(values_only=True)):
                if idx > MAX_DATA_ROWS + 5:
                    raise ValidationDomainError(
                        "O arquivo excede o limite de 10.000 linhas.",
                        fields={"file": ["Limite máximo de 10.000 linhas de dados."]},
                    )
                rows.append([_format_cell(cell) for cell in row])
            return rows
        finally:
            wb.close()
    except ValidationDomainError:
        raise
    except Exception as exc:
        raise ValidationDomainError(
            "Não foi possível ler o conteúdo da planilha XLSX.",
            fields={"file": ["Arquivo XLSX malformado."]},
        ) from exc


def _read_xls_rows(raw_bytes: bytes) -> list[list[str]]:
    if not raw_bytes.startswith(b"\xd0\xcf\x11\xe0"):
        raise ValidationDomainError(
            "O conteúdo não corresponde ao formato XLS.",
            fields={"file": ["Arquivo XLS inválido ou corrompido."]},
        )
    try:
        book = xlrd.open_workbook(file_contents=raw_bytes, on_demand=True)
        try:
            sheet = book.sheet_by_index(0)
            if sheet.nrows - 1 > MAX_DATA_ROWS:
                raise ValidationDomainError(
                    "O arquivo excede o limite de 10.000 linhas.",
                    fields={"file": ["Limite máximo de 10.000 linhas de dados."]},
                )
            rows: list[list[str]] = []
            for row_idx in range(sheet.nrows):
                row_values: list[str] = []
                for col_idx in range(sheet.ncols):
                    cell = sheet.cell(row_idx, col_idx)
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        dt = xlrd.xldate_as_datetime(cell.value, book.datemode)
                        row_values.append(dt.date().isoformat())
                    elif cell.ctype == xlrd.XL_CELL_NUMBER and float(cell.value).is_integer():
                        row_values.append(str(int(cell.value)))
                    else:
                        row_values.append(_format_cell(cell.value))
                rows.append(row_values)
            return rows
        finally:
            book.release_resources()
    except ValidationDomainError:
        raise
    except Exception as exc:
        raise ValidationDomainError(
            "Não foi possível ler o conteúdo da planilha XLS.",
            fields={"file": ["Arquivo XLS malformado."]},
        ) from exc


def read_spreadsheet_table(filename: str, raw_bytes: bytes) -> list[list[str]]:
    """Validates format/magic-bytes/limits and parses the first sheet into clean rows."""
    extension = str(filename or "").rsplit(".", 1)[-1].lower() if "." in str(filename or "") else ""
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValidationDomainError(
            "Envie um arquivo CSV, XLSX ou XLS.",
            fields={"file": ["Formato não suportado. Use CSV, XLSX ou XLS."]},
        )
    if not raw_bytes or len(raw_bytes) > MAX_UPLOAD_BYTES:
        raise PayloadTooLargeError()

    if extension == "csv":
        raw_rows = _read_csv_rows(raw_bytes)
    elif extension == "xlsx":
        raw_rows = _read_xlsx_rows(raw_bytes)
    else:
        raw_rows = _read_xls_rows(raw_bytes)

    non_empty = [row for row in raw_rows if any(str(cell).strip() for cell in row)]
    if len(non_empty) < 2:
        raise ValidationDomainError(
            "A primeira aba deve ter cabeçalhos e pelo menos uma linha de dados.",
            fields={"file": ["Planilha sem linhas de dados válidas."]},
        )
    if len(non_empty) - 1 > MAX_DATA_ROWS:
        raise ValidationDomainError(
            "O arquivo excede o limite de 10.000 linhas.",
            fields={"file": ["Limite máximo de 10.000 linhas de dados."]},
        )

    width = max(len(row) for row in non_empty)
    return [row + [""] * (width - len(row)) for row in non_empty]
