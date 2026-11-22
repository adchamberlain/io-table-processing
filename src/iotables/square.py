"""Stage 3: transform make and use tables into a square industry-by-industry table.

Method (Chamberlain Economics methodology paper, Feb 2011; Eurostat "Model D",
fixed product sales structure; BEA calls it the industry-technology assumption;
design spec section 7):

    N = M * diag(q)^-1        market-share matrix, industries x commodities
    Z = N * U                 intermediate uses, industries x industries
    F = N * D                 final demand, industries x final-demand columns
    y = row sums of [Z | F]   total industry output
    value added: compensation and taxes taken from the use table; gross operating
    surplus is the balancing item so column totals equal y.

Before transforming, noncomparable imports and the rest-of-world adjustment
(DROP_CODES) leave the tables, and the scrap mode decides how scrap and
used/secondhand goods (SCRAP_CODES) are handled: "keep" treats them as ordinary
commodities; "bea", BEA's nonscrap-ratio method (I-O manual ch. 12), removes them
and divides each industry's market shares by its nonscrap ratio
r = (g - scrap output) / g, which keeps industry output at g; "redistribute", the
methodology paper's rule, spreads each column's scrap purchases over the other
commodities in proportion to their purchases, so industry output differs from g.

Industries and commodities are different code sets; everything is aligned by
code, never by position.

`SquareIOTable.to_frame` gives the table in the layout of the legacy 2002
spreadsheets (code, description, industries, final demand, T008 total; rows:
industries, V00100, V00200, V00300, T008); `to_excel`, `read_square_frame` and
`to_csv` write and read it, and `SquareIOTable.from_frame` splits it back into a
table.
"""

import datetime
import json
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd

import iotables
from iotables import validate
from iotables.parse import MakeTable, UseTable, normalize_code

SCRAP_CODES = ("S00401", "S00402")  # scrap; used and secondhand goods
DROP_CODES = ("S00300", "S00900")  # noncomparable imports; rest-of-world adjustment
SCRAP_MODES = ("bea", "redistribute", "keep")
VALUE_ADDED_LABELS = {
    "V00100": "Compensation of employees",
    "V00200": "Taxes on production and imports, less subsidies",
    "V00300": "Gross operating surplus",
}
TOTAL_LABEL = "Total industry output"  # description of the T008 row and column
SHEET = "square"  # the sheet `to_excel` writes and `read_square_frame` reads
_FIRST_VALUE_COL = 3  # column C: Excel columns A and B hold the code and the description


@dataclass
class SquareIOTable:
    """A square industry-by-industry input-output table ($ millions).

    `Z` is industries x industries (seller rows, buyer columns), `F` industries
    x final-demand columns, `V` the value-added rows V00100, V00200, V00300 x
    industries, `y` total industry output (row totals of [Z | F]). `N` is the
    industries x commodities matrix that turned the use table into Z and F;
    `market_shares` is M diag(q)^-1. `meta` holds year, level and
    redefinitions (when the make table had them), `source` (both input tables'
    meta), `commodity_output` (q, by commodity) and `diagnostics`.
    """

    Z: pd.DataFrame
    F: pd.DataFrame
    V: pd.DataFrame
    y: pd.Series
    N: pd.DataFrame
    market_shares: pd.DataFrame
    industry_labels: pd.Series
    final_demand_labels: pd.Series
    commodity_labels: pd.Series
    meta: dict

    @property
    def industries(self) -> list[str]:
        return list(self.Z.index)

    @property
    def n(self) -> int:
        return len(self.Z.index)

    def check_identities(self, tol: float = 1e-6) -> dict[str, float | None]:
        """Residuals of the table's identities; raises ValueError beyond `tol`.

        See `validate.check_identities`.
        """
        return validate.check_identities(self, tol)

    def to_frame(self) -> pd.DataFrame:
        """The table in the legacy layout ($ millions), indexed and aligned by code.

        Rows: the industries, V00100, V00200, V00300, T008. Columns: "Description",
        the industries, the final-demand codes, T008. Industry rows carry Z | F | y;
        value-added rows carry V under the industries, 0.0 under final demand and
        their row sum under T008; the T008 row carries y under the industries, the
        column sums of F under final demand and their total with y (the sum of the
        row) under T008.
        """
        industries, final_demand = self.industries, list(self.F.columns)
        columns = industries + final_demand + ["T008"]
        body = pd.concat([self.Z, self.F], axis=1)
        body["T008"] = self.y
        value_added = self.V.loc[:, industries].reindex(columns=columns, fill_value=0.0)
        value_added["T008"] = value_added[industries].sum(axis=1)
        totals = pd.concat([self.y.loc[industries], self.F.sum(axis=0)])
        totals["T008"] = totals.sum()
        frame = pd.concat([body, value_added, totals.to_frame("T008").T])
        labels = pd.concat(
            [
                self.industry_labels.loc[industries],
                pd.Series(VALUE_ADDED_LABELS),
                pd.Series({"T008": TOTAL_LABEL}),
            ]
        )
        frame.insert(0, "Description", labels)
        return frame

    @classmethod
    def from_frame(
        cls, frame: pd.DataFrame, meta: dict | None = None, csv_dir: Path | None = None
    ) -> "SquareIOTable":
        """The table in a `to_frame()` layout (as `read_square_frame` returns it), split back into its parts.

        Z, F, V and y come from the frame, the industry labels from its Description
        column. The layout holds no market shares, commodity output or column
        descriptions; `csv_dir`, a folder `to_csv` wrote for the same table,
        supplies them: market_shares.csv, the final-demand and commodity labels
        from labels.csv, and meta.json, whose entries `meta` (copied) then
        updates, with commodity_output as a Series. N is the market shares divided
        by the industries' nonscrap ratios when meta's diagnostics record them
        (scrap mode "bea"), else the market shares, as in `build_square_table`.

        Without `csv_dir`, market_shares and N are empty (no columns),
        commodity_labels is empty, each final-demand code is its own label and
        meta (a copy of `meta`, default empty) has no commodity_output. Such a
        table gives industry prices and final-demand burdens; commodity and PCE
        prices and commodity taxes need what it lacks, and `check_identities`
        checks its balance but not its market shares.

        Raises ValueError when the rows are not the industries then V00100,
        V00200, V00300, T008, the columns not Description, the same industries
        in the same order, the final-demand codes, T008, or the CSV folder's
        market shares, labels or commodity output do not cover the frame's
        industries, final demand and the market shares' commodities.
        """
        tail = [*VALUE_ADDED_LABELS, "T008"]
        if list(frame.index[-len(tail):]) != tail or len(frame.index) == len(tail):
            raise ValueError(f"the rows must be the industries, then {', '.join(tail)}; got {list(frame.index)}")
        industries = list(frame.index[: -len(tail)])
        n = len(industries)
        columns = list(frame.columns)
        if columns[:1] != ["Description"] or columns[-1:] != ["T008"] or columns[1 : n + 1] != industries:
            raise ValueError(
                "the columns must be Description, the industries in row order, the final-demand codes and T008; "
                f"got {columns}"
            )
        final_demand = columns[n + 1 : -1]
        values = frame.drop(columns="Description").astype(float)
        y = values.loc[industries, "T008"].rename(None)
        meta = dict(meta or {})
        if csv_dir is None:
            shares = pd.DataFrame(index=pd.Index(industries), dtype=float)
            N = shares.copy()
            final_demand_labels = pd.Series(final_demand, index=final_demand, dtype=object)
            commodity_labels = pd.Series(dtype=object)
        else:
            shares, labels, stored = _read_csv_parts(Path(csv_dir), industries, final_demand)
            final_demand_labels, commodity_labels = labels["final_demand"], labels["commodity"]
            meta = {**stored, **meta}
            ratio = meta.get("diagnostics", {}).get("nonscrap_ratio")
            N = shares.copy() if ratio is None else shares.div(pd.Series(ratio, dtype=float).loc[industries], axis=0)
        return cls(
            Z=values.loc[industries, industries],
            F=values.loc[industries, final_demand],
            V=values.loc[list(VALUE_ADDED_LABELS), industries],
            y=y,
            N=N,
            market_shares=shares,
            industry_labels=frame.loc[industries, "Description"].rename(None),
            final_demand_labels=final_demand_labels,
            commodity_labels=commodity_labels,
            meta=meta,
        )

    def to_excel(self, path: Path, title: str | None = None) -> Path:
        """Write `to_frame()` to sheet "square" of an xlsx file; returns the path.

        A1 title (default "<year> <level>-level U.S. Input-Output Table" from
        `meta`, else "U.S. Input-Output Table"), A2 "<n> industries", A3 "($
        Millions)"; row 5 the codes (A5 "Code"), row 6 the column descriptions (A6
        "Industry", B6 "Description"); data from row 7 with each row's code and
        description in columns A and B; then a blank row and the source line.
        `read_square_frame` reads the file back.
        """
        path = Path(path)
        if title is None:
            if "year" in self.meta and "level" in self.meta:
                title = f"{self.meta['year']} {self.meta['level']}-level U.S. Input-Output Table"
            else:
                title = "U.S. Input-Output Table"
        frame = self.to_frame()
        codes = list(frame.columns[1:])
        descriptions = pd.concat(
            [
                self.industry_labels.loc[self.industries],
                self.final_demand_labels.loc[list(self.F.columns)],
                pd.Series({"T008": TOTAL_LABEL}),
            ]
        )
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = SHEET
        ws["A1"], ws["A2"], ws["A3"] = title, f"{self.n} industries", "($ Millions)"
        ws["A5"], ws["A6"], ws["B6"] = "Code", "Industry", "Description"
        for j, code in enumerate(codes):
            ws.cell(5, _FIRST_VALUE_COL + j, code)
            ws.cell(6, _FIRST_VALUE_COL + j, descriptions.loc[code])
        for i, (code, row) in enumerate(frame.iterrows()):
            ws.cell(7 + i, 1, code)
            ws.cell(7 + i, 2, row["Description"])
            for j, value in enumerate(row.iloc[1:]):
                ws.cell(7 + i, _FIRST_VALUE_COL + j, float(value))
        today = datetime.date.today().isoformat()
        ws.cell(
            7 + len(frame) + 1,
            1,
            f"Source: Bureau of Economic Analysis; built with iotables {iotables.__version__} on {today}",
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        wb.save(path)
        return path

    def to_csv(self, directory: Path) -> dict[str, Path]:
        """Write the table's parts as CSV files in `directory`; returns {name: path}.

        square.csv (`to_frame()`), Z, F, V, y (column "y"), market_shares, labels
        (columns kind, code, description for industries, final demand and
        commodities) and meta.json (`meta` with Series and DataFrames as dicts and
        anything else JSON cannot hold as strings).
        """
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        labels = pd.concat(
            {
                "industry": self.industry_labels,
                "final_demand": self.final_demand_labels,
                "commodity": self.commodity_labels,
            },
            names=["kind", "code"],
        )
        tables = {
            "square": self.to_frame(),
            "Z": self.Z,
            "F": self.F,
            "V": self.V,
            "y": self.y.to_frame("y"),
            "market_shares": self.market_shares,
        }
        paths = {name: directory / f"{name}.csv" for name in (*tables, "labels")}
        paths["meta"] = directory / "meta.json"
        for name, table in tables.items():
            table.to_csv(paths[name], index_label="Code")
        labels.rename("description").reset_index().to_csv(paths["labels"], index=False)
        paths["meta"].write_text(json.dumps(_jsonable(self.meta), indent=2) + "\n")
        return paths


def read_square_frame(path: Path) -> pd.DataFrame:
    """Read a `SquareIOTable.to_excel` file back into the `to_frame()` layout.

    The "Code" row is the first row whose column A, stripped and lower-cased, is
    "code", wherever it sits: its codes run from column C to the first empty
    cell, the description row follows it, and data rows (code in column A,
    description in column B, then the values) run from there to the first row
    with columns A and B both empty. Raises ValueError for a missing sheet "square",
    a missing "Code" row, no columns or no data rows, a data row without a code,
    duplicate codes along either axis, and a blank or non-numeric data cell (the
    message names its row and column codes).
    """
    with closing(openpyxl.load_workbook(Path(path), read_only=True, data_only=True)) as wb:
        if SHEET not in wb.sheetnames:
            raise ValueError(f"no sheet {SHEET!r}; found {wb.sheetnames}")
        ws = wb[SHEET]
        ws.reset_dimensions()
        rows = list(ws.iter_rows(values_only=True))
    width = max((len(r) for r in rows), default=0) + 2
    rows = [tuple(r) + (None,) * (width - len(r)) for r in rows]  # every row has the same width
    code_idx = next(
        (i for i, r in enumerate(rows) if str(r[0] or "").strip().lower() == "code"), None
    )
    if code_idx is None:
        raise ValueError(f"sheet {SHEET!r}: no row with 'Code' in column A")
    first = _FIRST_VALUE_COL - 1  # zero-based
    columns = []
    for cell in rows[code_idx][first:]:
        code = normalize_code(cell)
        if code is None:
            break
        columns.append(code)
    index, descriptions, data = [], [], []
    for r in rows[code_idx + 2 :]:
        code, description = normalize_code(r[0]), r[1]
        if code is None and description is None:
            break
        if code is None:
            raise ValueError(f"sheet {SHEET!r}: data row {description!r} has no code")
        index.append(code)
        descriptions.append(description)
        data.append(r[first : first + len(columns)])
    if not columns or not index:
        raise ValueError(f"sheet {SHEET!r}: the table has {len(index)} data rows and {len(columns)} columns")
    for axis, codes in (("column", columns), ("row", index)):
        dupes = sorted({c for c in codes if codes.count(c) > 1})
        if dupes:
            raise ValueError(f"sheet {SHEET!r}: duplicate {axis} codes {dupes}")
    values = pd.DataFrame(data, index=index, columns=columns, dtype=object)
    numeric = values.apply(pd.to_numeric, errors="coerce")
    bad = np.argwhere(numeric.isna().to_numpy())
    if len(bad):
        i, j = bad[0]  # the first bad cell in row-major order
        cell = values.iat[i, j]
        problem = "blank" if cell is None else f"not a number: {cell!r}"
        raise ValueError(
            f"sheet {SHEET!r}: row {index[i]!r}, column {columns[j]!r} is {problem}"
            f" ({len(bad)} bad cells in all)"
        )
    frame = numeric.astype(float)
    frame.insert(0, "Description", pd.Series(descriptions, index=index, dtype=object))
    return frame


def _read_csv_parts(
    directory: Path, industries: list[str], final_demand: list[str]
) -> tuple[pd.DataFrame, dict[str, pd.Series], dict]:
    """A `to_csv` folder's market shares (rows in `industries` order), its final-demand and
    commodity labels ({"final_demand": ..., "commodity": ...}) and its meta.json, with
    commodity_output as a Series in market-share column order; ValueError when they do
    not cover the given codes and the market shares' commodities."""
    path = directory / "market_shares.csv"
    shares = pd.read_csv(path, dtype={"Code": str}).set_index("Code").rename_axis(None).astype(float)
    only_csv, only_table = sorted(set(shares.index) - set(industries)), sorted(set(industries) - set(shares.index))
    if only_csv or only_table or len(shares.index) != len(industries):
        raise ValueError(
            f"{path}: its industries are not the table's: only in the CSV {only_csv}, only in the table {only_table}"
        )
    shares = shares.loc[industries]
    commodities = list(shares.columns)
    table = pd.read_csv(directory / "labels.csv", dtype=str, keep_default_na=False)
    labels = {}
    for kind, codes in (("final_demand", final_demand), ("commodity", commodities)):
        descriptions = table.loc[table["kind"] == kind].set_index("code")["description"]
        missing = [c for c in codes if c not in descriptions.index]
        if missing:
            raise ValueError(f"{directory / 'labels.csv'}: no {kind} labels for {missing}")
        labels[kind] = descriptions.loc[codes].rename(None).rename_axis(None)
    path = directory / "meta.json"
    stored = json.loads(path.read_text())
    q = pd.Series(stored.get("commodity_output", {}), dtype=float)
    if set(q.index) != set(commodities):
        raise ValueError(
            f"{path}: commodity_output does not cover the market shares' commodities: "
            f"{sorted(set(q.index) ^ set(commodities))}"
        )
    stored["commodity_output"] = q.loc[commodities]
    return shares, labels, stored


def _jsonable(obj):
    """`obj` with Series and DataFrames as dicts, numpy scalars as Python ones and the rest as strings."""
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (pd.Series, pd.DataFrame)):
        return _jsonable(obj.to_dict())
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, np.generic):
        return obj.item()
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    return str(obj)


def market_shares(make_values: pd.DataFrame) -> pd.DataFrame:
    """M diag(q)^-1: each industry's share of each commodity's output.

    q is the make table's column totals. Columns with zero total are all zero.
    """
    q = make_values.sum(axis=0)
    shares = make_values.div(q.where(q != 0, 1.0), axis=1)
    shares.loc[:, q == 0] = 0.0
    return shares


def build_square_table(
    make: MakeTable,
    use: UseTable,
    *,
    scrap: str = "bea",
    drop: Sequence[str] = DROP_CODES,
    scrap_codes: Sequence[str] = SCRAP_CODES,
) -> SquareIOTable:
    """Build the square industry-by-industry table (design spec section 7).

    Steps: check that make and use have the same industries (order from the
    make table); remove the `drop` commodities from the use rows and make
    columns, recording the amounts; apply the scrap mode; check the commodity
    sets; then N from the market shares, Z = N U, F = N D, y = row totals of
    [Z | F], and V00300 balances each column. Codes in `drop` or `scrap_codes`
    that a table lacks are ignored.

    `meta["diagnostics"]` records "scrap_mode", "drop_codes" and "scrap_codes":
    the codes of `drop` and of `scrap_codes` that were removed (those in the
    use rows or make columns, in the order given; "scrap_codes" is () in mode
    "keep"). Scrap mode "bea" records the nonscrap ratio (a Series by industry)
    and the scrap purchases it drops, {code: {"intermediate": $, "final_demand": $}}, in
    `meta["diagnostics"]` as "nonscrap_ratio" and "scrap_purchases_dropped".
    Mode "redistribute" (see `redistribute_rows`) records "redistributed":
    {"intermediate": $ moved in U, "final_demand": $ moved in D, "unallocated":
    {column: $}}, the scrap value of columns with no other purchases to receive it
    (industry and final-demand column codes are distinct, so one dict serves both).

    Industry output g (for diagnostics) is the use table's T008 row, or the
    make table's row totals when the use table has none.

    Raises ValueError for an unknown scrap mode, different industry sets, a
    make commodity with no use row, a commodity with zero make output (no
    make column, or an all-zero one) but nonzero use, or, in mode "bea", an
    industry with no nonscrap output (nonscrap ratio not positive).
    """
    if scrap not in SCRAP_MODES:
        raise ValueError(f"scrap must be one of {SCRAP_MODES}, got {scrap!r}")
    industries = _check_industries(make, use)
    M = make.values
    U = use.intermediate.loc[:, industries]
    D = use.final_demand
    va = use.value_added.loc[:, industries]
    g = use.industry_output.loc[industries] if use.industry_output is not None else M.sum(axis=1)
    diagnostics: dict = {"scrap_mode": scrap}

    diagnostics["drop_codes"] = _present(drop, M, U)
    M, U, D, diagnostics["dropped"], diagnostics["dropped_make_output"] = _remove_commodities(
        M, U, D, drop
    )

    # Scrap mode (spec 7.3), step 1: which scrap and used-goods rows and columns
    # leave the tables. "keep" treats them as ordinary commodities.
    diagnostics["scrap_codes"] = () if scrap == "keep" else _present(scrap_codes, M, U)
    nonscrap_ratio = None
    if scrap == "redistribute":
        present = [c for c in scrap_codes if c in U.index]
        scrap_in_U, scrap_in_D = U.loc[present].to_numpy().sum(), D.loc[present].to_numpy().sum()
        U, unallocated_U = redistribute_rows(U, present)
        D, unallocated_D = redistribute_rows(D, present)
        M = M.drop(columns=[c for c in scrap_codes if c in M.columns])
        diagnostics["redistributed"] = {
            "intermediate": float(scrap_in_U) - sum(unallocated_U.values()),
            "final_demand": float(scrap_in_D) - sum(unallocated_D.values()),
            "unallocated": {**unallocated_U, **unallocated_D},
        }
    if scrap == "bea":
        nonscrap_ratio = _nonscrap_ratio(M, g, scrap_codes)
        M, U, D, diagnostics["scrap_purchases_dropped"], _ = _remove_commodities(
            M, U, D, scrap_codes
        )
        diagnostics["nonscrap_ratio"] = nonscrap_ratio

    M = _align_commodities(M, U, D)
    q = M.sum(axis=0)
    shares = market_shares(M)
    # Scrap mode, step 2: N from the market shares. "keep" and "redistribute" use
    # (a copy of) them as they are; "bea" scales each industry's row up by 1 / its nonscrap ratio.
    N = shares.copy() if nonscrap_ratio is None else shares.div(nonscrap_ratio, axis=0)

    Z = N @ U  # pandas aligns N's commodity columns with U's commodity rows by code
    F = N @ D
    y = Z.sum(axis=1) + F.sum(axis=1)
    V = va.loc[["V00100", "V00200"]].copy()
    V.loc["V00300"] = y - Z.sum(axis=0) - V.loc["V00100"] - V.loc["V00200"]

    diagnostics["y_minus_g"] = y - g
    diagnostics["gos_minus_bea"] = V.loc["V00300"] - va.loc["V00300"]
    meta = {k: make.meta[k] for k in ("year", "level", "redefinitions") if k in make.meta}
    meta["source"] = {"make": dict(make.meta), "use": dict(use.meta)}
    meta["commodity_output"] = q
    meta["diagnostics"] = diagnostics
    return SquareIOTable(
        Z=Z,
        F=F,
        V=V,
        y=y,
        N=N,
        market_shares=shares,
        industry_labels=make.industry_labels.loc[industries],
        final_demand_labels=use.final_demand_labels.loc[D.columns],
        commodity_labels=use.commodity_labels.loc[M.columns],
        meta=meta,
    )


def redistribute_rows(
    block: pd.DataFrame, rows: Sequence[str]
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Spread the `rows` over the other rows in proportion to their values, column by column.

    In each column the `rows` total s is added to the other rows in proportion to
    their values, so column totals are unchanged, and the `rows` are dropped. A
    column whose other rows sum to zero cannot receive s: it keeps its other rows
    as they are and s is returned in the second value, {column: s}. Proportions
    are the other rows' values over their sum, with no special treatment of
    negative values. Raises KeyError for a row not in `block`.
    """
    rows = list(rows)
    scrap = block.loc[rows].sum(axis=0)
    others = block.drop(index=rows)
    total = others.sum(axis=0)
    receives = total != 0
    scale = scrap.where(receives, 0.0) / total.where(receives, 1.0)
    unallocated = {str(c): float(scrap[c]) for c in total.index[~receives]}
    return others + others * scale, unallocated


def _check_industries(make: MakeTable, use: UseTable) -> list[str]:
    """The make table's industries in its order, once the use table is shown to match."""
    only_make = sorted(set(make.industries) - set(use.industries))
    only_use = sorted(set(use.industries) - set(make.industries))
    if only_make or only_use:
        raise ValueError(
            "make and use tables have different industries: "
            f"only in make {only_make}, only in use {only_use}"
        )
    return make.industries


def _remove_commodities(
    M: pd.DataFrame, U: pd.DataFrame, D: pd.DataFrame, codes: Sequence[str]
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict, dict]:
    """Remove `codes` from the make columns and the use rows; absent codes are ignored.

    Returns the reduced M, U and D, the removed use amounts
    {code: {"intermediate": $, "final_demand": $}} and the removed make output
    {code: $}.
    """
    in_use = [c for c in codes if c in U.index]
    in_make = [c for c in codes if c in M.columns]
    use_amounts = {
        c: {"intermediate": float(U.loc[c].sum()), "final_demand": float(D.loc[c].sum())}
        for c in in_use
    }
    make_output = {c: float(M[c].sum()) for c in in_make}
    return (
        M.drop(columns=in_make),
        U.drop(index=in_use),
        D.drop(index=in_use),
        use_amounts,
        make_output,
    )


def _present(codes: Sequence[str], M: pd.DataFrame, U: pd.DataFrame) -> tuple[str, ...]:
    """The `codes` that are make columns or use rows, in the order given."""
    return tuple(c for c in codes if c in M.columns or c in U.index)


def _nonscrap_ratio(M: pd.DataFrame, g: pd.Series, scrap_codes: Sequence[str]) -> pd.Series:
    """Each industry's nonscrap ratio r = (g - s) / g, the share of its output that is not scrap.

    s is the industry's make-table output of the `scrap_codes` columns present in
    `M` (zero if none is). Raises ValueError for industries with r not positive:
    zero output, or output that is all scrap, which no scaling can restore.
    """
    scrap_output = M[[c for c in scrap_codes if c in M.columns]].sum(axis=1)
    ratio = (g - scrap_output) / g
    bad = [str(i) for i in ratio.index[~(ratio > 0)]]
    if bad:
        raise ValueError(f"industries with no nonscrap output (nonscrap ratio not positive): {bad}")
    return ratio


def _align_commodities(M: pd.DataFrame, U: pd.DataFrame, D: pd.DataFrame) -> pd.DataFrame:
    """The make table with its columns in the use table's commodity order.

    A use commodity absent from the make table gets a zero column. Raises
    ValueError for make commodities with no use row, and for commodities with
    zero make output but nonzero use (spec 7.4: their purchases would vanish).
    """
    make_only = [c for c in M.columns if c not in U.index]
    if make_only:
        raise ValueError(f"make-table commodities have no use-table row: {make_only}")
    M = M.reindex(columns=U.index, fill_value=0.0)
    q = M.sum(axis=0)
    used_without_output = [
        c for c in q.index[q == 0] if (U.loc[c] != 0).any() or (D.loc[c] != 0).any()
    ]
    if used_without_output:
        raise ValueError(
            "commodities with zero make output (no make column, or an all-zero one) "
            f"have nonzero use: {used_without_output}; scrap/used codes with no producer "
            "are removed under scrap='bea' or 'redistribute'"
        )
    return M
