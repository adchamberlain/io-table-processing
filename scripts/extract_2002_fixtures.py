"""Extract the 2002 regression fixtures (tests/fixtures/2002/) from the original 2002 workbooks.

One-time script, run by hand on 2026-11-22; never imported by the package or the tests.
It needs pandas, openpyxl and xlrd (for the BIFF .xls summary file). xlrd is not an
iotables dependency, so run it with an interpreter that has it, e.g. a scratch venv:

    <venv>/bin/python scripts/extract_2002_fixtures.py --source DIR [--out DIR]

Sources (read-only): --source (required) is the directory holding the original 2002
workbooks, at these relative file names:
  Carbon Tax Model/Data FIles/2002summary_makeuse.xls                 sheets MAKE, USE
  U.S. Input-Output Tables/2002 Summary Input-Output Table.xlsx       sheet 2002 Summary-Level
  U.S. Input-Output Tables/Supporting Files/2002 Detailed Make.xlsx   sheet Data
  U.S. Input-Output Tables/Supporting Files/2002 Detailed Use.xlsx    sheet Data
  U.S. Input-Output Tables/2002 Detailed Input-Output Table.xlsx      sheet 2002 Detailed Level

Outputs (--out, default tests/fixtures/2002 next to this script's repo): value grids with
codes as index (header "code") and column headers, in $ millions, at full precision:
  summary_make.csv, summary_use.csv       BEA's 2002 summary make and use tables
  summary_make_labels.csv, summary_use_labels.csv
                                          code,description: the row codes in table order,
                                          then the column codes in table order (a code on
                                          both axes appears once per axis)
  summary_target.csv                      the 2002 summary-level square table
  detail_make.csv.gz, detail_use.csv.gz   BEA's 2002 detailed make and use flat files, wide
  detail_target.csv.gz                    the 2002 detailed-level square table

Normalizations, and nothing else: codes become stripped strings with integer-valued
numbers as integer strings (1110.0 -> "1110"); summary codes S004 -> S00400 and
V001/V002/V003 -> V00100/V00200/V00300; the targets' total-output row and column (the
summary's column is coded T007, the detailed one is "Total") become T008; the
summary make's all-zero "N/A" (ROW of World) row is dropped; the summary use's T005 and
T006 rows are left out; the flat files are pivoted (duplicate pairs summed, absent pairs
0) and the detailed make gains a zero column for each regular use commodity it lacks
(exactly S00101). The targets leave the value-added rows and the total row blank under
final demand and T008; those cells are filled by SquareIOTable.to_frame's rule from the
sheet's own cells (value added under final demand 0, the T008 cell of a value-added row
its row sum, the total row the column sums over industries, its T008 cell its row sum).
Every other value is copied as stored; any blank or non-numeric cell elsewhere raises.
"""

import argparse
import gzip
import math
import numbers
import warnings
from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd
import xlrd

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "2002"
SUMMARY_MAKEUSE = "Carbon Tax Model/Data FIles/2002summary_makeuse.xls"
SUMMARY_TARGET = ("U.S. Input-Output Tables/2002 Summary Input-Output Table.xlsx", "2002 Summary-Level")
DETAIL_MAKE = "U.S. Input-Output Tables/Supporting Files/2002 Detailed Make.xlsx"
DETAIL_USE = "U.S. Input-Output Tables/Supporting Files/2002 Detailed Use.xlsx"
DETAIL_TARGET = ("U.S. Input-Output Tables/2002 Detailed Input-Output Table.xlsx", "2002 Detailed Level")

SUMMARY_RECODE = {"S004": "S00400", "V001": "V00100", "V002": "V00200", "V003": "V00300"}
VALUE_ADDED = ["V00100", "V00200", "V00300"]
# Commodities the build itself removes or redistributes; they are not given make columns.
SPECIAL_COMMODITIES = {"S00300", "S00900", "S00401", "S00402"}


def code(x) -> str | None:
    """A code cell as a stripped string (1110.0 -> "1110"); blank -> None."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    if isinstance(x, numbers.Real) and not isinstance(x, bool) and float(x).is_integer():
        return str(int(x))
    s = str(x).strip()
    return s or None


def number(x, where: str) -> float:
    if isinstance(x, bool) or not isinstance(x, numbers.Real):
        raise ValueError(f"{where}: expected a number, got {x!r}")
    return float(x)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


# --- summary make and use (BIFF .xls) --------------------------------------------------


def read_summary_sheet(book: xlrd.book.Book, sheet: str, header_text: str) -> tuple[pd.DataFrame, list, list]:
    """One summary sheet as (values, row labels, column labels), codes recoded.

    The code row is the row whose column C reads `header_text`; column names are the row
    above it; columns run from D to the first blank code. Data rows (code in B,
    description in C) run from the code row to the first row with B and C both blank.
    """
    sh = book.sheet_by_name(sheet)
    code_row = next(r for r in range(sh.nrows) if str(sh.cell_value(r, 2)).strip() == header_text)
    cols = []
    for c in range(3, sh.ncols):
        cc = code(sh.cell_value(code_row, c))
        if cc is None:
            break
        cols.append((c, SUMMARY_RECODE.get(cc, cc), str(sh.cell_value(code_row - 1, c)).strip()))
    rows, data = [], []
    for r in range(code_row + 1, sh.nrows):
        rc, desc = code(sh.cell_value(r, 1)), str(sh.cell_value(r, 2)).strip()
        if rc is None and not desc:
            break
        check(rc is not None, f"{sheet} row {r + 1} ({desc!r}) has no code")
        rows.append((SUMMARY_RECODE.get(rc, rc), desc))
        data.append([sh.cell_value(r, c) for c, _, _ in cols])
    values = pd.DataFrame(data, index=[r for r, _ in rows], columns=[c for _, c, _ in cols], dtype=object)
    for axis, codes in (("row", values.index), ("column", values.columns)):
        check(codes.is_unique, f"{sheet}: duplicate {axis} codes {sorted(codes[codes.duplicated()])}")
    return values, rows, [(c, d) for _, c, d in cols]


def to_numbers(values: pd.DataFrame, sheet: str, may_be_blank: np.ndarray | None = None) -> pd.DataFrame:
    """`values` as floats; raises for a non-number, except None (-> NaN) where `may_be_blank`."""
    cells = values.to_numpy(dtype=object)
    out = np.full(cells.shape, np.nan)
    for i, j in np.ndindex(cells.shape):
        v = cells[i, j]
        if v is None and may_be_blank is not None and may_be_blank[i, j]:
            continue
        out[i, j] = number(v, f"{sheet} [{values.index[i]}, {values.columns[j]}]")
    return pd.DataFrame(out, index=values.index, columns=values.columns)


def summary_make_use(path: Path) -> dict[str, tuple[pd.DataFrame, list]]:
    book = xlrd.open_workbook(str(path))
    make, make_rows, make_cols = read_summary_sheet(book, "MAKE", "Commodity code")
    check(make_rows[-1][0] == "T007", f"MAKE: last row is {make_rows[-1]}, expected T007")
    row_world = make.loc["N/A"]
    check(all(v == "" or v == 0 for v in row_world), f"MAKE: N/A (ROW of World) row is not all zero: {row_world[row_world != 0]}")
    make = to_numbers(make.drop(index="N/A"), "MAKE")
    make_rows = [r for r in make_rows if r[0] != "N/A"]
    industries = [r for r in make.index if r != "T007"]
    commodities = [c for c in make.columns if c != "T008"]
    check(len(industries) == 133 and len(commodities) == 134 and list(make.columns)[-1] == "T008",
          f"MAKE: {len(industries)} industries, {len(commodities)} commodities, last column {make.columns[-1]}")
    check("S00400" in commodities, "MAKE: no S00400 (scrap, used and secondhand goods) column")

    use, use_rows, use_cols = read_summary_sheet(book, "USE", "Industry code")
    keep_rows = [r for r in use.index if r not in ("T005", "T006")]
    use = to_numbers(use.loc[keep_rows], "USE")
    use_rows = [r for r in use_rows if r[0] in keep_rows]
    use_commodities = [r for r in use.index if r not in VALUE_ADDED and r != "T008"]
    check(list(use.index[-4:]) == VALUE_ADDED + ["T008"], f"USE: rows end {list(use.index[-4:])}")
    final_demand = [c for c in use.columns if c.startswith("F")]
    use_industries = [c for c in use.columns if not c.startswith(("F", "T0"))]
    check(len(final_demand) == 13 and [c for c in use.columns if c.startswith("T0")] == ["T001", "T004", "T007"],
          f"USE: final demand {final_demand}, totals {[c for c in use.columns if c.startswith('T0')]}")
    check(set(use_commodities) == set(commodities), f"MAKE/USE commodities do not match: {set(use_commodities) ^ set(commodities)}")
    check(set(use_industries) == set(industries), f"MAKE/USE industries do not match: {set(use_industries) ^ set(industries)}")
    return {"make": (make, make_rows + make_cols), "use": (use, use_rows + use_cols)}


# --- detailed make and use (flat xlsx files) --------------------------------------------


def read_flat(path: Path, header: list[str]) -> pd.DataFrame:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Unknown extension is not supported")
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        rows = list(wb["Data"].iter_rows(values_only=True))
        wb.close()
    check(list(rows[0]) == header, f"{path.name}: header {rows[0]}, expected {header}")
    frame = pd.DataFrame(rows[1:], columns=header)
    for col in (header[0], header[2]):
        frame[col] = [code(x) for x in frame[col]]
        check(frame[col].notna().all(), f"{path.name}: blank {col} code")
    frame["Value"] = [number(v, f"{path.name} Value") for v in frame["Value"]]
    return frame


def first_seen(codes: pd.Series) -> list[str]:
    return list(dict.fromkeys(codes))


def wide(flat: pd.DataFrame, row: str, col: str, rows: list[str], cols: list[str]) -> pd.DataFrame:
    """Pivot (row, col, Value) records; duplicate pairs are summed, absent pairs are 0."""
    dupes = flat.duplicated([row, col]).sum()
    if dupes:
        print(f"  {dupes} duplicate ({row}, {col}) pairs summed")
    summed = flat.groupby([row, col], sort=False)["Value"].sum()
    return summed.unstack(col, fill_value=0.0).reindex(index=rows, columns=cols, fill_value=0.0).astype(float)


def detail_make_use(make_path: Path, use_path: Path) -> dict[str, pd.DataFrame]:
    mk = read_flat(make_path, ["Industry", "IndustryDescription", "Commodity", "Commodity Description", "Value"])
    us = read_flat(use_path, ["Commodity", "Commodity Description", "Industry", "Industry Description", "Value"])
    check(len(mk) == 4759 and len(us) == 56759, f"flat files have {len(mk)} make and {len(us)} use records")

    industries = first_seen(mk["Industry"])
    make_commodities = first_seen(mk["Commodity"])
    use_rows = first_seen(us["Commodity"])
    use_rows = [r for r in use_rows if r not in VALUE_ADDED] + VALUE_ADDED
    use_cols = first_seen(us["Industry"])
    use_cols = [c for c in use_cols if not c.startswith("F")] + [c for c in use_cols if c.startswith("F")]
    use_industries = [c for c in use_cols if not c.startswith("F")]
    use_commodities = [r for r in use_rows if r not in VALUE_ADDED]
    check(len(industries) == 426 and len(make_commodities) == 424, f"make: {len(industries)} industries, {len(make_commodities)} commodities")
    check(len(use_rows) == 431 and len(use_cols) == 439, f"use: {len(use_rows)} rows, {len(use_cols)} columns")
    check(set(VALUE_ADDED) <= set(us["Commodity"]), "use: value-added rows missing")
    check(set(use_industries) == set(industries), f"make/use industries do not match: {set(use_industries) ^ set(industries)}")
    make_only = set(make_commodities) - set(use_commodities)
    check(not make_only, f"make commodities with no use row: {sorted(make_only)}")
    missing = [c for c in use_commodities if c not in make_commodities and c not in SPECIAL_COMMODITIES]
    check(missing == ["S00101"], f"regular use commodities without a make column: {missing}, expected ['S00101']")

    print("detail make:")
    make = wide(mk, "Industry", "Commodity", industries, make_commodities + missing)
    print("detail use:")
    use = wide(us, "Commodity", "Industry", use_rows, use_cols)
    check(not (use.loc[missing] != 0).to_numpy().any(), f"use rows {missing} are not all zero")
    return {"make": make, "use": use}


# --- targets (the 2002 square tables) ---------------------------------------------------


def total_code(c, desc) -> str | None:
    """T008 for the targets' total-output labels (summary: "T007" / "Total Industry Output"
    or blank / "Total industry output"; detailed: blank / "Total" or "Total" / blank)."""
    text = str(desc or "").strip().lower()
    if (c in ("T007", None) and text in ("total industry output", "total")) or (c == "Total" and not text):
        return "T008"
    return None


def read_target(path: Path, sheet: str, header_text: str) -> pd.DataFrame:
    """A target sheet in SquareIOTable.to_frame() layout without the Description column.

    The description row is the row whose column A reads `header_text`; codes are the row
    above it from column C, through the total-output column (-> T008). Rows (code in A,
    description in B) run from the row below it through the total-output row (-> T008).
    """
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Unknown extension is not supported")
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb[sheet]
        ws.reset_dimensions()
        rows = list(ws.iter_rows(values_only=True))
        wb.close()
    width = max(len(r) for r in rows)
    rows = [tuple(r) + (None,) * (width - len(r)) for r in rows]
    desc_row = next(i for i, r in enumerate(rows) if str(r[0] or "").strip() == header_text)
    cols = []
    for j in range(2, width):
        c, d = code(rows[desc_row - 1][j]), rows[desc_row][j]
        t = total_code(c, d)
        cols.append((j, t or c))
        if t:
            break
        check(c is not None, f"{sheet}: column {j + 1} ({d!r}) has no code")
    check(cols[-1][1] == "T008", f"{sheet}: no total-output column")
    index, data = [], []
    for r in rows[desc_row + 1 :]:
        c = code(r[0])
        t = total_code(c, r[1])
        index.append(t or SUMMARY_RECODE.get(c, c))
        data.append([r[j] for j, _ in cols])
        if t:
            break
        check(c is not None, f"{sheet}: row {r[1]!r} has no code")
    check(index[-1] == "T008", f"{sheet}: no total-output row")
    frame = pd.DataFrame(data, index=index, columns=[c for _, c in cols], dtype=object)
    for axis, codes in (("row", frame.index), ("column", frame.columns)):
        check(codes.is_unique, f"{sheet}: duplicate {axis} codes {sorted(codes[codes.duplicated()])}")

    industries = [r for r in index if r not in VALUE_ADDED and r != "T008"]
    final_demand = [c for c in frame.columns if c.startswith("F")]
    check(list(frame.index) == industries + VALUE_ADDED + ["T008"], f"{sheet}: unexpected row order")
    check(list(frame.columns) == industries + final_demand + ["T008"], f"{sheet}: columns are not industries, final demand, T008")
    # Only the value-added and total rows' final-demand and T008 cells may be blank; they
    # are filled by to_frame's rule from the sheet's own cells. Anything else must be a number.
    may_be_blank = pd.DataFrame(False, index=frame.index, columns=frame.columns)
    may_be_blank.loc[VALUE_ADDED + ["T008"], final_demand + ["T008"]] = True
    frame = to_numbers(frame, sheet, may_be_blank.to_numpy())
    blank = frame.isna()
    filled = int(blank.to_numpy().sum())
    for r in VALUE_ADDED:
        frame.loc[r, final_demand] = frame.loc[r, final_demand].fillna(0.0)
        if blank.loc[r, "T008"]:
            frame.loc[r, "T008"] = frame.loc[r, industries].sum()
    for c in final_demand:
        if blank.loc["T008", c]:
            frame.loc["T008", c] = frame.loc[industries, c].sum()
    if blank.loc["T008", "T008"]:
        frame.loc["T008", "T008"] = frame.loc["T008", industries + final_demand].sum()
    print(f"  {sheet}: {len(industries)} industries, {len(final_demand)} final-demand columns, {filled} blank cells filled")
    return frame


# --- output -----------------------------------------------------------------------------


def write(frame: pd.DataFrame, path: Path) -> None:
    if path.suffix == ".gz":
        with gzip.GzipFile(path, "wb", mtime=0) as fh:  # mtime=0: same bytes on every run
            fh.write(frame.to_csv(index_label="code").encode())
    else:
        frame.to_csv(path, index_label="code")
    print(f"  wrote {path.name}: {frame.shape[0]} x {frame.shape[1]}, {path.stat().st_size:,} bytes")


def write_labels(labels: list[tuple[str, str]], path: Path) -> None:
    pd.DataFrame(labels, columns=["code", "description"]).to_csv(path, index=False)
    print(f"  wrote {path.name}: {len(labels)} labels")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    expected = [SUMMARY_MAKEUSE, SUMMARY_TARGET[0], DETAIL_MAKE, DETAIL_USE, DETAIL_TARGET[0]]
    parser.add_argument("--source", type=Path, required=True,
                        help="directory holding the original 2002 workbooks, at the relative file names: "
                             + "; ".join(expected))
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    src, out = args.source, args.out
    out.mkdir(parents=True, exist_ok=True)

    print("summary make and use:")
    summary = summary_make_use(src / SUMMARY_MAKEUSE)
    for kind, (values, labels) in summary.items():
        check([c for c, _ in labels] == list(values.index) + list(values.columns), f"summary {kind}: labels do not match")
        write(values, out / f"summary_{kind}.csv")
        write_labels(labels, out / f"summary_{kind}_labels.csv")
    print("summary target:")
    write(read_target(src / SUMMARY_TARGET[0], SUMMARY_TARGET[1], "Industry Code"), out / "summary_target.csv")

    detail = detail_make_use(src / DETAIL_MAKE, src / DETAIL_USE)
    for kind, values in detail.items():
        write(values, out / f"detail_{kind}.csv.gz")
    print("detail target:")
    write(read_target(src / DETAIL_TARGET[0], DETAIL_TARGET[1], "Industry"), out / "detail_target.csv.gz")


if __name__ == "__main__":
    main()
