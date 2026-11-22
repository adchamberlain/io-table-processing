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
"""

from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd

from iotables import validate
from iotables.parse import MakeTable, UseTable

SCRAP_CODES = ("S00401", "S00402")  # scrap; used and secondhand goods
DROP_CODES = ("S00300", "S00900")  # noncomparable imports; rest-of-world adjustment
SCRAP_MODES = ("bea", "redistribute", "keep")


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

    def check_identities(self, tol: float = 1e-6) -> dict[str, float]:
        """Residuals of the table's identities; raises ValueError beyond `tol`.

        See `validate.check_identities`.
        """
        return validate.check_identities(self, tol)


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

    Scrap mode "bea" records the nonscrap ratio (a Series by industry) and the
    scrap purchases it drops, {code: {"intermediate": $, "final_demand": $}}, in
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

    M, U, D, diagnostics["dropped"], diagnostics["dropped_make_output"] = _remove_commodities(
        M, U, D, drop
    )

    # Scrap mode (spec 7.3), step 1: which scrap and used-goods rows and columns
    # leave the tables. "keep" treats them as ordinary commodities.
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
    # them as they are; "bea" scales each industry's row up by 1 / its nonscrap ratio.
    N = shares if nonscrap_ratio is None else shares.div(nonscrap_ratio, axis=0)

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
            f"have nonzero use: {used_without_output}"
        )
    return M
