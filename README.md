# iotables

Square industry-by-industry U.S. input-output tables built from the Bureau of
Economic Analysis (BEA) make and use tables, and a Leontief price model that
traces a tax or cost increase through the economy to industry prices, commodity
prices and consumer spending categories.

You give the model a tax on an industry, a commodity, a sale from one industry
to another or a component of value added, in dollars or as a rate. It answers
two questions: how do prices change throughout the economy, and who ends up
paying, by consumer spending category and by component of final demand? A
carbon price is one preset of that general model. Everything is built in Python
from BEA's published files, with no spreadsheets and no credentials, and every
number traces to a downloaded file, a date and a formula. The package replaces
the spreadsheet workflow behind the Chamberlain Economics methodology paper
(2011) and the price model of Tax Foundation Working Paper No. 6 (2009); see
[References](#references).

Phase 1 covers BEA's 2017 benchmark detail tables (402 industries).

## Method

BEA's make table M (industries by commodities) records what each industry
produces. Its use table records the commodities each industry buys (U,
commodities by industries), the commodities that go to final demand (D,
commodities by final-demand columns: personal consumption, investment,
government, exports and, as a negative column, imports) and each industry's
value added, all in producers' prices and millions of dollars. Following the
methodology paper, the package converts them to an industry-by-industry table
with a fixed product sales structure (Eurostat's Model D; BEA calls it the
industry-technology assumption): each commodity is supplied by the industries
that make it in fixed market shares. With q the commodity output, the column
totals of M,

```
N = M diag(q)^-1     market shares: industry i's share of the output of commodity c
Z = N U              intermediate flows, industries x industries (seller rows, buyer columns)
F = N D              final demand, industries x final-demand columns
y = Z 1 + F 1        industry output, the row totals of [Z | F]
```

Compensation of employees and taxes on production and imports less subsidies
come from the use table, and gross operating surplus is the balancing item, so
each industry's column total (its inputs plus its value added) equals its output
y. Noncomparable imports and BEA's rest-of-world adjustment, which no domestic
industry produces, are removed first. The price model is the Leontief cost-push
model on that table, with base-year prices equal to 1:

```
A     = Z diag(y)^-1                input from industry i per dollar of industry j's output
v     = column sums of V / y        value added per dollar of each industry's output
A_hat = A * (1 + T)                 elementwise; T holds ad valorem taxes on intermediate sales
p_hat = (I - A_hat')^-1 (v + tau)   tau: the tax per dollar of each industry's output
```

so p_hat - 1 is each industry's proportional price change. A tax on a commodity
falls on the industries that make it in proportion to their market shares, and a
value-added tax adds the rate times the industry's value-added component to its
costs. Commodity price changes are the market-share-weighted averages of the
industry price changes. BEA's PCE bridge then carries them to the 212 personal
consumption categories (NIPA lines) in purchasers' prices, with the trade and
transportation margins priced at the price changes of the wholesale, retail and
transportation industries.

## Scrap and used goods

BEA's tables carry two commodities that do not fit the industry-technology
assumption: scrap (S00401), a byproduct of many industries, and used and
secondhand goods (S00402), which in 2017 carry large transfers within final
demand. The `--scrap` option (`scrap=` in Python) chooses the treatment.

- `bea` (the default) is the nonscrap-ratio method of BEA's handbook (Horowitz
  and Planting, chapter 12). Scrap and used goods leave the make and use tables,
  and each industry's market shares are divided by its nonscrap ratio, the share
  of its output that is not scrap, which keeps industry output equal to BEA's.
  Purchases of scrap and used goods then fall into gross operating surplus.
- `redistribute` is the rule of the 2011 methodology paper. Each column's
  purchases of scrap and used goods are spread over its other commodity
  purchases in proportion to their values, and the two commodities leave the
  tables. Industry output then differs from BEA's by the amounts moved, and
  `iotables build` prints the largest gaps.
- `keep` treats scrap and used goods as ordinary commodities, each with its own
  use-table row and make-table column. Only noncomparable imports and the
  rest-of-world adjustment are removed. It applies to tables in which scrap and
  used goods have producers, for example the 2002 summary table, whose combined
  scrap, used and secondhand goods commodity (S00400) is made by 31 industries.
  The 2017 detail tables need `bea` or `redistribute`, because used goods
  (S00402) have no producer there: under `keep` their purchases would have no
  industry to fall on, and the build stops with a message saying so.

BEA's published 2017 requirements tables keep scrap as an ordinary commodity and
remove only used goods, which `iotables check` reproduces with
`--scrap-codes S00402` (its default). The library default keeps the handbook
treatment of both codes, because scrap is a byproduct whose price is not the
cost-plus price of the industries that generate it, and that matters in a
cost-push price model. `--scrap-codes` (`scrap_codes=` in Python) sets the codes
for any command.

## Install

Python 3.10 or later. From a clone of this repository:

```
pip install -e ".[dev]"
pytest
```

The runtime dependencies are pandas, numpy, openpyxl and requests. The first run
downloads BEA's and EIA's files into `data/raw/`, where they are cached next to a
provenance record of each file's URL, SHA-256 hash and download time. Tests that
need those files are marked `network`; `pytest -m "not network"` skips them.

## Commands

### `iotables build`

```
iotables build
```

Downloads BEA's 2017 detail make and use tables (after redefinitions), builds
the 402-industry table, prints its accounting-identity residuals and the
industries whose output and gross operating surplus differ most from BEA's, and
writes `data/output/us_io_2017_detail_after_bea.xlsx` with a folder of CSV files
of the same name (Z, F, V, y, market shares, labels and metadata). The
spreadsheet has the conventional layout: the industries down the rows, then the
three value-added rows and total output; the industries across the columns, then
the final-demand columns and total output. Options: `--year`,
`--redefinitions after|before`, `--scrap bea|redistribute|keep`,
`--scrap-codes`, `--out`, `--make PATH --use PATH` to read local workbooks in
BEA's layout, and `--force` to download again.

### `iotables check`

```
iotables check
```

Builds the table under BEA's published scrap convention and compares its
industry-by-industry total requirements, (I - A)^-1, with BEA's published 2017
table, cell by cell. It exits with status 1 when any cell differs by more than
`--tol` (default 1e-3).

### `iotables run`

The carbon example puts a price of $50 per metric ton on 2024 CO2 emissions,
collected upstream:

```
iotables run --carbon 50 --emissions-year 2024
```

The preset reads EIA's 2024 energy-related CO2 emissions by fuel and taxes each
fuel where it enters the economy: coal at coal mining (212100), natural gas and
petroleum at oil and gas extraction (211000). EIA's figures are emissions from
domestic consumption, so this approximates an upstream tax with a border
adjustment. An excerpt of the output (run on 2026-11-22):

```
Shocks (2; dollars in $ millions, rates as fractions):
  industry:211000:dollars=201552.05
  industry:212100:dollars=37561.85

Price model summary, formulation output_tax ($ millions):
  total_tax            239,113.900
  final_demand_burden  239,113.900
  identity_residual    8.731e-11
  pce_burden           230,682.967
  pce_share_of_burden  0.9647 (PCE burden / total tax)

The 20 PCE categories with the largest price increases, of 212 NIPA lines ($ millions):
  line      change   base spending        burden  category
  115      31.827%       291,554.0      92,794.0  Gasoline and other motor fuel
  118      29.945%        17,419.0       5,216.2  Fuel oil
  119      15.006%         4,063.0         609.7  Other fuels
  116      14.822%        10,948.0       1,622.8  Lubricants and fluids
  204       8.859%        13,021.0       1,153.5  Taxicabs and ride sharing services
  205       8.859%        20,858.0       1,847.7  Intracity mass transit
  203       8.859%         1,451.0         128.5  Intercity buses
  170       8.616%       177,661.0      15,307.9  Electricity
  ...
```

An excise tax equal to 5 percent of the output of refined petroleum products
(commodity 324110):

```
iotables run --shock commodity:324110:rate=0.05
```

That tax collects $23.9 billion and raises the price of gasoline and other
motor fuel by 2.7 percent; personal consumption bears 68 percent of it.

`--shock` takes one of these specs (dollars in millions, rates as fractions); it
can be repeated, and shocks add:

| Spec | Meaning |
| --- | --- |
| `industry:CODE:dollars=X` | $X million of tax on industry CODE |
| `industry:CODE:rate=R` | a tax of R per dollar of the industry's output |
| `commodity:CODE:dollars=X` | $X million on commodity CODE, shared among the industries that make it by market share |
| `commodity:CODE:rate=R` | R times the commodity's output, shared the same way |
| `flow:SELLER:BUYER:rate=R` | a tax of R per dollar of industry BUYER's purchases from industry SELLER |
| `va:COMPONENT:rate=R[:industries=A,B]` | R times value-added row COMPONENT (V00100 compensation, V00200 taxes on production and imports, V00300 gross operating surplus) of every industry, or of those listed |

`run` builds (and writes) the table as `build` does and takes the same options. With
`--table PATH.xlsx` it reads a table that `build` wrote instead; the CSV folder
next to it supplies the market shares, and without that folder the run gives
industry prices and final-demand burdens only. `--formulation wp6` selects the
formulation of Working Paper No. 6 (see [Validation](#validation)), and
`--no-pce` skips the PCE bridge. The run writes six files into `--out` (default
`data/output`):

- `industry_prices.csv`: code, description and price_change for each industry.
- `commodity_prices.csv`: the same for each commodity, in producers' prices.
- `pce_prices.csv`: nipa_line, pce_category, price_change, base_spending (in
  purchasers' prices) and burden for each PCE category.
- `burden_by_final_demand.csv`: base spending and burden for each of BEA's 20
  final-demand columns.
- `summary.json`: total_tax, final_demand_burden, identity_residual,
  pce_burden and pce_share_of_burden, with the table, the carbon price and the
  run's notes.
- `shocks.json`: every shock that was run, including those of the carbon preset.

A price change of 0.05 is 5 percent.

## Python API

```python
from iotables import PriceModel, build_square_table, load_bea_tables, load_pce_bridge, shocks

make, use = load_bea_tables("detail", 2017, "after")       # cached download and parse
sq = build_square_table(make, use)                          # scrap="bea", the default
sq.check_identities()                                       # raises ValueError if an identity fails
sq.to_excel("data/output/us_io_2017_detail.xlsx")

model = PriceModel(sq, pce_bridge=load_pce_bridge("detail", 2017))
result = model.run([
    shocks.IndustryTax("211000", dollars=50_000),               # $50 billion on oil and gas extraction
    shocks.CommodityTax("324110", rate=0.05),                   # 5 percent of refined petroleum output
    shocks.FlowTax(seller="221100", buyer="331110", rate=0.10), # electricity bought by steel mills
    shocks.ValueAddedTax("V00100", rate=0.01),                  # 1 percent payroll tax, all industries
])
result.summary
result.pce_prices.sort_values("price_change", ascending=False).head()

carbon = model.run(shocks.carbon_price(dollars_per_ton_co2=50, emissions_year=2024))
```

`result` is a `PriceResult` holding the same frames and summary that
`iotables run` writes.

## How to read the results

All dollar figures are millions of dollars of the table's year, 2017; the table
is not inflated to a later year. The carbon preset multiplies the emissions
year's tons by the price and places that dollar amount on the 2017 table as it
stands, so its price changes reflect the tax relative to the 2017 economy. The
burden on a final-demand column is its spending weighted by the industry price
changes dp = p_hat - 1, that is dp' F. Under the default formulation the
burdens add up to the tax: the total price increase on final demand equals the
tax collected, and `identity_residual` in `summary.json` (that sum minus the
tax) is zero to rounding. Imports enter the use table as a negative final-demand
column, so the imports column carries a negative burden, and the burdens on the
positive components (personal consumption, investment, government and exports)
sum to more than the tax. In the carbon example imports carry -$202.9 billion
and exports $115.7 billion. `pce_share_of_burden` is relative to the tax, not to
the sum of the positive burdens, which is why it can come close to 1: it is
0.965 in the carbon example, where consumers bear about half of the burden on
the positive components. The PCE burden is computed in purchasers' prices from
BEA's PCE bridge, so it differs slightly from the burden on the PCE column of
final demand, which is in producers' prices. Bridge rows for commodities that
are not in the table (scrap, used goods, noncomparable imports and the
rest-of-world adjustment) get a price change of zero, and the run's notes list
them. The two "Less:" lines of the bridge, personal remittances in kind to
nonresidents (NIPA line 149) and expenditures in the United States by
nonresidents (line 338), carry negative base spending by design: BEA subtracts
them to take nonresidents' purchases out of the PCE total. Their only bridge
commodity is the rest-of-world adjustment (S00900), which is not in the table,
so their price change and burden are zero.

The data directories `data/raw` (downloads) and `data/output` (the default
`--out`) are relative to the directory the command runs in.

## Validation

The test suite checks the accounting identities of every table it builds (row
totals equal column totals, market shares sum to one, baseline prices equal one,
and the burden identity) and reproduces four published results.

1. **BEA's handbook example.** The three-industry example in chapter 12 of
   BEA's *Concepts and Methods of the U.S. Input-Output Accounts* (market
   shares, nonscrap ratios and the requirements tables, 12.8 to 12.15) is
   reproduced to the printed precision by the `bea` scrap treatment.
2. **The 2002 tables.** Regression tests rebuild the 2002 summary and detailed
   input-output tables published by Chamberlain Economics from BEA's 2002 make
   and use tables (fixtures in `tests/fixtures/2002/`).
3. **BEA's 2017 requirements.** BEA's published 2017 industry-by-industry total
   requirements table, 402 by 402, is reproduced to a maximum absolute
   difference of 7.0e-4 under BEA's published scrap convention (`iotables
   check`).
4. **Tax Foundation Working Paper No. 6.** The WP6 price impacts are
   reproduced to machine precision under the `wp6` formulation, in which each
   industry's tax is spread over its intermediate sales:
   t_i = tax_i / (industry i's intermediate sales), A_hat = diag(1 + t) A,
   p_hat = (I - A_hat')^-1 v. That formulation exists only to reproduce WP6 and
   has no burden identity; the default is the textbook model above.

## Data sources

All files are public and need no key. The URLs, verified on 2026-11-22, are
recorded in `src/iotables/sources.py`.

- BEA 2017 benchmark detail make and use tables, after and before redefinitions
  (each workbook holds the 2007, 2012 and 2017 benchmarks; `--year` chooses one):
  - https://apps.bea.gov/industry/xls/io-annual/IOMake_After_Redefinitions_2017_Detail.xlsx
  - https://apps.bea.gov/industry/xls/io-annual/IOUse_After_Redefinitions_PRO_2017_Detail.xlsx
  - https://apps.bea.gov/industry/xls/io-annual/IOMake_Before_Redefinitions_2017_Detail.xlsx
  - https://apps.bea.gov/industry/xls/io-annual/IOUse_Before_Redefinitions_PRO_2017_Detail.xlsx
- BEA 2017 industry-by-industry total requirements, for `iotables check`:
  https://apps.bea.gov/industry/xls/io-annual/IxI_TR_2017_PRO_DET.xlsx
- BEA PCE bridge, personal consumption expenditures by commodity in producers'
  and purchasers' prices:
  https://apps.bea.gov/industry/xls/underlying-estimates/PCEBridge_2017_DET.xlsx
- EIA Monthly Energy Review, table 11.1, carbon dioxide emissions from energy
  consumption by source, for the carbon preset:
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

## Roadmap

Phase 2 adds BEA's annual summary-level tables (71 industries, 1997 onward),
which BEA serves through its API; they need a free BEA API key, read from the
`BEA_API_KEY` environment variable.

## Package layout

```
src/iotables/
  sources.py    URLs of the BEA and EIA files; data/raw and data/output
  download.py   cached downloads with provenance records
  parse.py      BEA workbooks -> MakeTable, UseTable
  square.py     make and use -> SquareIOTable (Z, F, V, y); Excel and CSV export
  validate.py   identity checks; comparison with BEA's requirements table
  shocks.py     shock types and the carbon-price preset
  bridge.py     BEA's PCE bridge
  leontief.py   PriceModel -> PriceResult
  cli.py        iotables build, check and run
tests/          pytest suite and fixtures
docs/           reference papers and the design document
```
