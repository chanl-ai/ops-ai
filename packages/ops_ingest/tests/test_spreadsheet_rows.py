"""A spreadsheet as a header and rows (c-535), for batches: a CSV's dialect or quoted commas splitting a value; an
Excel file read differently from the same table as CSV; blank trailing rows counted as rows."""

from __future__ import annotations

import io

from openpyxl import Workbook

from ops_ingest.parsers.spreadsheet import spreadsheet_rows

HEADER = ["claim_ref", "Policy number", "note"]
ROWS = [["HM-22918", "P-77120", "Called, no answer"], ["HM-22921", "P-60419", ""]]


def test_a_csv_keeps_quoted_commas_and_reads_its_own_delimiter() -> None:
    comma = b'claim_ref,Policy number,note\nHM-22918,P-77120,"Called, no answer"\nHM-22921,P-60419,\n\n'
    semicolon = b"claim_ref;Policy number;note\nHM-22918;P-77120;Called, no answer\nHM-22921;P-60419;\n"
    for data in (comma, semicolon):
        header, rows = spreadsheet_rows(data, filename="claims.csv")
        assert header == HEADER and rows == [dict(zip(HEADER, r, strict=True)) for r in ROWS], (header, rows)


def test_an_excel_file_reads_as_the_same_table() -> None:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    for r in [HEADER, *ROWS]:
        sheet.append(r)
    buf = io.BytesIO()
    book.save(buf)
    header, rows = spreadsheet_rows(buf.getvalue(), filename="claims.xlsx")
    assert header == HEADER and rows == [dict(zip(HEADER, r, strict=True)) for r in ROWS], (header, rows)
