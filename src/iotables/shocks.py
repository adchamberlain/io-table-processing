"""Stage 4: shock specifications and their conversion to the price model's (tau, T).

A shock is a policy cost placed on the economy, in millions of dollars or as a
rate (a fraction). The price model (`leontief`) takes two inputs: `tau`, one
number per industry, the cost borne by industry i as a share of its output
(dollars / y_i), and `T`, an industries x industries matrix of per-dollar taxes
on the sale from seller i to buyer j. Design spec section 8.2:

    IndustryTax(code, dollars | rate)   adds dollars / y_i, or rate, to tau_i
    CommodityTax(code, dollars | rate)  dollars (rate x q_c, q_c the commodity's
                                        output) are shared among the industries
                                        that make commodity c by market share,
                                        then taxed as an industry tax
    FlowTax(seller, buyer, rate)        adds rate to T[seller, buyer]
    ValueAddedTax(component, rate, industries=None)
                                        adds rate x V[component, j] / y_j for
                                        each listed industry (default all)

Shocks add: the same industry or flow named twice accumulates. `industry_dollars`
gives the dollars each industry bears (what the price model's WP6 mode takes),
`to_tau_T` the (tau, T) pair. Codes are aligned by name, an unknown code raises
KeyError, and a shock on an industry with no output raises ValueError, since its
tau is undefined.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd

from iotables.square import SquareIOTable


def _require_exactly_one(shock) -> None:
    if (shock.dollars is None) == (shock.rate is None):
        raise ValueError(f"{type(shock).__name__}({shock.code!r}): give exactly one of dollars and rate")


@dataclass(frozen=True)
class IndustryTax:
    """A tax on industry `code`: `dollars` ($ millions) or `rate` (a fraction of its output); exactly one."""

    code: str
    dollars: float | None = None
    rate: float | None = None

    def __post_init__(self):
        _require_exactly_one(self)


@dataclass(frozen=True)
class CommodityTax:
    """A tax on commodity `code`: `dollars` ($ millions) or `rate` (a fraction of the commodity's output); exactly one.

    The dollars fall on the industries that make the commodity, in proportion to their market shares.
    """

    code: str
    dollars: float | None = None
    rate: float | None = None

    def __post_init__(self):
        _require_exactly_one(self)


@dataclass(frozen=True)
class FlowTax:
    """A tax of `rate` (a fraction) on each dollar sold by industry `seller` to industry `buyer`."""

    seller: str
    buyer: str
    rate: float


@dataclass(frozen=True)
class ValueAddedTax:
    """A tax of `rate` (a fraction) on value-added row `component` (e.g. "V00100") of `industries` (default all)."""

    component: str
    rate: float
    industries: tuple[str, ...] | None = None


Shock = IndustryTax | CommodityTax | FlowTax | ValueAddedTax


def _check_industry(code: str, sq: SquareIOTable) -> None:
    if code not in sq.Z.index:
        raise KeyError(f"unknown industry code {code!r}")


def industry_dollars(shocks: Sequence[Shock], sq: SquareIOTable) -> pd.Series:
    """Dollars ($ millions) each industry bears from the industry, commodity and value-added taxes.

    Indexed by all of `sq`'s industries, zero where no shock lands. Rates become
    dollars: `rate * y_i` (industry tax), `rate * q_c` (commodity tax), `rate * V`
    (value-added tax). Flow taxes are not industry dollars and are skipped here.
    Raises KeyError for an unknown industry, commodity or value-added code.
    """
    industries = sq.industries
    dollars = pd.Series(0.0, index=industries)
    for shock in shocks:
        if isinstance(shock, IndustryTax):
            _check_industry(shock.code, sq)
            dollars.loc[shock.code] += shock.dollars if shock.dollars is not None else shock.rate * sq.y.loc[shock.code]
        elif isinstance(shock, CommodityTax):
            if shock.code not in sq.market_shares.columns:
                raise KeyError(f"unknown commodity code {shock.code!r}")
            if shock.dollars is not None:
                total = shock.dollars
            elif "commodity_output" not in sq.meta:
                raise ValueError("a CommodityTax rate needs the table's commodity output, "
                                 "but meta has no 'commodity_output'")
            else:
                total = shock.rate * sq.meta["commodity_output"].loc[shock.code]
            dollars += total * sq.market_shares[shock.code].loc[industries]
        elif isinstance(shock, ValueAddedTax):
            if shock.component not in sq.V.index:
                raise KeyError(f"unknown value-added component {shock.component!r}")
            targets = industries if shock.industries is None else list(shock.industries)
            for code in targets:
                _check_industry(code, sq)
            dollars.loc[targets] += shock.rate * sq.V.loc[shock.component, targets]
        elif not isinstance(shock, FlowTax):
            raise TypeError(f"not a shock: {shock!r}")
    return dollars


def to_tau_T(shocks: Sequence[Shock], sq: SquareIOTable) -> tuple[pd.Series, pd.DataFrame]:
    """The price model's inputs for `shocks`: tau (by industry, dollars / y) and T (industries x industries).

    T holds the flow-tax rates, zero elsewhere. Raises ValueError, naming the
    industries, when a shock lands on an industry whose output y is zero (a
    nonzero dollar amount, or a nonzero industry-tax rate), and KeyError for an
    unknown code.
    """
    industries = sq.industries
    dollars = industry_dollars(shocks, sq)
    y = sq.y.loc[industries]
    stranded = (y == 0) & (dollars != 0)
    for shock in shocks:
        if isinstance(shock, IndustryTax) and y.loc[shock.code] == 0 and (shock.dollars or shock.rate):
            stranded.loc[shock.code] = True      # a rate on zero output collects no dollars, but is still a shock
    if stranded.any():
        raise ValueError(f"shock on industries with zero output: {list(stranded.index[stranded])}")
    tau = pd.Series(0.0, index=industries)
    live = y != 0
    tau.loc[live] = dollars[live] / y[live]
    T = pd.DataFrame(0.0, index=industries, columns=industries)
    for shock in shocks:
        if isinstance(shock, FlowTax):
            for code in (shock.seller, shock.buyer):
                _check_industry(code, sq)
            T.loc[shock.seller, shock.buyer] += shock.rate
    return tau, T
