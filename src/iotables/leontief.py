"""Stage 4: the Leontief price model on the square table (design spec section 8).

Baseline (spec 8.1):

    A = Z diag(y)^-1               technical coefficients (input i per $ of output j)
    v = (y - Z.sum(axis=0)) / y    value added per $ of output
    p = (I - A')^-1 v              a vector of ones (checked to 1e-9)

Shocks (`shocks.py`) become output taxes tau (per $ of output) and flow-tax
rates T (seller x buyer). Two formulations:

    "output_tax" (default, spec 8.3)
        A_hat = A * (1 + T) elementwise;  p_hat = (I - A_hat')^-1 (v + tau)
        The price increase on final demand equals the tax collected, with flow
        taxes valued at the sellers' new prices.
    "wp6" (spec 8.4), only to reproduce the 2009 Tax Foundation WP6 results
        t_i = dollars_i / industry i's intermediate sales (an IndustryTax given
        as a rate is t_i itself);  A_hat = diag(1 + t) A;  p_hat = (I - A_hat')^-1 v
        No flow taxes, and no burden identity.

Every system is solved with numpy.linalg.solve; no inverse is formed. Price
changes are fractions (0.125 = 12.5 percent); dollars are millions.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from iotables.shocks import FlowTax, IndustryTax, Shock, industry_dollars, to_tau_T
from iotables.square import SquareIOTable

FORMULATIONS = ("output_tax", "wp6")
BASELINE_TOL = 1e-9  # largest allowed |p - 1| in the base year


@dataclass
class PriceResult:
    """The outcome of `PriceModel.run` ($ millions; price changes as fractions).

    `industry_prices`: columns code, description, pct_change, one row per
    industry in table order. `burden_by_final_demand`: columns code,
    description, base_spending (the column's total), burden (dp' F, the added
    cost of the column's purchases). `summary`: formulation, total_tax,
    final_demand_burden (the burdens' sum), identity_residual
    (final_demand_burden - total_tax) and pce_burden. `commodity_prices`,
    `pce_prices` and `summary["pce_burden"]` are None: not computed yet.
    `shocks` is the list that was run; `notes` holds messages about the run.
    """

    industry_prices: pd.DataFrame
    commodity_prices: pd.DataFrame | None
    pce_prices: pd.DataFrame | None
    burden_by_final_demand: pd.DataFrame
    summary: dict
    shocks: list
    notes: list[str]


class PriceModel:
    """The price model on `sq` in one `formulation` ("output_tax" or "wp6").

    `pce_bridge` and `margin_codes` are stored for the consumer-price stage and
    not used yet. Raises ValueError for an unknown formulation, an industry with
    zero output (its coefficients are undefined) or baseline prices more than
    1e-9 from 1.
    """

    def __init__(
        self,
        sq: SquareIOTable,
        pce_bridge: object | None = None,
        formulation: str = "output_tax",
        margin_codes: dict[str, list[str]] | None = None,
    ):
        if formulation not in FORMULATIONS:
            raise ValueError(f"formulation must be one of {FORMULATIONS}, got {formulation!r}")
        self.sq = sq
        self.pce_bridge = pce_bridge
        self.formulation = formulation
        self.margin_codes = margin_codes
        industries = sq.industries
        y = sq.y.loc[industries]
        if (y == 0).any():
            raise ValueError(f"industries with zero output: {list(y.index[y == 0])}")
        Z = sq.Z.loc[industries, industries]
        self.A = Z.div(y, axis=1)
        self.v = (y - Z.sum(axis=0)) / y
        deviation = (self.baseline_prices() - 1).abs()
        if not (deviation <= BASELINE_TOL).all():  # written so that NaN fails too
            raise ValueError(f"baseline prices are not 1 within {BASELINE_TOL}: max |p - 1| = "
                             f"{deviation.max()} (industry {deviation.idxmax()!r})")

    def baseline_prices(self) -> pd.Series:
        """p = (I - A')^-1 v, by industry: ones for a balanced table."""
        return self._solve(self.A, self.v)

    def run(self, shocks: Sequence[Shock]) -> PriceResult:
        """Prices and burdens after `shocks` (they add; see `shocks.py`).

        Raises ValueError for a flow tax under "wp6", or a dollar amount there
        on an industry with no intermediate sales; KeyError for an unknown code.
        """
        shocks = list(shocks)
        if self.formulation == "output_tax":
            p_hat, total_tax = self._output_tax(shocks)
        else:
            p_hat, total_tax = self._wp6(shocks)
        dp = p_hat - 1
        industries = list(self.A.index)
        F = self.sq.F.loc[industries]
        burden = dp @ F
        final_demand_burden = float(burden.sum())
        return PriceResult(
            industry_prices=pd.DataFrame({
                "code": industries,
                "description": list(self.sq.industry_labels.loc[industries]),
                "pct_change": dp.loc[industries].to_numpy(),
            }),
            commodity_prices=None,
            pce_prices=None,
            burden_by_final_demand=pd.DataFrame({
                "code": list(F.columns),
                "description": list(self.sq.final_demand_labels.loc[F.columns]),
                "base_spending": F.sum(axis=0).to_numpy(),
                "burden": burden.loc[F.columns].to_numpy(),
            }),
            summary={
                "formulation": self.formulation,
                "total_tax": total_tax,
                "final_demand_burden": final_demand_burden,
                "identity_residual": final_demand_burden - total_tax,
                "pce_burden": None,
            },
            shocks=shocks,
            notes=[],
        )

    def _output_tax(self, shocks: list) -> tuple[pd.Series, float]:
        """p_hat and the tax collected: output taxes tau * y plus flow taxes at the sellers' new prices."""
        tau, T = to_tau_T(shocks, self.sq)
        p_hat = self._solve(self.A * (1 + T), self.v + tau)
        flow_tax = (T * self.sq.Z).mul(p_hat, axis=0).to_numpy().sum()
        return p_hat, float((tau * self.sq.y).sum() + flow_tax)

    def _wp6(self, shocks: list) -> tuple[pd.Series, float]:
        """p_hat and the tax t * intermediate sales, with t per industry as in the module docstring."""
        t = pd.Series(0.0, index=self.A.index)
        dollar_shocks = []
        for shock in shocks:
            if isinstance(shock, FlowTax):
                raise ValueError(f"formulation 'wp6' takes no flow taxes, got {shock!r}")
            if isinstance(shock, IndustryTax) and shock.rate is not None:
                if shock.code not in t.index:
                    raise KeyError(f"unknown industry code {shock.code!r}")
                t.loc[shock.code] += shock.rate
            else:
                dollar_shocks.append(shock)
        dollars = industry_dollars(dollar_shocks, self.sq)
        sales = self.sq.Z.loc[t.index, t.index].sum(axis=1)
        stranded = (sales == 0) & (dollars != 0)
        if stranded.any():
            raise ValueError(f"formulation 'wp6' spreads dollars over intermediate sales, and these "
                             f"industries have none: {list(stranded.index[stranded])}")
        live = sales != 0
        t.loc[live] += dollars[live] / sales[live]
        p_hat = self._solve(self.A.mul(1 + t, axis=0), self.v)
        return p_hat, float((t * sales).sum())

    @staticmethod
    def _solve(A_hat: pd.DataFrame, b: pd.Series) -> pd.Series:
        """Solve (I - A_hat') p = b; A_hat has the same industries, in the same order, on both axes."""
        industries = A_hat.index
        p = np.linalg.solve(np.eye(len(industries)) - A_hat.to_numpy().T, b.loc[industries].to_numpy())
        return pd.Series(p, index=industries)
