"""The accounting identities of a square table.

`check_identities` verifies them (row totals = column totals, market shares
sum to 1, y = row sums) and raises when any residual exceeds the tolerance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from iotables.square import SquareIOTable


def _max_abs(residual: pd.Series) -> float:
    """Largest absolute residual; NaN (labels that failed to align) propagates."""
    return float(residual.abs().max(skipna=False)) if len(residual) else 0.0


def check_identities(sq: SquareIOTable, tol: float = 1e-6) -> dict[str, float | None]:
    """Check a square table's identities; return the residuals ($ millions).

    - "row_minus_col": max |(Z + F row total) - (Z + V column total)| per industry;
      the column total includes the imported inputs of a table with an import split.
    - "shares_minus_one": max |column sum of market_shares - 1| over commodities
      with nonzero output (`meta["commodity_output"]`); None, and not checked,
      when the table has no commodity output or no market shares.
    - "y_minus_rowsum": max |y - (Z + F row total)|.

    Raises ValueError if any checked residual exceeds `tol` or is NaN, or when
    the commodity output and the market shares cover different commodities.
    """
    row_total = sq.Z.sum(axis=1) + sq.F.sum(axis=1)
    col_total = sq.Z.sum(axis=0) + sq.V.sum(axis=0)
    if sq.imported_inputs is not None:  # imported inputs are a cost alongside domestic inputs and value added
        col_total = col_total + sq.imported_inputs.sum(axis=0)
    shares_residual = None
    if "commodity_output" in sq.meta and not sq.market_shares.empty:
        share_sums = sq.market_shares.sum(axis=0)
        q = sq.meta["commodity_output"]
        if set(q.index) != set(share_sums.index):
            raise ValueError(
                "meta['commodity_output'] and market_shares cover different commodities: "
                f"{sorted(set(q.index) ^ set(share_sums.index))}"
            )
        shares_residual = _max_abs(share_sums.loc[q.index[q != 0]] - 1.0)
    residuals = {
        "row_minus_col": _max_abs(row_total - col_total),
        "shares_minus_one": shares_residual,
        "y_minus_rowsum": _max_abs(sq.y - row_total),
    }
    violations = {k: v for k, v in residuals.items() if v is not None and not v <= tol}
    if violations:
        raise ValueError(f"identities violated beyond tol={tol}: {violations}")
    return residuals
