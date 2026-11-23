"""Make and use tables into a square industry-by-industry table.

Each commodity is taken to be supplied by the industries that make it in fixed
market shares (Eurostat's Model D; BEA's industry-technology assumption). With
BEA's import matrix splitting the use table into domestic and imported
purchases, U = U_d + U_m and D = D_d + D_m:

    N = M diag(q)^-1          market shares, industries x commodities
    Z = N U_d                 intermediate flows, industries x industries
    F = N D_d                 final demand, industries x final-demand columns
    y = row sums of [Z | F]   industry output
    value added: compensation and taxes from the use table; gross operating
    surplus balances each column of domestic inputs, imported inputs and value added.

Four commodities leave the tables first (REMOVED): scrap, used and secondhand
goods, noncomparable imports and the rest-of-world adjustment. Following BEA's
handbook (Concepts and Methods, ch. 12), each industry's market shares are
divided by its nonscrap ratio r = (g - its output of the removed commodities) / g,
which keeps industry output at BEA's g. Noncomparable imports stay among the
imported inputs.

The import matrix's own imports column is minus the rest of its row; here the
imports column of final demand is given what is left after the buyers' imports
are taken out, BEA's reconciliation of duties and freight, so that each
commodity's total, and industry output, are unchanged.

Industries and commodities are different code sets; everything is aligned by
code, never by position.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from iotables import validate
from iotables.parse import ImportMatrix, MakeTable, UseTable

REMOVED = ("S00401", "S00402", "S00300", "S00900")  # scrap; used goods; noncomparable imports; rest-of-world adjustment
NONCOMPARABLE_IMPORTS = "S00300"  # wholly imported: stays among the imported inputs
IMPORTS_ROW = "IMPORTS"  # the row of imported inputs in `SquareIOTable.to_frame`
IMPORTS_LABEL = "Imported inputs"
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
    `market_shares` is M diag(q)^-1. Z and F are purchases from domestic
    industries. `imported_inputs` is U_m (imported commodities x industries),
    `imported_final` the imports bought directly by final users (imported
    commodities x final-demand columns without the imports column) and
    `pce_import_share` the imported share of personal consumption of each
    commodity; they may be None in a table put together by hand. `meta` holds
    year and level (when the make table had them), `source` (both input
    tables' meta), `commodity_output` (q, by commodity) and `diagnostics`.
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
        """Imports of each commodity by all buyers ($ millions); empty without imported inputs."""
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
        """The table in one conventional layout ($ millions), indexed and aligned by code.

        Rows: the industries, IMPORTS (imported inputs under the industries,
        final users' imports under final demand), V00100, V00200, V00300, T008. Columns: "Description",
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

        square.csv (`to_frame()`), Z, F, V, y (column "y"), market_shares,
        imported_inputs, imported_final, pce_import_share, labels
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
    imports: ImportMatrix,
    *,
    removed: Sequence[str] = REMOVED,
    pce_column: str = "F01000",
    imports_column: str = "F05000",
) -> SquareIOTable:
    """Build the square industry-by-industry table (module docstring).

    `imports` is BEA's import matrix for the same tables. `removed` are the
    commodities that leave the tables; codes a table lacks are ignored.
    `pce_column` is the final-demand column whose imported share by commodity
    is kept for consumer prices, and `imports_column` the imports column.

    `meta["diagnostics"]` holds "removed" (the codes that were in the tables),
    "nonscrap_ratio" (by industry), "y_minus_g" (output less BEA's) and
    "gos_minus_bea" (operating surplus less BEA's).

    Raises ValueError for different industry sets in make and use, an import
    matrix that does not cover the use table, imports in a use table with no
    imports column, a make commodity with no use row, a commodity that is
    bought but not made, or an industry with no output left after the removal.
    """
    industries = _check_industries(make, use)
    M = make.values
    U = use.intermediate.loc[:, industries]
    D = use.final_demand
    va = use.value_added.loc[:, industries]
    g = use.industry_output.loc[industries] if use.industry_output is not None else M.sum(axis=1)
    buyers = [c for c in D.columns if c != imports_column]
    U_m, D_m = _import_parts(imports, U, D, buyers)

    present = tuple(c for c in removed if c in M.columns or c in U.index)
    nonscrap_ratio = (g - M[[c for c in removed if c in M.columns]].sum(axis=1)) / g
    empty = [str(i) for i in nonscrap_ratio.index[~(nonscrap_ratio > 0)]]
    if empty:
        raise ValueError(f"industries with no output left once {list(removed)} are removed: {empty}")
    M = M.drop(columns=[c for c in removed if c in M.columns])
    U = U.drop(index=[c for c in removed if c in U.index])
    D = D.drop(index=[c for c in removed if c in D.index])
    not_imports = [c for c in removed if c != NONCOMPARABLE_IMPORTS]
    U_m, D_m = U_m.drop(index=not_imports, errors="ignore"), D_m.drop(index=not_imports, errors="ignore")

    M = _align_commodities(M, U, D)
    q = M.sum(axis=0)
    shares = market_shares(M)
    N = shares.div(nonscrap_ratio, axis=0)

    total_imports = U_m.sum(axis=1) + D_m.sum(axis=1)
    U_d = U - U_m.loc[U.index]
    D_d = D.copy()
    D_d[buyers] = D_d[buyers] - D_m.loc[D.index]
    if imports_column in D_d.columns:
        D_d[imports_column] = D_d[imports_column] + total_imports.loc[D.index]
    elif total_imports.loc[D.index].abs().sum() > 0:
        raise ValueError(f"the import matrix has imports but the use table has no imports column {imports_column!r}")

    Z = N @ U_d  # pandas aligns N's commodity columns with U's commodity rows by code
    F = N @ D_d
    y = Z.sum(axis=1) + F.sum(axis=1)
    V = va.loc[["V00100", "V00200"]].copy()
    V.loc["V00300"] = y - Z.sum(axis=0) - U_m.sum(axis=0) - V.loc["V00100"] - V.loc["V00200"]

    pce_import_share = None
    if pce_column in D_m.columns:
        pce_imported = D_m[pce_column]
        pce_total = pce_imported + D_d[pce_column].reindex(D_m.index, fill_value=0.0)
        pce_import_share = (pce_imported / pce_total.where(pce_total != 0)).fillna(0.0).clip(0, 1)

    meta = {k: make.meta[k] for k in ("year", "level") if k in make.meta}
    meta["source"] = {"make": dict(make.meta), "use": dict(use.meta)}
    meta["commodity_output"] = q
    meta["diagnostics"] = {
        "removed": present,
        "nonscrap_ratio": nonscrap_ratio,
        "y_minus_g": y - g,
        "gos_minus_bea": V.loc["V00300"] - va.loc["V00300"],
    }
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
        commodity_labels=use.commodity_labels.loc[[*M.columns, *[c for c in U_m.index if c not in M.columns]]],
        meta=meta,
        imported_inputs=U_m,
        imported_final=D_m,
        pce_import_share=pce_import_share,
    )


def _import_parts(
    imports: ImportMatrix, U: pd.DataFrame, D: pd.DataFrame, buyers: list[str]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The import matrix aligned to the use table: imported inputs, and final users' imports over `buyers`.

    Raises ValueError when the matrix lacks commodities, industries or
    final-demand columns of the use table.
    """
    for axis, have, need in (
        ("commodities", imports.intermediate.index, U.index),
        ("industries", imports.intermediate.columns, U.columns),
        ("final-demand columns", imports.final_demand.columns, buyers),
    ):
        missing = [c for c in need if c not in have]
        if missing:
            raise ValueError(f"the import matrix lacks {axis} of the use table: {missing}")
    return imports.intermediate.loc[U.index, U.columns], imports.final_demand.loc[D.index, buyers]


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


def _align_commodities(M: pd.DataFrame, U: pd.DataFrame, D: pd.DataFrame) -> pd.DataFrame:
    """The make table with its columns in the use table's commodity order.

    A use commodity absent from the make table gets a zero column. Raises
    ValueError for make commodities with no use row, and for commodities that
    are bought but that no industry makes.
    """
    make_only = [c for c in M.columns if c not in U.index]
    if make_only:
        raise ValueError(f"make-table commodities have no use-table row: {make_only}")
    M = M.reindex(columns=U.index, fill_value=0.0)
    q = M.sum(axis=0)
    bought_not_made = [c for c in q.index[q == 0] if (U.loc[c] != 0).any() or (D.loc[c] != 0).any()]
    if bought_not_made:
        raise ValueError(f"commodities that are bought but that no industry makes: {bought_not_made}")
    return M
