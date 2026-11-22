"""Identity checks and table comparison, used by tests and the CLI's checks.

`check_identities` verifies the accounting identities of a square table
(row totals = column totals, market shares sum to 1, y = row sums) and raises
when any residual exceeds the tolerance. `compare_tables` lists the cells
where two code-labeled tables disagree. `ixi_total_requirements` gives the
industry-by-industry total requirements (I - A)^-1 that BEA publishes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from iotables.square import SquareIOTable


def _max_abs(residual: pd.Series) -> float:
    """Largest absolute residual; NaN (labels that failed to align) propagates."""
    return float(residual.abs().max(skipna=False)) if len(residual) else 0.0


def check_identities(sq: SquareIOTable, tol: float = 1e-6) -> dict[str, float]:
    """Check a square table's identities; return the residuals ($ millions).

    - "row_minus_col": max |(Z + F row total) - (Z + V column total)| per industry.
    - "shares_minus_one": max |column sum of market_shares - 1| over commodities
      with nonzero output (`meta["commodity_output"]`).
    - "y_minus_rowsum": max |y - (Z + F row total)|.

    Raises ValueError if any residual exceeds `tol` or is NaN.
    """
    row_total = sq.Z.sum(axis=1) + sq.F.sum(axis=1)
    col_total = sq.Z.sum(axis=0) + sq.V.sum(axis=0)
    share_sums = sq.market_shares.sum(axis=0)
    q = sq.meta["commodity_output"]
    if set(q.index) != set(share_sums.index):
        raise ValueError(
            "meta['commodity_output'] and market_shares cover different commodities: "
            f"{sorted(set(q.index) ^ set(share_sums.index))}"
        )
    residuals = {
        "row_minus_col": _max_abs(row_total - col_total),
        "shares_minus_one": _max_abs(share_sums.loc[q.index[q != 0]] - 1.0),
        "y_minus_rowsum": _max_abs(sq.y - row_total),
    }
    violations = {k: v for k, v in residuals.items() if not v <= tol}
    if violations:
        raise ValueError(f"identities violated beyond tol={tol}: {violations}")
    return residuals


def compare_tables(
    a: pd.DataFrame, b: pd.DataFrame, rtol: float = 1e-6, atol: float = 1e-6
) -> pd.DataFrame:
    """Cells where `a` and `b` differ beyond tolerance, aligned by label.

    `b` is the reference: a cell is a violation unless
    |a - b| <= atol + rtol * |b| (NaN never matches). Both tables must carry
    the same row and column labels (any order); otherwise ValueError.
    Returns a long DataFrame with columns row, col, a, b, diff (= a - b),
    empty when the tables agree.
    """
    for axis, left, right in (("row", a.index, b.index), ("column", a.columns, b.columns)):
        only_a, only_b = left.difference(right), right.difference(left)
        if len(only_a) or len(only_b):
            raise ValueError(
                f"{axis} labels differ: only in a {list(only_a)}, only in b {list(only_b)}"
            )
    av = a.to_numpy(dtype=float)
    bv = b.loc[a.index, a.columns].to_numpy(dtype=float)
    rows, cols = np.nonzero(~np.isclose(av, bv, rtol=rtol, atol=atol))
    return pd.DataFrame(
        {
            "row": a.index[rows],
            "col": a.columns[cols],
            "a": av[rows, cols],
            "b": bv[rows, cols],
            "diff": av[rows, cols] - bv[rows, cols],
        }
    )


def ixi_total_requirements(sq: SquareIOTable) -> pd.DataFrame:
    """Industry-by-industry total requirements (I - A)^-1, A = Z diag(y)^-1.

    A_ij = Z_ij / y_j is industry i's sales to industry j per dollar of j's
    output; cell (i, j) of the result is the output of industry i needed per
    dollar of final demand for industry j's output, the layout of BEA's IxI
    total requirements table. Rows and columns carry the industry codes in
    `sq.Z`'s row order; Z's columns and y are aligned to them by code.

    Raises ValueError when Z's row and column codes differ or an industry has
    zero output; numpy.linalg.LinAlgError (a ValueError) when I - A is singular.
    """
    industries = sq.Z.index
    if set(sq.Z.columns) != set(industries) or len(sq.Z.columns) != len(industries):
        raise ValueError(
            "Z must have the same industry codes on both axes: "
            f"only in rows {sorted(set(industries) - set(sq.Z.columns))}, "
            f"only in columns {sorted(set(sq.Z.columns) - set(industries))}"
        )
    y = sq.y.reindex(industries)
    no_output = [str(c) for c in industries[~(y.abs() > 0)]]
    if no_output:
        raise ValueError(f"industries with zero or missing output y: {no_output}")
    A = sq.Z.loc[industries, industries].to_numpy(dtype=float) / y.to_numpy(dtype=float)
    L = np.linalg.inv(np.eye(len(industries)) - A)
    return pd.DataFrame(L, index=industries.copy(), columns=industries.copy())
