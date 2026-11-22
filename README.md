# iotables

A Python toolkit that turns the Bureau of Economic Analysis (BEA) make and use
tables into a square industry-by-industry input-output table, and uses that table
to trace a tax or cost increase through the economy to the prices consumers pay.

You describe a tax: on an industry, on a commodity, on sales from one industry to
another, or on a component of value added, in dollars or as a rate. The model
answers two questions: how much does every price in the economy change, and who
pays, by consumer spending category and by component of final demand. A carbon
price is a built-in preset of that general model.

Everything runs from BEA's published files. No spreadsheets, no credentials, and
every number traces to a downloaded file, a date and a formula. The method is the
one described in the Chamberlain Economics methodology paper (2011) and applied in
Tax Foundation Working Paper No. 6 (2009); see [References](#references). This
release covers BEA's 2017 benchmark tables at the detail level (402 industries).

## Quick start

Python 3.10 or later. From a clone of this repository:

```
pip install -e ".[dev]"
iotables build
iotables run --carbon 50 --emissions-year 2024
```

`build` downloads BEA's 2017 tables (about 15 MB, cached under `data/raw/`) and
writes the square table to `data/output/`. `run` prices a $50 per ton carbon
tax and writes the results next to it. Both print a summary as they go.

The runtime dependencies are pandas, numpy, openpyxl and requests. `pytest` runs
the test suite; `pytest -m "not network"` skips the tests that need the
downloaded files.

## The three commands

### `iotables build`

Builds the 402-industry table and writes
`data/output/us_io_2017_detail_after_bea.xlsx` plus a folder of CSV files with
the same name (Z, F, V, y, market shares, labels and metadata). The spreadsheet
has the conventional layout: industries down the rows, then three value-added
rows and total output; industries across the columns, then the final-demand
columns and total output. It also prints the accounting-identity residuals and
the industries whose output or operating surplus differ most from BEA's figures.

Options: `--year 2017|2012|2007`, `--redefinitions after|before`,
`--scrap bea|redistribute|keep` (see [Scrap and used goods](#scrap-and-used-goods)),
`--scrap-codes`, `--out DIR`, `--make PATH --use PATH` to read local BEA
workbooks, and `--force` to download again.

### `iotables check`

Builds the table under BEA's own scrap convention and compares its total
requirements, (I - A)^-1, with BEA's published 2017 industry-by-industry
requirements table, cell by cell. It exits with status 1 if any cell differs by
more than `--tol` (default 1e-3). On the 2017 data the largest difference is
7.0e-4.

### `iotables run`

Applies one or more taxes and reports the resulting price changes and burdens.
Taxes are given with `--shock`, which can be repeated, or with the carbon preset.

| Spec | Meaning |
| --- | --- |
| `industry:CODE:dollars=X` | $X million of tax on industry CODE |
| `industry:CODE:rate=R` | a tax of R per dollar of the industry's output |
| `commodity:CODE:dollars=X` | $X million on commodity CODE, shared among the industries that make it by market share |
| `commodity:CODE:rate=R` | R times the commodity's output, shared the same way |
| `flow:SELLER:BUYER:rate=R` | a tax of R per dollar of BUYER's purchases from SELLER |
| `va:COMPONENT:rate=R[:industries=A,B]` | R times value-added row COMPONENT (V00100 compensation, V00200 taxes on production and imports, V00300 gross operating surplus), for every industry or those listed |

Dollars are millions; rates are fractions (0.05 means 5 percent). Shocks add.

`--carbon PRICE --emissions-year YEAR` builds the shocks for a carbon tax of
PRICE dollars per metric ton of CO2. It reads EIA's energy-related CO2 emissions
by fuel for that year and taxes each fuel where it enters the economy: coal at
coal mining (212100), natural gas and petroleum at oil and gas extraction
(211000). EIA counts emissions from domestic consumption, so this approximates an
upstream tax with a border adjustment.

Other options: `--formulation wp6` (see [Validation](#validation)), `--no-pce` to
skip the consumer-category step, `--table PATH.xlsx` to reuse a table that
`build` wrote, and every `build` option.

The run writes six files to `--out` (default `data/output`):

- `industry_prices.csv`: price change for each industry.
- `commodity_prices.csv`: price change for each commodity, in producers' prices.
- `pce_prices.csv`: price change, base spending and dollar burden for each of
  the 212 personal consumption categories, in purchasers' prices.
- `burden_by_final_demand.csv`: base spending and burden for each of BEA's 20
  final-demand columns.
- `summary.json`: total tax, the burden on final demand, the PCE burden and its
  share of the tax, and the run's notes.
- `shocks.json`: every shock that was run, including those built by the preset.

## Two examples

A $50 per ton carbon tax on 2024 emissions, run on 2026-11-22:

```
iotables run --carbon 50 --emissions-year 2024
```

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

That tax collects $23.9 billion, raises the price of gasoline and other motor
fuel by 2.7 percent, and personal consumption bears 68 percent of it.

## How to read the results

- All dollar figures are millions of dollars of the table's year, 2017. The
  carbon preset places the emissions year's tax on the 2017 economy as it
  stands; the table is not inflated.
- A price change of 0.05 is 5 percent. The burden on a spending category is its
  base spending times its price change.
- Under the default formulation the burdens add up to the tax: the total price
  increase on final demand equals the tax collected, and `identity_residual` in
  `summary.json` is that total minus the tax, zero to rounding.
- Imports enter BEA's use table as a negative final-demand column, so the
  imports column carries a negative burden and the positive components
  (personal consumption, investment, government, exports) together bear more
  than the tax. In the carbon example imports carry -$202.9 billion and exports
  $115.7 billion. `pce_share_of_burden` is relative to the tax, which is why it
  can approach 1; consumers bear about half of the burden on the positive
  components in that example.
- The PCE burden is computed in purchasers' prices from BEA's PCE bridge, so it
  differs slightly from the PCE column of final demand, which is in producers'
  prices. Two bridge lines, personal remittances in kind to nonresidents (149)
  and expenditures in the United States by nonresidents (338), carry negative
  base spending by BEA's design and a burden of zero.
- `data/raw` and `data/output` are relative to the directory the command runs in.

## Using it from Python

Everything the commands do is available as functions and classes. The square
table and all results are pandas objects.

```python
from iotables import PriceModel, build_square_table, load_bea_tables, load_pce_bridge, shocks

make, use = load_bea_tables("detail", 2017, "after")   # cached download and parse
sq = build_square_table(make, use)                      # scrap="bea", the default
sq.Z                                                    # 402 x 402 intermediate flows, a DataFrame
sq.check_identities()                                   # raises ValueError if an identity fails
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

`sq` is a `SquareIOTable` with the frames `Z` (intermediate flows, seller rows
and buyer columns), `F` (final demand), `V` (value added) and the Series `y`
(industry output). `result` is a `PriceResult` holding the same frames and
summary that `iotables run` writes.

## Method

BEA publishes a make table M (what each industry produces, industries by
commodities) and a use table (what each industry buys, U, commodities by
industries; what goes to final demand, D; and each industry's value added), in
producers' prices and millions of dollars. The package converts them to an
industry-by-industry table on the assumption that each commodity is supplied by
the industries that make it in fixed market shares (Eurostat's Model D, which
BEA calls the industry-technology assumption). With q the commodity output:

```
N = M diag(q)^-1     market shares: industry i's share of commodity c
Z = N U              intermediate flows, industries x industries
F = N D              final demand, industries x final-demand columns
y = Z 1 + F 1        industry output, the row totals of [Z | F]
```

Compensation and taxes on production come from the use table and gross operating
surplus is the balancing item, so each industry's inputs plus value added equal
its output. Noncomparable imports and BEA's rest-of-world adjustment, which no
domestic industry produces, are removed first.

The price model is the Leontief cost-push model on that table, with base-year
prices equal to 1:

```
A     = Z diag(y)^-1                input from industry i per dollar of industry j's output
v     = value added / y             value added per dollar of output
A_hat = A * (1 + T)                 T holds taxes on intermediate sales, if any
p_hat = (I - A_hat')^-1 (v + tau)   tau: the tax per dollar of each industry's output
```

`p_hat - 1` is each industry's price change. Commodity price changes are the
market-share-weighted averages of the industry price changes, and BEA's PCE
bridge carries them to the 212 personal consumption categories in purchasers'
prices, with trade and transportation margins priced at the wholesale, retail and
transportation industries' own price changes.

## Scrap and used goods

Two BEA commodities do not fit the market-share assumption: scrap (S00401), a
byproduct of many industries, and used and secondhand goods (S00402), which have
no producer. `--scrap` chooses how they are handled.

- `bea` (default): the nonscrap-ratio method of BEA's handbook. Scrap and used
  goods leave the tables and each industry's market shares are scaled by the
  share of its output that is not scrap, so industry output stays equal to
  BEA's. Purchases of scrap and used goods fall into gross operating surplus.
  Scrap is a byproduct whose price is not the cost-plus price of the industries
  that generate it, so this is the right treatment for a cost-push price model.
- `redistribute`: the rule of the 2011 methodology paper. Each column's purchases
  of scrap and used goods are spread over its other purchases in proportion to
  their values. Industry output then differs from BEA's by the amounts moved;
  `build` prints the largest gaps.
- `keep`: treats scrap and used goods as ordinary commodities. It works only
  where both have producers, such as the 2002 summary table; the 2017 tables
  need `bea` or `redistribute`.

BEA's own published requirements tables keep scrap as an ordinary commodity and
remove only used goods. `iotables check` uses that convention
(`--scrap-codes S00402`) so that the comparison is like for like.

## Validation

The test suite checks the accounting identities of every table it builds and
reproduces four published results: BEA's own three-industry handbook example,
the 2002 Chamberlain Economics summary and detailed tables, BEA's published 2017
industry-by-industry requirements table (to 7.0e-4), and the price impacts of
Tax Foundation Working Paper No. 6 under `--formulation wp6`, which spreads each
industry's tax over its intermediate sales as that paper did.

## Data sources

All files are public and need no key. The URLs are recorded in
`src/iotables/sources.py`.

- BEA 2017 benchmark detail make and use tables, after and before redefinitions
  (each workbook also holds the 2007 and 2012 benchmarks):
  - https://apps.bea.gov/industry/xls/io-annual/IOMake_After_Redefinitions_2017_Detail.xlsx
  - https://apps.bea.gov/industry/xls/io-annual/IOUse_After_Redefinitions_PRO_2017_Detail.xlsx
  - https://apps.bea.gov/industry/xls/io-annual/IOMake_Before_Redefinitions_2017_Detail.xlsx
  - https://apps.bea.gov/industry/xls/io-annual/IOUse_Before_Redefinitions_PRO_2017_Detail.xlsx
- BEA 2017 industry-by-industry total requirements, for `iotables check`:
  https://apps.bea.gov/industry/xls/io-annual/IxI_TR_2017_PRO_DET.xlsx
- BEA PCE bridge, personal consumption by commodity in producers' and
  purchasers' prices:
  https://apps.bea.gov/industry/xls/underlying-estimates/PCEBridge_2017_DET.xlsx
- EIA Monthly Energy Review, table 11.1, CO2 emissions from energy consumption
  by source, for the carbon preset:
  https://www.eia.gov/totalenergy/data/browser/csv.php?tbl=T11.01

Downloads are cached in `data/raw/` with a record of each file's URL, SHA-256
hash and download time.

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
which BEA serves through its API. They need a free BEA API key, read from the
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
