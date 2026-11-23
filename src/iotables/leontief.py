"""The Leontief price model on the square table.

In the base year every price is 1 and each industry's price equals its costs
per dollar of output: domestic inputs, imported inputs and value added.

    A = Z diag(y)^-1               domestic input i per $ of output j
    B = U_m diag(y)^-1             imported commodity per $ of output j
    v = V.sum(axis=0) / y          value added per $ of output
    p = (I - A')^-1 (v + B' p_m)   a vector of ones when p_m = 1 (checked to 1e-9)

Cost changes (`costs.py`) become c, new cost per $ of each industry's output,
and dp_m, the rise in import prices:

    p = (I - A')^-1 (v + c + B' p_m),   dp = p - 1

The price increase on final demand, on domestic output and on final users' own
imports, equals the total cost, c' y + dp_m' imports. An `IndustryPrice` fixes
an industry's price change: with L = (I - A')^-1 and S the fixed industries,
c_S solves L[S, S] c_S = (1 + change) - p[S] without it.

Consumer prices, from the industry price changes:

    dp_c = market_shares' dp       commodity price changes (producers' prices)
    m_t, m_w, m_r                  transportation, wholesale and retail margin
                                   price changes: output-weighted means of dp_c
                                   over the margin commodities (`margin_codes`)
    dP_k = sum_r (PV_r dpc_r + TC_r m_t + WM_r m_w + RM_r m_r) / sum_r PurchV_r
                                   PCE price change of NIPA line k over its
                                   bridge rows r

dpc_r blends the domestic and import price changes of row r's commodity by the
imported share of personal consumption of it: (1 - m) dp_c + m dp_m. PV, TC,
WM, RM and PurchV are the bridge's producers' value, transportation costs,
wholesale and retail margins and purchasers' value. A bridge commodity that is
not in the table gets a price change of 0, as does a line with no purchasers'
value, and the run's notes say so.

Price changes are fractions (0.125 = 12.5 percent); dollars are millions.
"""

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from iotables import validate
from iotables.bridge import MARGIN_CODES, PCEBridge
from iotables.costs import CostChange, IndustryPrice, cost_per_dollar, import_price_changes
from iotables.square import SquareIOTable

BASELINE_TOL = 1e-9  # largest allowed |p - 1| in the base year


@dataclass
class PriceResult:
    """The outcome of `PriceModel.run` ($ millions; price changes as fractions).

    `industry_prices`: code, description, price_change, one row per industry.
    `commodity_prices`: code, description, price_change (domestic output),
    import_price_change and pce_import_share, one row per commodity, the
    imported-only ones included (the last two columns are absent for a table
    without imported inputs). `pce_prices` (None without a PCE bridge):
    nipa_line, pce_category, price_change, base_spending, burden, one row per
    NIPA line, sorted by line number. `burden_by_final_demand`: code,
    description, base_spending, burden. `summary`: total_cost,
    final_demand_burden, identity_residual (their difference), pce_burden and
    pce_share_of_cost (None without a bridge; the share is None when the total
    is 0). `changes` is the list that was run; `notes` holds messages about
    the run.
    """

    industry_prices: pd.DataFrame
    commodity_prices: pd.DataFrame
    pce_prices: pd.DataFrame | None
    burden_by_final_demand: pd.DataFrame
    summary: dict
    changes: list
    notes: list[str]

    def to_csv(self, directory: Path) -> dict[str, Path]:
        """Write the result as CSV files in `directory`; returns {name: path}.

        industry_prices, commodity_prices, pce_prices (when there is one) and
        burden_by_final_demand, summary (columns item, value) and changes (one
        row per cost change: its type and fields).
        """
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        frames = {name: getattr(self, name) for name in
                  ("industry_prices", "commodity_prices", "pce_prices", "burden_by_final_demand")}
        frames["summary"] = pd.Series(self.summary, name="value").rename_axis("item").reset_index()
        frames["changes"] = pd.DataFrame([{"type": type(s).__name__, **dataclasses.asdict(s)} for s in self.changes])
        paths = {}
        for name, frame in frames.items():
            if frame is not None:
                paths[name] = directory / f"{name}.csv"
                frame.to_csv(paths[name], index=False)
        return paths


class PriceModel:
    """The price model on `sq`.

    With a `pce_bridge`, `run` also gives PCE price changes, which need the
    margin commodities: `margin_codes` maps exactly "transport", "wholesale"
    and "retail" to commodity codes, at least one of each with positive
    commodity output in the table, and defaults to `bridge.MARGIN_CODES` for
    the table's `meta["level"]`.

    The table is checked on construction: its identities
    (`validate.check_identities`) and its base-year prices. Raises ValueError
    for an industry with zero output, a failed identity, base-year prices more
    than 1e-9 from 1 and, with a bridge, margin codes that are missing for the
    table's level, have other keys or name no commodity with output.
    """

    def __init__(
        self,
        sq: SquareIOTable,
        pce_bridge: PCEBridge | None = None,
        margin_codes: dict[str, list[str]] | None = None,
    ):
        self.sq = sq
        self.pce_bridge = pce_bridge
        self.margin_codes = margin_codes if margin_codes is not None else MARGIN_CODES.get(sq.meta.get("level"))
        industries = sq.industries
        y = sq.y.loc[industries]
        if (y == 0).any():
            raise ValueError(f"industries with zero output: {list(y.index[y == 0])}")
        validate.check_identities(sq)
        if pce_bridge is not None:
            self._check_margin_codes()
        self.A = sq.Z.loc[industries, industries].div(y, axis=1)
        self.v = sq.V.loc[:, industries].sum(axis=0) / y
        # Imported inputs per $ of output, by imported commodity; None for a table without them.
        self.B = None if sq.imported_inputs is None else sq.imported_inputs.loc[:, industries].div(y, axis=1)
        self.imported_cost = pd.Series(0.0, index=industries) if self.B is None else self.B.sum(axis=0)
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
        """p = (I - A')^-1 (v + B' 1), by industry: ones for a balanced table."""
        return self._solve(self.v + self.imported_cost)

    def run(self, changes: Sequence[CostChange]) -> PriceResult:
        """Prices and burdens after `changes` (they add; see `costs.py`).

        Raises KeyError for an unknown code and ValueError for a cost on an
        industry with no output or an import price that cannot be applied.
        """
        changes = list(changes)
        industries = list(self.A.index)
        c = cost_per_dollar(changes, self.sq)
        dp_m = import_price_changes(changes, self.sq)
        cost = self.v + self.imported_cost
        import_cost = 0.0
        if self.B is not None:
            cost = cost + self.B.T @ dp_m.loc[self.B.index]
            import_cost = float((dp_m * self.sq.total_imports).sum())
        p = self._solve(cost + c)

        fixed = {}
        for change in changes:
            if isinstance(change, IndustryPrice):
                if change.code not in c.index:
                    raise KeyError(f"unknown industry code {change.code!r}")
                fixed[change.code] = change.change
        if fixed:
            S = list(fixed)
            positions = [c.index.get_loc(code) for code in S]
            eye = np.eye(len(c))
            L_columns = np.linalg.solve(eye - self.A.to_numpy().T, eye[:, positions])
            c.loc[S] += np.linalg.solve(L_columns[positions, :], (1 + pd.Series(fixed).loc[S] - p.loc[S]).to_numpy())
            p = self._solve(cost + c)

        dp = p - 1
        total_cost = float((c * self.sq.y).sum() + import_cost)
        F = self.sq.F.loc[industries]
        burden = dp @ F
        base_spending = F.sum(axis=0)
        if self.sq.imported_final is not None:  # final users' own imports, at import prices
            F_m = self.sq.imported_final
            burden = burden.add(dp_m.loc[F_m.index] @ F_m, fill_value=0.0).loc[F.columns]
            base_spending = base_spending.add(F_m.sum(axis=0), fill_value=0.0).loc[F.columns]
        final_demand_burden = float(burden.sum())

        dp_c = self.commodity_price_changes(dp)
        pce_prices, pce_burden, pce_share, notes = None, None, None, []
        if self.pce_bridge is not None:
            pce_prices, notes = self.pce_price_changes(dp_c, self.margin_price_changes(dp_c), dp_m)
            pce_burden = float(pce_prices["burden"].sum())
            pce_share = pce_burden / total_cost if total_cost != 0 else None
        return PriceResult(
            industry_prices=pd.DataFrame({
                "code": industries,
                "description": list(self.sq.industry_labels.loc[industries]),
                "price_change": dp.loc[industries].to_numpy(),
            }),
            commodity_prices=self._commodity_prices(dp_c, dp_m),
            pce_prices=pce_prices,
            burden_by_final_demand=pd.DataFrame({
                "code": list(F.columns),
                "description": list(self.sq.final_demand_labels.loc[F.columns]),
                "base_spending": base_spending.to_numpy(),
                "burden": burden.loc[F.columns].to_numpy(),
            }),
            summary={
                "total_cost": total_cost,
                "final_demand_burden": final_demand_burden,
                "identity_residual": final_demand_burden - total_cost,
                "pce_burden": pce_burden,
                "pce_share_of_cost": pce_share,
            },
            changes=changes,
            notes=notes,
        )

    def _commodity_prices(self, dp_c: pd.Series, dp_m: pd.Series) -> pd.DataFrame:
        """The commodity price frame (see `PriceResult`)."""
        share = self.sq.pce_import_share
        if share is None:
            return pd.DataFrame({
                "code": list(dp_c.index),
                "description": list(self.sq.commodity_labels.loc[dp_c.index]),
                "price_change": dp_c.to_numpy(),
            })
        return pd.DataFrame({
            "code": list(dp_m.index),
            "description": list(self.sq.commodity_labels.reindex(dp_m.index)),
            "price_change": dp_c.reindex(dp_m.index, fill_value=0.0).to_numpy(),
            "import_price_change": dp_m.to_numpy(),
            "pce_import_share": share.reindex(dp_m.index, fill_value=0.0).to_numpy(),
        })

    def commodity_price_changes(self, dp: pd.Series) -> pd.Series:
        """dp_c = market_shares' dp, by commodity in market-share column order.

        A commodity whose output (`meta["commodity_output"]`) is not positive
        has no producers to average over and gets 0.
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

    def pce_price_changes(self, dp_c: pd.Series, margins: dict[str, float],
                          dp_m: pd.Series | None = None) -> tuple[pd.DataFrame, list[str]]:
        """PCE price changes by NIPA line from `self.pce_bridge` (module docstring), and notes.

        `margins` holds the "transport", "wholesale" and "retail" price changes and
        `dp_m` the import price changes. A bridge commodity in neither gets a price
        change of 0 (one note per code); a line whose purchasers' value sums to 0
        gets 0 (one note per line). The frame has columns nipa_line, pce_category,
        price_change, base_spending (the line's purchasers' value) and burden
        (price_change x base_spending), sorted by line number when every line is
        a number and as text otherwise.
        """
        rows = self.pce_bridge.rows
        notes = []
        share = self.sq.pce_import_share
        blended = share is not None and dp_m is not None
        known = dp_c.index.union(dp_m.index) if blended else dp_c.index
        missing = rows.loc[~rows["commodity"].isin(known)]
        for code, group in missing.groupby("commodity", sort=False):
            notes.append(f"PCE bridge commodity {code!r} ({group['commodity_desc'].iloc[0]}) is not in the "
                         f"table; its producers' value gets a price change of 0 "
                         f"(NIPA lines {', '.join(pd.unique(group['nipa_line']))})")
        commodity_change = rows["commodity"].map(dp_c).fillna(0.0)
        if blended:
            m = rows["commodity"].map(share).fillna(0.0)
            commodity_change = (1 - m) * commodity_change + m * rows["commodity"].map(dp_m).fillna(0.0)
        added = (rows["producers_value"] * commodity_change
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

    def _solve(self, b: pd.Series) -> pd.Series:
        """Solve (I - A') p = b."""
        industries = self.A.index
        p = np.linalg.solve(np.eye(len(industries)) - self.A.to_numpy().T, b.loc[industries].to_numpy())
        return pd.Series(p, index=industries)
