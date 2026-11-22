"""Stage 4: the Leontief price model on the square table (design spec section 8).

Baseline (spec 8.1):

    A = Z diag(y)^-1               technical coefficients (input i per $ of output j)
    v = V.sum(axis=0) / y          value added per $ of output, from the value-added rows
    p = (I - A')^-1 v              a vector of ones (checked to 1e-9)

The table's identities (`validate.check_identities`) are checked first, and
the baseline check holds only when each column's inputs and value added sum
to the industry's output.

Shocks (`shocks.py`) become output taxes tau (per $ of output) and flow-tax
rates T (seller x buyer). Two formulations:

    "output_tax" (default, spec 8.3)
        A_hat = A * (1 + T) elementwise;  p_hat = (I - A_hat')^-1 (v + tau)
        The price increase on final demand equals the tax collected, with flow
        taxes valued at the sellers' new prices.
    "wp6" (spec 8.4), only to reproduce the 2009 Tax Foundation WP6 results
        t_i = dollars_i / industry i's intermediate sales (an IndustryTax given
        as a rate is t_i itself);  A_hat = diag(1 + t) A;  p_hat = (I - A_hat')^-1 v
        No flow taxes, no tax on an industry without intermediate sales (an
        error, in dollars or as a rate), and no burden identity.

Consumer prices (spec 8.5), from the industry price changes dp = p_hat - 1:

    dp_c = market_shares' dp       commodity price changes (producers' prices),
                                   0 for a commodity with no output
    m_t, m_w, m_r                  transportation, wholesale and retail margin
                                   price changes: output-weighted means of dp_c
                                   over the margin commodities (`margin_codes`)
    dP_k = sum_r (PV_r dp_c[r] + TC_r m_t + WM_r m_w + RM_r m_r) / sum_r PurchV_r
                                   PCE price change of NIPA line k; r runs
                                   over line k's bridge rows, dp_c[r] is the
                                   price change of row r's commodity

PV, TC, WM, RM and PurchV are the bridge's producers' value, transportation
costs, wholesale and retail margins and purchasers' value. A bridge commodity
that is not in the table gets dp_c = 0, a line with no purchasers' value dP = 0,
and the run's notes say so.

Every system is solved with numpy.linalg.solve; no inverse is formed. Price
changes are fractions (0.125 = 12.5 percent); dollars are millions.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from iotables import validate
from iotables.bridge import MARGIN_CODES, PCEBridge
from iotables.shocks import FlowTax, IndustryTax, Shock, industry_dollars, to_tau_T
from iotables.square import SquareIOTable

FORMULATIONS = ("output_tax", "wp6")
BASELINE_TOL = 1e-9  # largest allowed |p - 1| in the base year


@dataclass
class PriceResult:
    """The outcome of `PriceModel.run` ($ millions; price changes as fractions).

    `industry_prices`: columns code, description, price_change, one row per
    industry in table order. `commodity_prices` (None when the table has no
    commodity output, `meta["commodity_output"]`): columns code, description,
    price_change, one row per commodity in market-share column order.
    `pce_prices` (None without a PCE bridge): columns nipa_line, pce_category,
    price_change, base_spending (the line's purchasers' value), burden
    (price_change x base_spending), one row per NIPA line, sorted by line number.
    `burden_by_final_demand`: columns code, description, base_spending (the
    column's total), burden (dp' F, the added cost of the column's purchases).
    `summary`: formulation, total_tax, final_demand_burden (the burdens' sum),
    identity_residual (final_demand_burden - total_tax), pce_burden (the PCE
    lines' burdens' sum) and pce_share_of_burden (pce_burden / total_tax); the
    last two are None without a bridge, and the share is None when total_tax is
    0. `shocks` is the list that was run; `notes` holds messages about the run
    (bridge commodities not in the table, lines with no purchasers' value).
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

    With a `pce_bridge`, `run` also gives PCE price changes, which need the
    margin commodities: `margin_codes` maps exactly "transport", "wholesale"
    and "retail" to commodity codes, at least one of each with positive
    commodity output in the table, and defaults to `bridge.MARGIN_CODES` for
    the table's `meta["level"]`. A table without `meta["commodity_output"]`
    (one read back without its market shares, `SquareIOTable.from_frame`)
    gives industry prices and burdens only.

    Every table is checked on construction: its identities
    (`validate.check_identities`, which checks the market shares only when the
    table has them) and its baseline prices. Raises ValueError for an unknown
    formulation, a bridge with a table without commodity output, an industry
    with zero output (its coefficients are undefined), a failed identity,
    baseline prices more than 1e-9 from 1 (the message names the industry
    farthest from 1) and, with a bridge, margin codes that are missing for the
    table's level, have other keys or name no commodity with output.
    """

    def __init__(
        self,
        sq: SquareIOTable,
        pce_bridge: PCEBridge | None = None,
        formulation: str = "output_tax",
        margin_codes: dict[str, list[str]] | None = None,
    ):
        if formulation not in FORMULATIONS:
            raise ValueError(f"formulation must be one of {FORMULATIONS}, got {formulation!r}")
        if pce_bridge is not None and "commodity_output" not in sq.meta:
            raise ValueError("PCE prices need commodity prices, and the table has no commodity output "
                             "(meta['commodity_output']) and market shares to compute them")
        self.sq = sq
        self.pce_bridge = pce_bridge
        self.formulation = formulation
        self.margin_codes = (margin_codes if margin_codes is not None
                             else MARGIN_CODES.get(sq.meta.get("level")))
        industries = sq.industries
        y = sq.y.loc[industries]
        if (y == 0).any():
            raise ValueError(f"industries with zero output: {list(y.index[y == 0])}")
        validate.check_identities(sq)
        if pce_bridge is not None:
            self._check_margin_codes()
        Z = sq.Z.loc[industries, industries]
        self.A = Z.div(y, axis=1)
        self.v = sq.V.loc[:, industries].sum(axis=0) / y
        deviation = (self.baseline_prices() - 1).abs()
        if not (deviation <= BASELINE_TOL).all():  # written so that NaN fails too
            worst = deviation.fillna(np.inf).idxmax()
            raise ValueError(f"baseline prices are not 1 within {BASELINE_TOL}: max |p - 1| = "
                             f"{deviation[worst]} (industry {worst!r}); the table's columns of inputs "
                             "and value added must sum to industry output")

    def _check_margin_codes(self) -> None:
        """Raise ValueError unless `margin_codes` has exactly the three margins, each with a commodity with output."""
        if self.margin_codes is None:
            raise ValueError(f"no built-in margin codes for table level {self.sq.meta.get('level')!r}; "
                             "pass margin_codes={'transport': [...], 'wholesale': [...], 'retail': [...]}")
        expected = {"transport", "wholesale", "retail"}
        keys = set(self.margin_codes)
        if keys != expected:
            raise ValueError(f"margin_codes must have exactly the keys {sorted(expected)}; "
                             f"missing {sorted(expected - keys)}, unexpected {sorted(keys - expected, key=str)}")
        q = self.sq.meta["commodity_output"]
        commodities = set(self.sq.market_shares.columns)
        for margin, codes in self.margin_codes.items():
            if not any(c in commodities and c in q.index and q[c] > 0 for c in codes):
                raise ValueError(f"margin_codes[{margin!r}]: none of {list(codes)} is a commodity of the table "
                                 "with positive output")

    def baseline_prices(self) -> pd.Series:
        """p = (I - A')^-1 v, by industry: ones for a balanced table."""
        return self._solve(self.A, self.v)

    def run(self, shocks: Sequence[Shock]) -> PriceResult:
        """Prices and burdens after `shocks` (they add; see `shocks.py`).

        Raises ValueError for a flow tax under "wp6", or an industry tax there
        (dollars or rate) on an industry with no intermediate sales; KeyError
        for an unknown code; with a bridge, ValueError as in
        `margin_price_changes`.
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
        dp_c = self.commodity_price_changes(dp) if "commodity_output" in self.sq.meta else None
        pce_prices, pce_burden, pce_share, notes = None, None, None, []
        if self.pce_bridge is not None:
            pce_prices, notes = self.pce_price_changes(dp_c, self.margin_price_changes(dp_c))
            pce_burden = float(pce_prices["burden"].sum())
            pce_share = pce_burden / total_tax if total_tax != 0 else None
        return PriceResult(
            industry_prices=pd.DataFrame({
                "code": industries,
                "description": list(self.sq.industry_labels.loc[industries]),
                "price_change": dp.loc[industries].to_numpy(),
            }),
            commodity_prices=None if dp_c is None else pd.DataFrame({
                "code": list(dp_c.index),
                "description": list(self.sq.commodity_labels.loc[dp_c.index]),
                "price_change": dp_c.to_numpy(),
            }),
            pce_prices=pce_prices,
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
                "pce_burden": pce_burden,
                "pce_share_of_burden": pce_share,
            },
            shocks=shocks,
            notes=notes,
        )

    def commodity_price_changes(self, dp: pd.Series) -> pd.Series:
        """dp_c = market_shares' dp, by commodity in market-share column order.

        Industries align by code. A commodity whose output (`meta["commodity_output"]`)
        is not positive has no producers to average over and gets 0.
        """
        shares = self.sq.market_shares
        dp_c = shares.T @ dp
        q = self.sq.meta["commodity_output"].loc[shares.columns]
        return dp_c.where(q > 0, 0.0)

    def margin_price_changes(self, dp_c: pd.Series) -> dict[str, float]:
        """The price change of each margin in `margin_codes`: the mean of `dp_c` over
        its commodities, weighted by commodity output (`meta["commodity_output"]`).

        Codes not in `dp_c`, or without output, are ignored. Raises ValueError when
        there are no margin codes, or when none of a margin's codes is left.
        """
        if self.margin_codes is None:
            raise ValueError(f"no built-in margin codes for table level {self.sq.meta.get('level')!r}; "
                             "pass margin_codes={'transport': [...], 'wholesale': [...], 'retail': [...]}")
        q = self.sq.meta["commodity_output"]
        margins = {}
        for margin, codes in self.margin_codes.items():
            present = [c for c in codes if c in dp_c.index and c in q.index and q[c] > 0]
            if not present:
                raise ValueError(f"none of the {margin} margin commodities {codes} is in the table with output")
            weights = q.loc[present]
            margins[margin] = float((dp_c.loc[present] * weights).sum() / weights.sum())
        return margins

    def pce_price_changes(self, dp_c: pd.Series, margins: dict[str, float]) -> tuple[pd.DataFrame, list[str]]:
        """PCE price changes by NIPA line from `self.pce_bridge` (module docstring), and notes.

        `margins` holds the "transport", "wholesale" and "retail" price changes.
        A bridge commodity not in `dp_c` gets dp_c = 0 (one note per code); a line
        whose purchasers' value sums to 0 gets 0 (one note per line). The frame has
        columns nipa_line, pce_category, price_change, base_spending (the line's
        purchasers' value) and burden (price_change x base_spending), sorted by line
        number when every line is a number and as text otherwise.
        """
        rows = self.pce_bridge.rows
        notes = []
        missing = rows.loc[~rows["commodity"].isin(dp_c.index)]
        for code, group in missing.groupby("commodity", sort=False):
            notes.append(f"PCE bridge commodity {code!r} ({group['commodity_desc'].iloc[0]}) is not in the "
                         f"table; its producers' value gets a price change of 0 "
                         f"(NIPA lines {', '.join(pd.unique(group['nipa_line']))})")
        added = (rows["producers_value"] * rows["commodity"].map(dp_c).fillna(0.0)
                 + rows["transport"] * margins["transport"]
                 + rows["wholesale"] * margins["wholesale"]
                 + rows["retail"] * margins["retail"])
        lines = self.pce_bridge.categories().set_index("nipa_line")
        added = added.groupby(rows["nipa_line"], sort=False).sum().loc[lines.index]
        spending = lines["purchasers_value"]
        zero = spending == 0
        for line in lines.index[zero]:
            notes.append(f"NIPA line {line} ({lines.loc[line, 'pce_category']}) has no purchasers' value; "
                         "its price change is set to 0")
        price_change = (added / spending.where(~zero, 1.0)).where(~zero, 0.0)
        frame = pd.DataFrame({
            "nipa_line": list(lines.index),
            "pce_category": lines["pce_category"].to_numpy(),
            "price_change": price_change.to_numpy(),
            "base_spending": spending.to_numpy(),
            "burden": (price_change * spending).to_numpy(),
        })
        numeric = frame["nipa_line"].str.fullmatch("[0-9]+").all()
        frame = frame.sort_values("nipa_line", key=(lambda s: s.astype(int)) if numeric else None, kind="stable")
        return frame.reset_index(drop=True), notes

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
        stranded = (sales == 0) & ((dollars != 0) | (t != 0))
        if stranded.any():
            raise ValueError(f"formulation 'wp6' levies an industry's tax (dollars or rate) on its intermediate "
                             f"sales, and these industries have none: {list(stranded.index[stranded])}")
        live = sales != 0
        t.loc[live] += dollars[live] / sales[live]
        p_hat = self._solve(self.A.mul(1 + t, axis=0), self.v)
        return p_hat, float((t * sales).sum())

    @staticmethod
    def _solve(A_hat: pd.DataFrame, b: pd.Series) -> pd.Series:
        """Solve (I - A_hat') p = b; A_hat must have the same industries, in the same order, on both axes."""
        if list(A_hat.index) != list(A_hat.columns):
            raise ValueError("the coefficient matrix must have the same industry codes, in the same order, "
                             "on both axes")
        industries = A_hat.index
        p = np.linalg.solve(np.eye(len(industries)) - A_hat.to_numpy().T, b.loc[industries].to_numpy())
        return pd.Series(p, index=industries)
