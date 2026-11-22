"""Stage 2: read raw BEA xlsx worksheets into labeled pandas objects.

`read_bea_grid` finds the header by content (the row whose column A is "Code"),
never by fixed offsets, and aligns everything by BEA code, never by position.
`MakeTable.from_grid` and `UseTable.from_grid` then split a grid into data and
totals by code prefix (T0... totals, F... final demand, V001-V003 value added),
and `load_bea_tables` downloads, reads and splits the make and use workbooks.
"""

import json
import math
import numbers
import re
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import openpyxl
import pandas as pd

from iotables import download
from iotables.sources import RAW_DIR, bea_detail_url

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


_VALUE_ADDED_CODES = ("V00100", "V00200", "V00300")


@dataclass
class MakeTable:
    """BEA make table: what each industry produces, by commodity ($ millions).

    `values` is industries x commodities. `industry_output` is BEA's T008
    column (over industries) and `commodity_output` its T007 row (over
    commodities); either is None when the grid lacks that total.
    """

    values: pd.DataFrame
    industry_labels: pd.Series
    commodity_labels: pd.Series
    industry_output: pd.Series | None
    commodity_output: pd.Series | None
    meta: dict

    @classmethod
    def from_grid(cls, grid: BeaGrid, meta: dict | None = None) -> "MakeTable":
        """Rows and columns whose code starts with "T0" are totals; the rest is data."""
        industries = [c for c in grid.values.index if not c.startswith("T0")]
        commodities = [c for c in grid.values.columns if not c.startswith("T0")]
        return cls(
            values=grid.values.loc[industries, commodities],
            industry_labels=grid.row_labels.loc[industries],
            commodity_labels=grid.col_labels.loc[commodities],
            industry_output=(
                grid.values.loc[industries, "T008"] if "T008" in grid.values.columns else None
            ),
            commodity_output=(
                grid.values.loc["T007", commodities] if "T007" in grid.values.index else None
            ),
            meta=dict(meta or {}),
        )

    @property
    def industries(self) -> list[str]:
        return list(self.values.index)

    @property
    def commodities(self) -> list[str]:
        return list(self.values.columns)


@dataclass
class UseTable:
    """BEA use table: what each industry and final-demand category buys ($ millions).

    `intermediate` is commodities x industries, `final_demand` commodities x
    F-codes, `value_added` the rows V00100, V00200, V00300 x industries.
    `industry_output` is BEA's T008 row (over industries) and
    `commodity_output` its T007 column (over commodities); either is None when
    the grid lacks that total.
    """

    intermediate: pd.DataFrame
    final_demand: pd.DataFrame
    value_added: pd.DataFrame
    commodity_labels: pd.Series
    industry_labels: pd.Series
    final_demand_labels: pd.Series
    industry_output: pd.Series | None
    commodity_output: pd.Series | None
    meta: dict

    @classmethod
    def from_grid(cls, grid: BeaGrid, meta: dict | None = None) -> "UseTable":
        """Split a use grid by code, never by position.

        Rows: V00100, V00200 and V00300 are value added (all three required),
        codes starting "T0" are totals, the rest are commodities. Columns:
        codes starting "F" are final demand, "T0" totals, the rest industries.
        """
        values = grid.values
        missing = [c for c in _VALUE_ADDED_CODES if c not in values.index]
        if missing:
            raise ValueError(f"use table has no value-added rows {missing}")
        commodities = [
            c for c in values.index if c not in _VALUE_ADDED_CODES and not c.startswith("T0")
        ]
        final_demand = [c for c in values.columns if c.startswith("F")]
        industries = [c for c in values.columns if not c.startswith(("F", "T0"))]
        return cls(
            intermediate=values.loc[commodities, industries],
            final_demand=values.loc[commodities, final_demand],
            value_added=values.loc[list(_VALUE_ADDED_CODES), industries],
            commodity_labels=grid.row_labels.loc[commodities],
            industry_labels=grid.col_labels.loc[industries],
            final_demand_labels=grid.col_labels.loc[final_demand],
            industry_output=values.loc["T008", industries] if "T008" in values.index else None,
            commodity_output=(
                values.loc[commodities, "T007"] if "T007" in values.columns else None
            ),
            meta=dict(meta or {}),
        )

    @property
    def industries(self) -> list[str]:
        return list(self.intermediate.columns)

    @property
    def commodities(self) -> list[str]:
        return list(self.intermediate.index)


def _read_year_sheet(path: Path, year: int | str) -> tuple[BeaGrid, dict]:
    """Read the sheet for `year` ("latest" = the newest year sheet) and its meta."""
    years = list_year_sheets(path)
    if year == "latest":
        if not years:
            raise ValueError(f"{path}: no year sheets (4-digit sheet names) found")
        year = max(years)
    else:
        try:
            year = int(year)
        except (TypeError, ValueError):
            raise ValueError(f"year must be an integer or 'latest', got {year!r}") from None
        if year not in years:
            raise ValueError(f"{path}: no sheet for year {year}; available years: {years}")
    grid = read_bea_grid(path, str(year))
    meta = {"path": str(path), "sheet": str(year), "year": year, "title": grid.title}
    return grid, meta


def parse_make(path: Path, year: int | str = "latest") -> MakeTable:
    """Read the make table for `year` ("latest" = the newest year sheet)."""
    grid, meta = _read_year_sheet(Path(path), year)
    return MakeTable.from_grid(grid, meta)


def parse_use(path: Path, year: int | str = "latest") -> UseTable:
    """Read the use table for `year` ("latest" = the newest year sheet)."""
    grid, meta = _read_year_sheet(Path(path), year)
    return UseTable.from_grid(grid, meta)


def load_bea_tables(
    level: str = "detail",
    year: int | str = "latest",
    redefinitions: str = "after",
    data_dir: Path = RAW_DIR,
    force: bool = False,
) -> tuple[MakeTable, UseTable]:
    """Download (cached) and parse the BEA make and use workbooks.

    Files land in `data_dir / "bea"`. Each table's `meta` gains `level`,
    `redefinitions` and `provenance` (the download sidecar: url, sha256,
    bytes, downloaded_at); `year` is the resolved integer year.
    """
    if level != "detail":
        raise NotImplementedError("summary level arrives in Phase 2")
    bea_dir = Path(data_dir) / "bea"
    tables = []
    for kind, parser in (("make", parse_make), ("use", parse_use)):
        path = download.fetch(bea_detail_url(kind, redefinitions), bea_dir, force=force)
        table = parser(path, year)
        table.meta["level"] = level
        table.meta["redefinitions"] = redefinitions
        table.meta["provenance"] = json.loads(
            path.with_name(path.name + ".provenance.json").read_text()
        )
        tables.append(table)
    make, use = tables
    return make, use
