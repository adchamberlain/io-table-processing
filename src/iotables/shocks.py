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

    ImportTariff(code, rate | dollars)  raises the import price of commodity
                                        `code` ("all" for every import) by rate,
                                        or by dollars / imports of it; needs a
                                        table built with BEA's import matrix
    IndustryPrice(code, change)         fixes industry i's price change at
                                        `change`; the model finds the cost on
                                        the industry that produces it

Shocks add: the same industry or flow named twice accumulates. `industry_dollars`
gives the dollars each industry bears (what the price model's WP6 mode takes),
`to_tau_T` the (tau, T) pair. Codes are aligned by name, an unknown code raises
KeyError, and a shock on an industry with no output raises ValueError, since its
tau is undefined.

`carbon_price` builds a preset: a $/ton CO2 price on the fossil-fuel extraction
industries, from EIA's CO2 emissions by fuel (Monthly Energy Review table 11.1).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from iotables.download import fetch
from iotables.sources import EIA_CO2_URL, RAW_DIR
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


@dataclass(frozen=True)
class ImportTariff:
    """A tariff on imports of commodity `code` ("all": every import): `rate` (the rise in the import price,
    a fraction) or `dollars` ($ millions collected on base-year imports); exactly one."""

    code: str
    rate: float | None = None
    dollars: float | None = None

    def __post_init__(self):
        _require_exactly_one(self)


@dataclass(frozen=True)
class IndustryPrice:
    """The price of industry `code` rises by exactly `change` (a fraction), whatever else lands on it."""

    code: str
    change: float


Shock = IndustryTax | CommodityTax | FlowTax | ValueAddedTax | ImportTariff | IndustryPrice


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
        elif not isinstance(shock, (FlowTax, ImportTariff, IndustryPrice)):
            raise TypeError(f"not a shock: {shock!r}")
    return dollars


def import_price_changes(shocks: Sequence[Shock], sq: SquareIOTable) -> pd.Series:
    """The rise in the import price of each imported commodity from the `ImportTariff` shocks (fractions).

    Indexed by the commodities of `sq.imported_inputs`; empty for a table without
    an import split. A tariff in dollars becomes the rate that collects them on
    the commodity's base-year imports by all buyers (`sq.total_imports`). Raises
    ValueError for a tariff on a table without an import split or a dollar
    tariff on a commodity with no imports, and KeyError for an unknown commodity.
    """
    tariffs = [s for s in shocks if isinstance(s, ImportTariff)]
    if sq.imported_inputs is None:
        if tariffs:
            raise ValueError(f"{tariffs[0]!r} needs a table built with BEA's import matrix "
                             "(build_square_table(..., imports=...))")
        return pd.Series(dtype=float)
    total = sq.total_imports
    dp_m = pd.Series(0.0, index=sq.imported_inputs.index)
    for shock in tariffs:
        if shock.code != "all" and shock.code not in dp_m.index:
            raise KeyError(f"unknown imported commodity code {shock.code!r}")
        codes = list(dp_m.index) if shock.code == "all" else [shock.code]
        rate = shock.rate
        if rate is None:
            if total.loc[codes].sum() == 0:
                raise ValueError(f"{shock!r}: there are no imports of {shock.code!r} to carry a dollar amount")
            rate = shock.dollars / total.loc[codes].sum()
        dp_m.loc[codes] += rate
    return dp_m


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


# --- carbon-pricing preset ----------------------------------------------------

# EIA Monthly Energy Review table 11.1 series: CO2 from energy consumption, by fuel.
EIA_SERIES = {"coal": "CKTCEUS", "natural_gas": "NNTCEUS", "petroleum": "PMTCEUS", "total": "TETCEUS"}

# The extraction industry where a fuel enters the economy ("upstream" coverage), by table level.
CARBON_INDUSTRIES = {"detail": {"coal": "212100", "natural_gas": "211000", "petroleum": "211000"}}

_EIA_FILENAME = "eia_t11_01.csv"     # the URL path is csv.php, so fetch's default filename would be useless


def eia_co2_by_fuel(year: int, data_dir: Path = RAW_DIR, force: bool = False, path: Path | None = None) -> dict[str, float]:
    """US energy-related CO2 emissions in `year`, million metric tons, by fuel (keys of `EIA_SERIES`).

    Reads EIA's annual rows (`YYYYMM` is `<year>13`) of Monthly Energy Review table 11.1,
    downloaded to `data_dir / "eia"` and cached; `path` reads that CSV instead, with no
    download. Raises ValueError when a series has no value for `year` (no annual row,
    or a "Not Available" value).
    """
    if path is None:
        path = fetch(EIA_CO2_URL, Path(data_dir) / "eia", filename=_EIA_FILENAME, force=force)
    df = pd.read_csv(path, dtype=str, usecols=["MSN", "YYYYMM", "Value"])
    annual = df[df["YYYYMM"] == f"{year}13"]
    out = {}
    for fuel, msn in EIA_SERIES.items():
        values = pd.to_numeric(annual.loc[annual["MSN"] == msn, "Value"], errors="coerce").dropna()
        if len(values) != 1:
            raise ValueError(f"{path}: expected one CO2 value for {msn} ({fuel}) in {year}, found {len(values)}")
        out[fuel] = float(values.iloc[0])
    return out


def carbon_price(dollars_per_ton_co2: float, emissions_year: int, coverage: str = "upstream", level: str = "detail",
                 data_dir: Path = RAW_DIR, path: Path | None = None, force: bool = False,
                 sq: SquareIOTable | None = None) -> list[IndustryTax | ImportTariff]:
    """A carbon price of `dollars_per_ton_co2` on `emissions_year`'s CO2, as industry taxes ($ millions).

    Upstream coverage taxes each fossil fuel where it is extracted: million metric
    tons x $/ton = $ millions, put on the industry `CARBON_INDUSTRIES` names for
    `level`. Fuels that share an industry (oil and gas) are summed into one tax.
    Returns one `IndustryTax` per industry, sorted by code. With `sq`, a table
    with an import split, each fuel's dollars fall at one rate on domestic output
    and on imports of the commodity with the industry's code: the imported part,
    imports / (commodity output + imports), becomes an `ImportTariff` that
    follows the industry's tax. Raises
    NotImplementedError for any other `coverage` and KeyError for an unknown `level`.
    `data_dir`, `path` and `force` are as in `eia_co2_by_fuel`.
    """
    if coverage != "upstream":
        raise NotImplementedError(f"carbon_price coverage {coverage!r}: only 'upstream' is implemented")
    if level not in CARBON_INDUSTRIES:
        raise KeyError(f"no carbon-price industries for level {level!r}; have {sorted(CARBON_INDUSTRIES)}")
    emissions = eia_co2_by_fuel(emissions_year, data_dir=data_dir, force=force, path=path)
    dollars: dict[str, float] = {}
    for fuel, code in CARBON_INDUSTRIES[level].items():
        dollars[code] = dollars.get(code, 0.0) + emissions[fuel] * dollars_per_ton_co2
    out: list[IndustryTax | ImportTariff] = []
    total = sq.total_imports if sq is not None else pd.Series(dtype=float)
    for code in sorted(dollars):
        imported = float(total.get(code, 0.0))
        share = imported / (float(sq.meta["commodity_output"][code]) + imported) if imported else 0.0
        out.append(IndustryTax(code, dollars=dollars[code] * (1 - share)))
        if share > 0:
            out.append(ImportTariff(code, dollars=dollars[code] * share))
    return out
