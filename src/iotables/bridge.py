"""BEA's PCE bridge: personal consumption expenditures by NIPA line, in producers'
and purchasers' prices (design spec sections 6.2 and 8.5).

Each bridge row is one (NIPA line, commodity) pair: the commodity's producers'
value, the transportation costs and wholesale and retail margins on its way to
the consumer, and their sum, the purchasers' value ($ millions). The price model
(`leontief.PriceModel`) turns commodity price changes into PCE category price
changes with it; the margin dollars take the price changes of the margin
commodities listed in MARGIN_CODES.

`parse_pce_bridge` reads one year sheet of the bridge workbook and
`load_pce_bridge` downloads (cached) and reads it.
"""

import json
import numbers
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import openpyxl
import pandas as pd

from iotables import download
from iotables.parse import list_year_sheets, normalize_code
from iotables.sources import RAW_DIR, bea_detail_url

# The commodities that supply each margin, by table level (verified against the
# 2017 detail tables, spec 8.5). Wholesale is the ten 42xxxx commodities without
# 4200ID (customs duties).
MARGIN_CODES: dict[str, dict[str, list[str]]] = {
    "detail": {
        "transport": ["481000", "482000", "483000", "484000", "486000"],
        "wholesale": ["423100", "423400", "423600", "423800", "423A00",
                      "424200", "424400", "424700", "424A00", "425000"],
        "retail": ["441000", "444000", "445000", "446000", "447000",
                   "448000", "452000", "454000", "4B0000"],
    },
}

COLUMNS = ["nipa_line", "pce_category", "commodity", "commodity_desc", "producers_value",
           "transport", "wholesale", "retail", "purchasers_value"]

# The year sheet's layout, by 0-based column: the header row (the row whose
# first cell is "NIPA Line") and the group-label row above it. The columns are
# read by position, so both rows are checked before any data is read.
_HEADER = {0: "nipa line", 1: "pce category", 2: "commodity code", 3: "commodity description",
           6: "wholesale", 7: "retail", 9: "year"}
_GROUPS = {4: "producers' value", 5: "transportation costs", 6: "trade margins",
           8: "purchasers' value"}
_WIDTH = 10  # columns A-J: the header's nine data columns and Year


@dataclass
class PCEBridge:
    """One year of the PCE bridge ($ millions).

    `rows` has one row per (NIPA line, commodity), in the sheet's order, with
    columns nipa_line (str), pce_category, commodity (str), commodity_desc,
    producers_value, transport, wholesale, retail and purchasers_value (float).
    `meta` holds path, sheet, year and title (and, from `load_pce_bridge`,
    level and provenance).
    """

    rows: pd.DataFrame
    year: int
    meta: dict

    def categories(self) -> pd.DataFrame:
        """One row per NIPA line, in first-appearance order: nipa_line, pce_category
        (its first row's) and purchasers_value (the sum over its rows)."""
        lines = self.rows.groupby("nipa_line", sort=False)
        return pd.DataFrame({
            "pce_category": lines["pce_category"].first(),
            "purchasers_value": lines["purchasers_value"].sum(),
        }).reset_index()


def _cell(row: tuple, j: int):
    return row[j] if j < len(row) else None


def _text(x) -> str:
    return "" if x is None else str(x).strip()


def _value(x, sheet: str, row: int) -> float:
    """A value cell as a float; a blank cell is 0."""
    if x is None or _text(x) == "":
        return 0.0
    if isinstance(x, numbers.Real) and not isinstance(x, bool):
        return float(x)
    raise ValueError(f"sheet {sheet!r}, row {row}: non-numeric value {x!r}")


def _check_layout(header: tuple, groups: tuple, sheet: str) -> None:
    wrong = [f"column {j + 1}: {_text(_cell(row, j))!r}, expected {label!r}"
             for row, labels in ((header, _HEADER), (groups, _GROUPS))
             for j, label in labels.items()
             if _text(_cell(row, j)).lower() != label]
    if wrong:
        raise ValueError(f"sheet {sheet!r}: not the PCE bridge layout ({'; '.join(wrong)})")


def _resolve_year(path: Path, year: int | str) -> int:
    years = list_year_sheets(path)
    if year == "latest":
        if not years:
            raise ValueError(f"{path}: no year sheets (4-digit sheet names) found")
        return max(years)
    try:
        year = int(year)
    except (TypeError, ValueError):
        raise ValueError(f"year must be an integer or 'latest', got {year!r}") from None
    if year not in years:
        raise ValueError(f"{path}: no sheet for year {year}; available years: {years}")
    return year


def parse_pce_bridge(path: Path, year: int | str = "latest") -> PCEBridge:
    """Read the bridge sheet for `year` ("latest" = the newest year sheet).

    The header is the first row whose first cell is "NIPA Line"; the row above
    it holds the group labels (Producers' Value, Transportation Costs, Trade
    Margins, Purchasers' Value) that name the columns the header leaves blank,
    and both are checked against the expected layout (ValueError otherwise).
    Data rows follow the header until the first blank row. NIPA lines and
    commodity codes are coerced with `normalize_code`; blank value cells are 0.
    Raises ValueError for a missing year sheet or header, a data row without a
    NIPA line or commodity code, a non-numeric value or no data rows.
    """
    path = Path(path)
    year = _resolve_year(path, year)
    sheet = str(year)
    with closing(openpyxl.load_workbook(path, read_only=True, data_only=True)) as wb:
        ws = wb[sheet]
        ws.reset_dimensions()  # some BEA files declare a bogus used range
        rows = list(ws.iter_rows(values_only=True))

    header_idx = next(
        (i for i, r in enumerate(rows) if _text(_cell(r, 0)).lower() == "nipa line"), None
    )
    if header_idx is None:
        raise ValueError(f"sheet {sheet!r}: no row with 'NIPA Line' in column A")
    if header_idx == 0:
        raise ValueError(f"sheet {sheet!r}: 'NIPA Line' row has no group-label row above it")
    _check_layout(rows[header_idx], rows[header_idx - 1], sheet)

    records = []
    for i, r in enumerate(rows[header_idx + 1:], start=header_idx + 2):  # i: the Excel row number
        if all(_text(c) == "" for c in r):
            break
        cells = [_cell(r, j) for j in range(_WIDTH)]
        nipa_line, commodity = normalize_code(cells[0]), normalize_code(cells[2])
        if nipa_line is None or commodity is None:
            raise ValueError(f"sheet {sheet!r}, row {i}: no NIPA line or commodity code")
        values = [_value(c, sheet, i) for c in cells[4:9]]
        records.append([nipa_line, _text(cells[1]), commodity, _text(cells[3]), *values])
    if not records:
        raise ValueError(f"sheet {sheet!r}: no data rows below the header")

    frame = pd.DataFrame(records, columns=COLUMNS)
    meta = {"path": str(path), "sheet": sheet, "year": year, "title": _text(_cell(rows[0], 0))}
    return PCEBridge(rows=frame, year=year, meta=meta)


def load_pce_bridge(
    level: str = "detail",
    year: int | str = "latest",
    data_dir: Path = RAW_DIR,
    force: bool = False,
) -> PCEBridge:
    """Download (cached, into `data_dir / "bea"`) and parse BEA's detail PCE bridge.

    The bridge's `meta` gains `level` and `provenance` (the download sidecar).
    """
    if level != "detail":
        raise NotImplementedError("only the detail level is available")
    path = download.fetch(bea_detail_url("pce_bridge"), Path(data_dir) / "bea", force=force)
    pce_bridge = parse_pce_bridge(path, year)
    pce_bridge.meta["level"] = level
    pce_bridge.meta["provenance"] = json.loads(
        path.with_name(path.name + ".provenance.json").read_text()
    )
    return pce_bridge
