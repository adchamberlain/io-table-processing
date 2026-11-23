# iotables

A model that turns the Bureau of Economic Analysis (BEA) make and use tables
into a square industry-by-industry input-output table, and uses that table to
trace a cost increase through the economy to the prices consumers pay.

You describe a cost shock: a tax on an industry or a commodity, a tariff on an
imported good, a rise in the price of what one industry sells to another, a rise
in a component of value added, or a given rise in one industry's price. The
model answers two questions: how much does every price in the economy change,
and who pays, by consumer spending category and by component of final demand.

Everything runs from BEA's published files. No credentials, and every number
traces to a downloaded file and a formula. The method builds on the Chamberlain
Economics methodology paper (2011) and Tax Foundation Working Paper No. 6
(2009); see [References](#references). This release covers BEA's 2017 benchmark
tables at the detail level (402 industries).

The repository holds two things, which give the same numbers:

- [`script/`](script/): the whole model as one Python script, `io_model.py`,
  to read and run cell by cell in an editor. The folder is self-contained.
- [`src/iotables/`](src/iotables/): the same method as an importable Python
  module, for use in your own code.

## The script

[`script/io_model.py`](script/io_model.py) is the model as a single file of
about 280 lines: each step is a cell with its formula and the code for it.

```
cd script
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python io_model.py
```

An editor such as Cursor, VS Code, PyCharm or Spyder runs it one `# %%` cell at
a time. Each cell prints a short result and leaves everything in memory as
pandas objects. BEA's files are downloaded once into `script/data/`, and the
results are written as CSV files to `script/output/`.

| Cell | What it does |
| --- | --- |
| Setup | Libraries, and three helpers that download and read BEA's spreadsheets |
| 1 | The data: make table, use table, import matrix, PCE bridge |
| 2 | Commodities with no industry behind them |
| 3 | Market shares |
| 4 | The input-output table: Z, F, y, A, B, v |
| 5 | The shock |
| 6 | The price model |
| 7 | Who pays, by final use |
| 8 | Consumer prices |
| 9 | Results |
| 10 | Appendix: BEA's published total requirements |

A shock is set directly on the model's inputs in cell 5:

```python
tariff["331110"] = 0.25                                 # 25% tariff on imported iron and steel
tariff[:] = 0.10                                        # 10% tariff on all imports
tau["211000"] = 50_000 / y["211000"]                    # $50 billion of cost on oil and gas extraction
tau += 0.05 * q["324110"] * shares["324110"] / y        # 5% excise on refined petroleum
tau += 0.01 * V.loc["V00100"] / y                       # compensation up 1% everywhere
fixed["211000"] = 0.20                                  # the price of oil and gas up exactly 20%
```

`tau` is new cost per dollar of an industry's output, `tariff` the rise in the
price of an imported commodity, and `fixed` a given price change for an
industry. Shocks add.

## The module

Python 3.10 or later. From a clone of this repository:

```
pip install -e ".[dev]"
```

```python
from iotables import (PriceModel, build_square_table, load_bea_tables, load_import_matrix,
                      load_pce_bridge, shocks)

make, use = load_bea_tables("detail", 2017)             # cached download and parse
imports = load_import_matrix("detail", 2017)            # BEA's import matrix
sq = build_square_table(make, use, imports=imports)
sq.Z                                                    # 402 x 402 domestic intermediate flows, a DataFrame
sq.imported_inputs                                      # imported commodities x industries
sq.check_identities()                                   # raises ValueError if an identity fails
sq.to_csv("output/table")                               # the table's parts as CSV files

model = PriceModel(sq, pce_bridge=load_pce_bridge("detail", 2017))
result = model.run([
    shocks.ImportTariff("331110", rate=0.25),                   # 25 percent tariff on imported steel
    shocks.IndustryTax("211000", dollars=50_000),               # $50 billion of cost on oil and gas extraction
    shocks.IndustryPrice("212100", 0.10),                       # the price of coal rises exactly 10 percent
    shocks.CommodityTax("324110", rate=0.05),                   # 5 percent of refined petroleum output
    shocks.FlowTax(seller="221100", buyer="331110", rate=0.10), # electricity bought by steel mills
    shocks.ValueAddedTax("V00100", rate=0.01),                  # 1 percent rise in compensation, all industries
])
result.summary
result.pce_prices.sort_values("price_change", ascending=False).head()
result.to_csv("output/results")                         # the result frames as CSV files

carbon = model.run(shocks.carbon_price(dollars_per_ton_co2=50, emissions_year=2024, sq=sq))
```

`sq` is a `SquareIOTable` with the frames `Z` (intermediate flows, seller rows
and buyer columns), `F` (final demand), `V` (value added) and the Series `y`
(industry output). `result` is a `PriceResult` with `industry_prices`,
`commodity_prices`, `pce_prices`, `burden_by_final_demand` and `summary`.
Dollars are millions; rates and price changes are fractions.

The module's defaults are the script's method. It adds a carbon-price example
(`shocks.carbon_price`, from EIA's CO2 emissions by fuel), a shock on the sales
of one industry to another (`shocks.FlowTax`), and a few variants the script
leaves out: `build_square_table(make, use)` without `imports=` combines
imports with domestic purchases; `scrap="redistribute"` and `scrap="keep"` are
other treatments of scrap; `load_bea_tables(..., redefinitions="after")` reads
BEA's after-redefinitions tables; and `PriceModel(..., formulation="wp6")`
reproduces the 2009 working paper.

The runtime dependencies are pandas, numpy, openpyxl and requests. `pytest` runs
the test suite; `pytest -m "not network"` skips the tests that need the
downloaded files.

## Three examples

Results below are from 2026-11-22 and are the same from the script and the module.

**A 25 percent tariff on imported iron and steel** (the script's default). The
tariff collects $8.4 billion. The largest price increases are in the industries
that buy the most imported steel per dollar of output: steel products made from
purchased steel (3.6 percent), motor vehicle metal stamping (2.2 percent),
fabricated pipe (2.1 percent). Consumers bear $2.1 billion, 25 percent of the
total; most of the rest falls on business investment in equipment and
structures and on exports.

**A $50 per ton carbon price on 2024 emissions** (`shocks.carbon_price` in the
module: EIA's emissions by fuel times the price, placed on coal mining and on
oil and gas extraction, at the same rate on domestic output and on imports).
The cost is $239.1 billion. Personal consumption bears $115.4 billion
(48 percent), exports $63.5 billion, private investment $31.6 billion and
government $31.2 billion. The largest consumer price increases:

| Category | Price change |
| --- | --- |
| Gasoline and other motor fuel | 17.4% |
| Fuel oil | 16.3% |
| Other fuels | 8.5% |
| Lubricants and fluids | 8.0% |
| Electricity | 5.0% |
| Natural gas | 2.7% |

As a check on the size: $50 per ton of CO2 is about $0.44 per gallon of
gasoline, roughly 18 percent of the 2017 pump price.

**An excise equal to 5 percent of the output of refined petroleum products**
(the fourth line above). It collects $23.9 billion, raises
the price of gasoline and other motor fuel by 2.4 percent, and personal
consumption bears 54 percent of it.

## How to read the results

- All dollar figures are millions of dollars of the table's year, 2017. The
  carbon example places the emissions year's cost on the 2017 economy as it
  stands; the table is not inflated.
- A price change of 0.05 is 5 percent. The burden on a spending category is its
  base spending times its price change.
- The burdens add up to the shock: the total price increase on final demand,
  on domestic output and on final users' own imports, equals the dollars of the
  shock.
- The model passes costs forward in full and holds quantities fixed, so the
  results are a short-run upper bound. In particular, domestic producers do not
  raise their prices to match a tariff on competing imports. Add a price shock
  on the domestic industry to assume that they do.
- Exports bear part of a domestic cost shock because nothing is rebated at the
  border.
- Consumer burdens are computed in purchasers' prices from BEA's PCE bridge, so
  they differ slightly from the PCE column of final demand, which is in
  producers' prices. Each commodity is given one imported share in consumer
  purchases, the same in every spending category that buys it. Two bridge
  lines, personal remittances in kind to nonresidents (149) and expenditures in
  the United States by nonresidents (338), carry negative base spending by
  BEA's design.

## Method

BEA publishes a make table M (what each industry produces, industries by
commodities) and a use table (what each industry buys, U, commodities by
industries; what goes to final demand, D; and each industry's value added), in
producers' prices and millions of dollars. BEA's import matrix gives the
imported part of every cell of the use table, U_m and D_m.

These are converted to an industry-by-industry table on the assumption that each
commodity is supplied by the industries that make it in fixed market shares
(Eurostat's Model D, which BEA calls the industry-technology assumption). With
q the commodity output:

```
N   = M diag(q)^-1     market shares: industry i's share of commodity c
U_d = U - U_m          domestic intermediate purchases
D_d = D - D_m          domestic final demand
Z   = N U_d            intermediate flows, industries x industries
F   = N D_d            final demand, industries x final-demand columns
y   = Z 1 + F 1        industry output, the row totals of [Z | F]
B   = U_m diag(y)^-1   imported commodity c per dollar of industry j's output
```

Compensation and taxes on production come from the use table and gross operating
surplus is the balancing item, so each industry's domestic inputs, imported
inputs and value added equal its output.

The price model is the Leontief cost-push model on that table, with base-year
prices equal to 1:

```
A     = Z diag(y)^-1                        domestic input from industry i per dollar of industry j's output
v     = value added / y                     value added per dollar of output
A_hat = A * (1 + T)                         T holds price rises on particular sales, if any
p     = (I - A_hat')^-1 (v + tau + B' p_m)  tau: new cost per dollar of each industry's output
                                            p_m: import prices, 1 plus any tariff
```

`p - 1` is each industry's price change. A fixed price change for an industry
is met by solving for the cost on that industry that produces it. Commodity
price changes are the market-share-weighted averages of the industry price
changes, and BEA's PCE bridge carries them to the 212 personal consumption
categories in purchasers' prices: each commodity at a blend of its domestic and
import price changes, and the trade and transportation margins at the
wholesale, retail and transportation industries' own price changes.

### Imports

BEA's use table records what each industry buys of each commodity without
saying where it was made, and offsets total imports in one negative column of
final demand. BEA's import matrix separates the imported part of each purchase.
A cost on domestic producers then moves domestic prices only, and a tariff
reaches every industry that buys the imported good, and through them their
customers. The import matrix is published before redefinitions, so the model
uses BEA's before-redefinitions tables. Noncomparable imports are kept as an
imported commodity.

Without the split, imports are counted as domestic purchases: a cost on a
domestic industry also raises the price of the imported share of its commodity,
which overstates price effects for heavily imported goods.

In BEA's data a dozen cells record more imports than purchases, nearly all for
biological products (325414). They are used as published, which leaves small
negative domestic purchases in those cells ($5.0 billion of $13.4 trillion).

### Commodities that leave the tables

Four commodities do not fit the market-share assumption and are removed: scrap
(S00401), a byproduct of many industries; used and secondhand goods (S00402)
and noncomparable imports (S00300), which no domestic industry makes; and the
rest-of-world adjustment (S00900), an accounting entry. Following BEA's
handbook, each industry's market shares are scaled by the share of its output
that stays in the table, so every industry's output equals BEA's to within the
rounding of BEA's tables. Purchases of the removed commodities fall into gross
operating surplus, except noncomparable imports, which stay as an imported
input.

## Validation

The test suite checks the accounting identities of every table it builds, and
that the burdens of every run sum to the shock. It reproduces four published
results: BEA's own three-industry handbook example, the 2002 Chamberlain
Economics summary and detailed tables, BEA's published 2017
industry-by-industry requirements table (to 7.0e-4; the script's last cell
does the same), and the price impacts of Tax Foundation Working Paper No. 6
under `formulation="wp6"`. The import split, tariffs and fixed prices are
checked against a three-industry economy worked by hand, and a fixed price
against the textbook solution with that industry's equation removed. The script
and the module are run on the same shocks and must give the same tables, prices
and result files.

## Data sources

All files are public and need no key. The URLs are in cells 1 and 10 of
`script/io_model.py` and in `src/iotables/sources.py`.

- BEA 2017 benchmark detail make and use tables, before redefinitions (each
  workbook also holds the 2007 and 2012 benchmarks):
  - https://apps.bea.gov/industry/xls/io-annual/IOMake_Before_Redefinitions_2017_Detail.xlsx
  - https://apps.bea.gov/industry/xls/io-annual/IOUse_Before_Redefinitions_PRO_2017_Detail.xlsx
- BEA import matrix, before redefinitions, the imported part of each cell of the
  use table:
  https://apps.bea.gov/industry/xls/io-annual/ImportMatrices_Before_Redefinitions_DET_2017.xlsx
- BEA PCE bridge, personal consumption by commodity in producers' and
  purchasers' prices:
  https://apps.bea.gov/industry/xls/underlying-estimates/PCEBridge_2017_DET.xlsx
- For the check against BEA: its 2017 industry-by-industry total requirements,
  and the after-redefinitions make and use tables it was built from:
  - https://apps.bea.gov/industry/xls/io-annual/IxI_TR_2017_PRO_DET.xlsx
  - https://apps.bea.gov/industry/xls/io-annual/IOMake_After_Redefinitions_2017_Detail.xlsx
  - https://apps.bea.gov/industry/xls/io-annual/IOUse_After_Redefinitions_PRO_2017_Detail.xlsx
- EIA Monthly Energy Review, table 11.1, CO2 emissions from energy consumption
  by source, for the carbon example:
  https://www.eia.gov/totalenergy/data/browser/csv.php?tbl=T11.01

## References

- Chamberlain Economics, L.L.C. (2011). "Methodology Paper: Developing Square
  U.S. Input-Output Tables from B.E.A. Make and Use Tables." Updated February
  2011. [`docs/reference/IO_Methodology.pdf`](docs/reference/IO_Methodology.pdf)
- Chamberlain, Andrew (2009). "Who Pays for Climate Policy? New Estimates of the
  Household Burden and Economic Impact of a U.S. Cap-and-Trade System." Tax
  Foundation Working Paper No. 6, March 2009.
  [`docs/reference/wp6.pdf`](docs/reference/wp6.pdf)
- Horowitz, Karen J., and Mark A. Planting (2006, updated 2009). *Concepts and
  Methods of the U.S. Input-Output Accounts*. Bureau of Economic Analysis.
  https://www.bea.gov/resources/methodologies/concepts-methods-io-accounts
- Miller, Ronald E., and Peter D. Blair (2009). *Input-Output Analysis:
  Foundations and Extensions*, 2nd ed. Cambridge University Press.

## Roadmap

Next is BEA's annual summary-level tables (71 industries, 1997 onward), which
BEA serves through its API. They need a free BEA API key, read from the
`BEA_API_KEY` environment variable.

## Repository layout

```
script/           the whole model as one script; self-contained
  io_model.py     the script, in ten cells
  requirements.txt
  README.md       how to set it up and run it
src/iotables/     the same method as an importable module
  sources.py      URLs of the BEA and EIA files
  download.py     cached downloads
  parse.py        BEA workbooks -> MakeTable, UseTable, ImportMatrix
  square.py       make, use and imports -> SquareIOTable (Z, F, V, y)
  validate.py     identity checks; BEA's total requirements
  shocks.py       shock types and the carbon example
  bridge.py       BEA's PCE bridge
  leontief.py     PriceModel -> PriceResult
tests/            pytest suite and fixtures
docs/             reference papers and design notes
```

## License

MIT; see [`LICENSE`](LICENSE).
