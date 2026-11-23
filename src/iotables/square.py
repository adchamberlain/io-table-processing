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
r = (g - its output of the removed commodities) / g, scrap and DROP_CODES alike,
which keeps industry output at g; "redistribute", the
methodology paper's rule, spreads each column's scrap purchases over the other
commodities in proportion to their purchases, so industry output differs from g.

With BEA's import matrix (`imports=`), the use table is first split into
domestic and imported purchases, U = U_d + U_m and D = D_d + D_m. Z and F are
built from the domestic parts, the imported inputs U_m stay by commodity
(`imported_inputs`), and gross operating surplus balances each column of
domestic inputs, imported inputs and value added. The matrix's imports column
is minus the rest of its row, so industry output is unchanged. Without it,
imports are counted as domestic purchases, offset by the negative imports
column of final demand.

Industries and commodities are different code sets; everything is aligned by
code, never by position.

`SquareIOTable.to_frame` gives the table in one conventional layout (code,
description, industries, final demand, T008 total; rows: industries, V00100,
V00200, V00300, T008), and `to_csv` writes the table's parts as CSV files.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from iotables import validate
from iotables.parse import ImportMatrix, MakeTable, UseTable

SCRAP_CODES = ("S00401", "S00402")  # scrap; used and secondhand goods
DROP_CODES = ("S00300", "S00900")  # noncomparable imports; rest-of-world adjustment
NONCOMPARABLE_IMPORTS = "S00300"  # wholly imported: stays as an imported commodity when imports are split
IMPORTS_ROW = "IMPORTS"  # the row of imported inputs in `SquareIOTable.to_frame`
IMPORTS_LABEL = "Imported inputs"
SCRAP_MODES = ("bea", "redistribute", "keep")
VALUE_ADDED_LABELS = {
    "V00100": "Compensation of employees",
    "V00200": "Taxes on production and imports, less subsidies",
    "V00300": "Gross operating surplus",
}
TOTAL_LABEL = "Total industry output"  # description of the T008 row and column


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

    A table built with BEA's import matrix also has `imported_inputs` (U_m,
    imported commodities x industries), `imported_final` (imports bought
    directly by final users, imported commodities x final-demand columns
    without the imports column) and `pce_import_share` (the imported share of
    personal consumption of each commodity); Z and F are then domestic. They
    are None for a table that combines imports with domestic purchases.
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
    imported_inputs: pd.DataFrame | None = None
    imported_final: pd.DataFrame | None = None
    pce_import_share: pd.Series | None = None

    @property
    def industries(self) -> list[str]:
        return list(self.Z.index)

    @property
    def total_imports(self) -> pd.Series:
        """Imports of each commodity by all buyers ($ millions); empty without an import split."""
        if self.imported_inputs is None:
            return pd.Series(dtype=float)
        total = self.imported_inputs.sum(axis=1)
        if self.imported_final is not None:
            total = total.add(self.imported_final.sum(axis=1), fill_value=0.0)
        return total.loc[self.imported_inputs.index]

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

        Rows: the industries, IMPORTS (only for a table with an import split:
        imported inputs under the industries, final users' imports under final
        demand), V00100, V00200, V00300, T008. Columns: "Description",
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
        parts, extra_labels = [body], {}
        if self.imported_inputs is not None:  # one row: imported inputs by industry, imports of final users
            imports = self.imported_inputs.sum(axis=0).reindex(columns, fill_value=0.0)
            if self.imported_final is not None:
                imports = imports.add(self.imported_final.sum(axis=0).reindex(columns, fill_value=0.0))
            imports["T008"] = imports.sum()
            parts.append(imports.to_frame(IMPORTS_ROW).T)
            extra_labels[IMPORTS_ROW] = IMPORTS_LABEL
        frame = pd.concat([*parts, value_added, totals.to_frame("T008").T])
        labels = pd.concat(
            [
                self.industry_labels.loc[industries],
                pd.Series(extra_labels, dtype=object),
                pd.Series(VALUE_ADDED_LABELS),
                pd.Series({"T008": TOTAL_LABEL}),
            ]
        )
        frame.insert(0, "Description", labels)
        return frame

    def to_csv(self, directory: Path) -> dict[str, Path]:
        """Write the table's parts as CSV files in `directory`; returns {name: path}.

        square.csv (`to_frame()`), Z, F, V, y (column "y"), market_shares, for a
        table with an import split imported_inputs, imported_final and
        pce_import_share, labels
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
        if self.imported_inputs is not None:
            tables["imported_inputs"] = self.imported_inputs
        if self.imported_final is not None:
            tables["imported_final"] = self.imported_final
        if self.pce_import_share is not None:
            tables["pce_import_share"] = self.pce_import_share.to_frame("pce_import_share")
        paths = {name: directory / f"{name}.csv" for name in (*tables, "labels")}
        paths["meta"] = directory / "meta.json"
        for name, table in tables.items():
            table.to_csv(paths[name], index_label="Code")
        labels.rename("description").reset_index().to_csv(paths["labels"], index=False)
        paths["meta"].write_text(json.dumps(_jsonable(self.meta), indent=2) + "\n")
        return paths


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
    imports: ImportMatrix | None = None,
    pce_column: str = "F01000",
    imports_column: str = "F05000",
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

    `imports`, BEA's import matrix for the same tables, splits the use table
    into domestic and imported purchases (module docstring). Its imports column
    (`imports_column`) is set to minus the rest of each row, exactly, so each
    commodity's total and industry output are unchanged by the split. Of the
    `drop` commodities, noncomparable imports (S00300) stay in the imported
    parts as an imported commodity; scrap rows leave them when they leave the
    use table. `pce_column` is the final-demand column whose imported share
    by commodity is recorded for consumer prices.

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
    U_m = D_m = None
    if imports is not None:
        U_m, D_m = _import_parts(imports, U, D, imports_column)

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
        # The ratio also counts an industry's output of the `drop` commodities (the
        # rest-of-world adjustment has a producer), so industry output stays at g.
        nonscrap_ratio = _nonscrap_ratio(make.values, g, (*scrap_codes, *drop))
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

    imported_final = pce_import_share = None
    U_d, D_d = U, D
    if imports is not None:
        gone = [c for c in drop if c != NONCOMPARABLE_IMPORTS]
        if scrap != "keep":
            gone += list(scrap_codes)
        U_m, D_m = U_m.drop(index=gone, errors="ignore"), D_m.drop(index=gone, errors="ignore")
        U_d, D_d = U - U_m.loc[U.index], D - D_m.loc[D.index]
        imported_final = D_m.drop(columns=imports_column)
        if pce_column in D_m.columns:
            pce_imported = D_m[pce_column]
            pce_total = pce_imported + D_d[pce_column].reindex(D_m.index, fill_value=0.0)
            pce_import_share = (pce_imported / pce_total.where(pce_total != 0)).fillna(0.0).clip(0, 1)

    Z = N @ U_d  # pandas aligns N's commodity columns with U's commodity rows by code
    F = N @ D_d
    y = Z.sum(axis=1) + F.sum(axis=1)
    V = va.loc[["V00100", "V00200"]].copy()
    V.loc["V00300"] = y - Z.sum(axis=0) - V.loc["V00100"] - V.loc["V00200"]
    if U_m is not None:
        V.loc["V00300"] -= U_m.sum(axis=0)

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
        # the table's commodities, then any that are only imported (noncomparable imports)
        commodity_labels=use.commodity_labels.loc[
            [*M.columns, *([] if U_m is None else [c for c in U_m.index if c not in M.columns])]
        ],
        meta=meta,
        imported_inputs=U_m,
        imported_final=imported_final,
        pce_import_share=pce_import_share,
    )


def _import_parts(
    imports: ImportMatrix, U: pd.DataFrame, D: pd.DataFrame, imports_column: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The import matrix aligned to the use table's U and D, with its imports column set to minus the rest of each row.

    Raises ValueError when the matrix lacks commodities, industries or
    final-demand columns of the use table, or has no `imports_column`.
    """
    for axis, have, need in (
        ("commodities", imports.intermediate.index, U.index),
        ("industries", imports.intermediate.columns, U.columns),
        ("final-demand columns", imports.final_demand.columns, D.columns),
    ):
        missing = [c for c in need if c not in have]
        if missing:
            raise ValueError(f"the import matrix lacks {axis} of the use table: {missing}")
    if imports_column not in D.columns:
        raise ValueError(f"the use table has no imports column {imports_column!r}")
    U_m = imports.intermediate.loc[U.index, U.columns]
    D_m = imports.final_demand.loc[D.index, D.columns].copy()
    D_m[imports_column] = -(U_m.sum(axis=1) + D_m.drop(columns=imports_column).sum(axis=1))
    return U_m, D_m


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
    """Each industry's nonscrap ratio r = (g - s) / g, the share of its output that stays in the table.

    s is the industry's make-table output of the `scrap_codes` columns present in
    `M` (zero if none is); `build_square_table` passes the scrap and the dropped
    commodities together. Raises ValueError for industries with r not positive:
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
