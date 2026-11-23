"""Cost changes, and their conversion to the price model's inputs.

A cost change is anything that raises costs somewhere in the economy: a tax, a
tariff, a rise in a world price, higher wages. The price model does not ask
where it came from. It takes `c`, the new cost per dollar of each industry's
output, and `dp_m`, the rise in the price of each imported commodity.

    IndustryCost(code, dollars | rate)    adds dollars / y_i, or rate, to c_i
    CommodityCost(code, dollars | rate)   dollars (rate x q, the commodity's
                                          output) shared among the industries
                                          that make the commodity by market
                                          share, then as an industry cost
    ValueAddedCost(component, rate, industries=None)
                                          adds rate x V[component, j] / y_j for
                                          each listed industry (default all)
    ImportPrice(code, rate | dollars)     raises the import price of commodity
                                          `code` ("all": every import) by rate,
                                          or by dollars / imports of it
    IndustryPrice(code, change)           fixes industry i's price change; the
                                          model finds the cost that produces it

Costs add: the same industry named twice accumulates. Dollars are millions and
rates are fractions. Codes are aligned by name, an unknown code raises KeyError,
and a cost on an industry with no output raises ValueError.

`carbon_price` is an example built from these: a price per ton of CO2 on the
fossil fuels, from EIA's CO2 emissions by fuel (Monthly Energy Review table 11.1).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from iotables.download import fetch
from iotables.sources import EIA_CO2_URL, RAW_DIR
from iotables.square import SquareIOTable


def _require_exactly_one(change) -> None:
    if (change.dollars is None) == (change.rate is None):
        raise ValueError(f"{type(change).__name__}({change.code!r}): give exactly one of dollars and rate")


@dataclass(frozen=True)
class IndustryCost:
    """New cost on industry `code`: `dollars` ($ millions) or `rate` (a fraction of its output); exactly one."""

    code: str
    dollars: float | None = None
    rate: float | None = None

    def __post_init__(self):
        _require_exactly_one(self)


@dataclass(frozen=True)
class CommodityCost:
    """New cost on commodity `code`: `dollars` ($ millions) or `rate` (a fraction of the commodity's output); exactly one.

    The dollars fall on the industries that make the commodity, in proportion to their market shares.
    """

    code: str
    dollars: float | None = None
    rate: float | None = None

    def __post_init__(self):
        _require_exactly_one(self)


@dataclass(frozen=True)
class ValueAddedCost:
    """Value-added row `component` (e.g. "V00100") rises by `rate` (a fraction) in `industries` (default all)."""

    component: str
    rate: float
    industries: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ImportPrice:
    """The import price of commodity `code` ("all": every import) rises: by `rate` (a fraction), or by the rate
    that costs `dollars` ($ millions) on base-year imports; exactly one."""

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


CostChange = IndustryCost | CommodityCost | ValueAddedCost | ImportPrice | IndustryPrice


def _check_industry(code: str, sq: SquareIOTable) -> None:
    if code not in sq.Z.index:
        raise KeyError(f"unknown industry code {code!r}")


def industry_dollars(changes: Sequence[CostChange], sq: SquareIOTable) -> pd.Series:
    """Dollars ($ millions) each industry bears from the industry, commodity and value-added costs.

    Indexed by all of `sq`'s industries, zero where nothing lands. Rates become
    dollars: `rate * y_i`, `rate * q_c`, `rate * V`. Import and fixed prices are
    not industry dollars and are skipped here. Raises KeyError for an unknown
    industry, commodity or value-added code.
    """
    industries = sq.industries
    dollars = pd.Series(0.0, index=industries)
    for change in changes:
        if isinstance(change, IndustryCost):
            _check_industry(change.code, sq)
            dollars.loc[change.code] += (change.dollars if change.dollars is not None
                                         else change.rate * sq.y.loc[change.code])
        elif isinstance(change, CommodityCost):
            if change.code not in sq.market_shares.columns:
                raise KeyError(f"unknown commodity code {change.code!r}")
            total = change.dollars if change.dollars is not None else change.rate * sq.meta["commodity_output"].loc[change.code]
            dollars += total * sq.market_shares[change.code].loc[industries]
        elif isinstance(change, ValueAddedCost):
            if change.component not in sq.V.index:
                raise KeyError(f"unknown value-added component {change.component!r}")
            targets = industries if change.industries is None else list(change.industries)
            for code in targets:
                _check_industry(code, sq)
            dollars.loc[targets] += change.rate * sq.V.loc[change.component, targets]
        elif not isinstance(change, (ImportPrice, IndustryPrice)):
            raise TypeError(f"not a cost change: {change!r}")
    return dollars


def cost_per_dollar(changes: Sequence[CostChange], sq: SquareIOTable) -> pd.Series:
    """c: the new cost per dollar of each industry's output, dollars / y.

    Raises ValueError, naming the industries, when a cost lands on an industry
    whose output is zero, and KeyError for an unknown code.
    """
    industries = sq.industries
    dollars = industry_dollars(changes, sq)
    y = sq.y.loc[industries]
    stranded = (y == 0) & (dollars != 0)
    for change in changes:
        if isinstance(change, IndustryCost) and y.loc[change.code] == 0 and (change.dollars or change.rate):
            stranded.loc[change.code] = True      # a rate on zero output costs nothing, but is still a cost change
    if stranded.any():
        raise ValueError(f"cost on industries with zero output: {list(stranded.index[stranded])}")
    c = pd.Series(0.0, index=industries)
    live = y != 0
    c.loc[live] = dollars[live] / y[live]
    return c


def import_price_changes(changes: Sequence[CostChange], sq: SquareIOTable) -> pd.Series:
    """dp_m: the rise in the import price of each imported commodity from the `ImportPrice` changes.

    Indexed by the commodities of `sq.imported_inputs`; empty for a table without
    them. Dollars become the rate that costs them on the commodity's base-year
    imports by all buyers (`sq.total_imports`). Raises ValueError for an import
    price on a table without imported inputs or a dollar amount on a commodity
    with no imports, and KeyError for an unknown commodity.
    """
    prices = [s for s in changes if isinstance(s, ImportPrice)]
    if sq.imported_inputs is None:
        if prices:
            raise ValueError(f"{prices[0]!r} needs a table with imported inputs")
        return pd.Series(dtype=float)
    total = sq.total_imports
    dp_m = pd.Series(0.0, index=sq.imported_inputs.index)
    for change in prices:
        if change.code != "all" and change.code not in dp_m.index:
            raise KeyError(f"unknown imported commodity code {change.code!r}")
        codes = list(dp_m.index) if change.code == "all" else [change.code]
        rate = change.rate
        if rate is None:
            if total.loc[codes].sum() == 0:
                raise ValueError(f"{change!r}: there are no imports of {change.code!r} to carry a dollar amount")
            rate = change.dollars / total.loc[codes].sum()
        dp_m.loc[codes] += rate
    return dp_m


# --- carbon-price example ---------------------------------------------------------

# EIA Monthly Energy Review table 11.1 series: CO2 from energy consumption, by fuel.
EIA_SERIES = {"coal": "CKTCEUS", "natural_gas": "NNTCEUS", "petroleum": "PMTCEUS", "total": "TETCEUS"}

# Where each fuel enters the economy: the extraction industry, and the commodity of the same code.
CARBON_CODES = {"coal": "212100", "natural_gas": "211000", "petroleum": "211000"}

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


def carbon_price(dollars_per_ton_co2: float, emissions_year: int, sq: SquareIOTable, data_dir: Path = RAW_DIR,
                 path: Path | None = None, force: bool = False) -> list[IndustryCost | ImportPrice]:
    """A price of `dollars_per_ton_co2` on `emissions_year`'s CO2, as cost changes on `sq` ($ millions).

    Each fuel's emissions (million metric tons) times the price is a cost in
    $ millions, placed where the fuel enters the economy (`CARBON_CODES`) at one
    rate on domestic output and on imports: the imported part, imports /
    (commodity output + imports), is an `ImportPrice` and the rest an
    `IndustryCost`. Fuels that share a code (oil and gas) are summed. Sorted by
    code. `data_dir`, `path` and `force` are as in `eia_co2_by_fuel`.
    """
    emissions = eia_co2_by_fuel(emissions_year, data_dir=data_dir, force=force, path=path)
    dollars: dict[str, float] = {}
    for fuel, code in CARBON_CODES.items():
        dollars[code] = dollars.get(code, 0.0) + emissions[fuel] * dollars_per_ton_co2
    total = sq.total_imports
    out: list[IndustryCost | ImportPrice] = []
    for code in sorted(dollars):
        imported = float(total.get(code, 0.0))
        share = imported / (float(sq.meta["commodity_output"][code]) + imported) if imported else 0.0
        out.append(IndustryCost(code, dollars=dollars[code] * (1 - share)))
        if share > 0:
            out.append(ImportPrice(code, dollars=dollars[code] * share))
    return out
