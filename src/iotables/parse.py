"""Stage 2: read raw BEA xlsx worksheets into labeled pandas objects.

`read_bea_grid` finds the header by content (the row whose column A is "Code"),
never by fixed offsets, and aligns everything by BEA code, never by position.
Interpreting a grid as a make or use table is done by later steps.
"""

import math
import numbers
import re
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import openpyxl
import pandas as pd

# Codes synthesized for header cells whose code cell is empty but whose
# description matches (BEA leaves these columns uncoded).
UNCODED_TOTALS = {
    "Total Final Uses (GDP)": "T004",
    "Total Commodity Output": "T007",
    "Total Industry Output": "T008",
}

_FIRST_LABEL_COL = 1  # column B: row descriptions
_FIRST_DATA_COL = 2  # column C: first data column


@dataclass
class BeaGrid:
    """A BEA worksheet as a code-indexed value grid plus its labels.

    `values` has row codes as index and column codes as columns (float, blanks
    as 0.0); `row_labels` and `col_labels` map code -> description.
    """

    values: pd.DataFrame
    row_labels: pd.Series
    col_labels: pd.Series
    title: str


def normalize_code(x) -> str | None:
    """Coerce a code cell to a stripped string; blank cells become None.

    Integer-valued numbers lose their decimal part (1110.0 -> "1110").
    """
    if x is None:
        return None
    if isinstance(x, float) and math.isnan(x):
        return None
    if isinstance(x, numbers.Integral):
        return str(int(x))
    if isinstance(x, numbers.Real) and float(x).is_integer():
        return str(int(x))
    s = str(x).strip()
    return s or None


def _cell(row, j):
    """Cell j of a row tuple, or None when the row is shorter than j + 1."""
    return row[j] if j < len(row) else None


def _text(x) -> str:
    return "" if x is None else str(x).strip()


def _unique(codes: list[str], axis: str, sheet: str) -> None:
    dupes = sorted({c for c in codes if codes.count(c) > 1})
    if dupes:
        raise ValueError(f"sheet {sheet!r}: duplicate {axis} codes {dupes}")


def read_bea_grid(path: Path, sheet: str) -> BeaGrid:
    """Read one BEA worksheet into a BeaGrid.

    Header rule: the "Code" row is the first row whose column A, stripped and
    lower-cased, is "code"; column descriptions are the row directly above it
    and column codes run along it from column C (UNCODED_TOTALS fills empty
    codes, and the scan stops at the first column with neither code nor
    description). Data rows follow the "Code" row until the first row whose
    columns A and B are both empty. The title is cell A1.
    """
    with closing(openpyxl.load_workbook(path, read_only=True, data_only=True)) as wb:
        ws = wb[sheet]
        ws.reset_dimensions()  # some BEA files declare a bogus used range
        rows = list(ws.iter_rows(values_only=True))

    code_idx = next(
        (i for i, r in enumerate(rows) if _text(_cell(r, 0)).lower() == "code"), None
    )
    if code_idx is None:
        raise ValueError(f"sheet {sheet!r}: no row with 'Code' in column A")
    if code_idx == 0:
        raise ValueError(f"sheet {sheet!r}: 'Code' row has no description row above it")

    code_row, desc_row = rows[code_idx], rows[code_idx - 1]
    col_codes: list[str] = []
    col_descs: list[str] = []
    col_pos: list[int] = []
    for j in range(_FIRST_DATA_COL, max(len(code_row), len(desc_row))):
        code, desc = normalize_code(_cell(code_row, j)), _text(_cell(desc_row, j))
        if code is None and not desc:
            break
        if code is None:
            if desc not in UNCODED_TOTALS:
                raise ValueError(
                    f"sheet {sheet!r}: column {j + 1} ({desc!r}) has no code "
                    "and is not in UNCODED_TOTALS"
                )
            code = UNCODED_TOTALS[desc]
        col_codes.append(code)
        col_descs.append(desc)
        col_pos.append(j)

    row_codes: list[str] = []
    row_descs: list[str] = []
    data: list[list] = []
    for r in rows[code_idx + 1 :]:
        code, desc = normalize_code(_cell(r, 0)), _text(_cell(r, _FIRST_LABEL_COL))
        if code is None and not desc:
            break
        if code is None:
            raise ValueError(f"sheet {sheet!r}: data row {desc!r} has no code")
        row_codes.append(code)
        row_descs.append(desc)
        data.append([_cell(r, j) for j in col_pos])

    _unique(col_codes, "column", sheet)
    _unique(row_codes, "row", sheet)

    values = (
        pd.DataFrame(data, index=row_codes, columns=col_codes, dtype=object)
        .apply(pd.to_numeric, errors="coerce")
        .fillna(0.0)
        .astype(float)
    )
    return BeaGrid(
        values=values,
        row_labels=pd.Series(row_descs, index=row_codes, dtype=object),
        col_labels=pd.Series(col_descs, index=col_codes, dtype=object),
        title=_text(_cell(rows[0], 0)) if rows else "",
    )


def list_year_sheets(path: Path) -> list[int]:
    """Sheet names that are 4-digit years, as ascending ints."""
    with closing(openpyxl.load_workbook(path, read_only=True, data_only=True)) as wb:
        names = wb.sheetnames
    return sorted(int(n) for n in names if re.fullmatch(r"[0-9]{4}", n))
