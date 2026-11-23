# Single-script version of the model: design

Date: 2026-11-22

## Intent

One Python file that an economist can open in an IDE and run cell by cell to
build the square input-output table and trace any cost shock through the
economy to consumer prices, with every formula visible in the order the method
is explained. The package spreads about 30 lines of linear algebra across nine
modules; the script puts them on one page.

## Goals

- A single file, `io_model.py`, at the repository root, in `# %%` cells.
- A configuration cell at the top; the rest runs top to bottom without edits.
- Self-contained: imports pandas, numpy, openpyxl (to read BEA's workbooks) and
  requests only. No import from `iotables`.
- A general cost-shock model. Any increase in costs can be entered: a tax, a
  tariff or other rise in an import price, a rise in the price of a domestic
  input, a rise in wages or another component of value added, or a given rise in
  one industry's price. Carbon pricing is one optional example, off by default.
- Domestic and imported inputs are separated with BEA's import matrix, so a
  shock to domestic producers moves domestic prices only and a tariff enters
  through the imports that industries and final users buy.
- Every intermediate result is a named pandas object left in memory, and each
  cell prints a short summary of what it produced.
- Results written as CSV files only.

## Non-goals

- No Excel output of any kind.
- No classes, command line, or packaging.
- No detailed error handling for malformed inputs; the script assumes BEA's and
  EIA's files look as they do today.
- No behavioural responses: domestic producers do not raise prices to match a
  tariff, buyers do not substitute, quantities do not change. (A matching
  domestic price rise can be entered by hand as a `"price"` shock.)
- The package is not changed or removed.

## Anti-goals

- Logic hidden behind helper functions. Only two helpers are allowed: download
  and cache a file, and read a BEA worksheet into a DataFrame.
- A configuration or vocabulary built around carbon taxes.

## Approaches

1. Self-contained script with the math inline (chosen). Where it overlaps the
   package, a test ties the two together.
2. A script of cells that call the package. Short, but the formulas stay hidden.
   Rejected: it does not meet the intent.
3. A Jupyter notebook. Rejected: a plain `.py` file with cells runs the same way
   in the IDE, diffs cleanly, and needs no notebook server.

For imports: (a) split the use table with BEA's import matrix (chosen; the
matrix exists for the 2017 benchmark at the detail level, same layout as the
use table); (b) keep the combined table and approximate a tariff as a cost on
the domestic industry (rejected: it prices the wrong goods).

## Design

Configuration cell:

```python
YEAR = 2017
REDEFINITIONS = "after"        # "after" or "before"
SCRAP = "bea"                  # "bea", "redistribute" or "keep"
IMPORTS = "split"              # "split": domestic and imported inputs separate
                               # "combined": BEA's standard table, as the package does
FORMULATION = "output"         # "output" or "wp6"
OUTPUT_DIR = "data/output"

# Cost shocks. Each is (kind, where, unit, amount). Shocks add.
#   ("import",    "331110",            "rate",    0.25)    25% tariff on imports of a commodity
#   ("industry",  "211000",            "dollars", 50_000)  $ millions of added cost
#   ("industry",  "211000",            "rate",    0.10)    10% of the industry's output
#   ("industry",  "211000",            "price",   0.20)    the industry's price rises exactly 20%
#   ("commodity", "324110",            "rate",    0.05)    shared among producers by market share
#   ("flow",      ("221100","331110"), "rate",    0.10)    price of seller's sales to buyer
#   ("value_added", "V00100",          "rate",    0.01)    1% rise in compensation
SHOCKS = [
    ("import", "331110", "rate", 0.25),
]

# Optional example: a carbon price, converted to shocks from EIA data.
CARBON_PRICE = None            # $ per metric ton of CO2, or None
EMISSIONS_YEAR = 2024
```

The model with imports split. U = U_d + U_m, D = D_d + D_m, where U_m and D_m
are BEA's import matrix (commodities by industries, and by final uses):

```
N   = M diag(q)^-1                 market shares
Z   = N U_d                        domestic intermediate flows, industry x industry
F   = N D_d                        domestic final demand
y   = Z 1 + F 1                    industry output
A   = Z diag(y)^-1                 domestic input per dollar of output
B   = U_m diag(y)^-1               imported commodity c per dollar of industry j's output
v   = value added / y
p   = (I - A_hat')^-1 (v + tau + B' p_m)
```

p_m is the vector of import prices by commodity, 1 in the base year; a tariff
of 25 percent on commodity c sets p_m[c] = 1.25. The price of commodity c to a
buyer is the buyer's domestic share times the domestic commodity price plus its
import share times p_m[c]; that applies to industries (through A and B) and to
final users, including each PCE category.

A `"price"` shock on industry k is converted to the cost shock that produces
it: tau_k = target / L[k,k] with L = (I - A_hat')^-1 (a small linear solve when
several prices are fixed).

Identity checked in every run: the total burden on final demand, domestic and
imported, equals the total dollars of the shocks (tariff revenue is the rate
times all imports of the commodity, intermediate and final).

With `IMPORTS = "combined"` the script reproduces the package.

Cells, in order:

1. Configuration.
2. Download and cache the BEA files (and the EIA file if `CARBON_PRICE` is set).
3. Read the make table M, the use table (U, final demand D, value added) and the
   import matrix (U_m, D_m).
4. Scrap and used goods, by the `SCRAP` setting.
5. Market shares.
6. Square table: Z, F, y, B, value added with operating surplus as the
   balancing item.
7. Accounting identities.
8. Comparison with BEA's published industry-by-industry total requirements
   (always on the combined table under BEA's scrap convention, like for like).
9. Turn `SHOCKS` (plus the carbon example, if set) into tau, T and p_m.
10. Price model; burden on final demand and its identity with the total shock.
11. Commodity prices and the PCE bridge to 212 consumer categories.
12. Results: printed tables, then CSV files: the square table (Z, F, V, y, B,
    market shares, labels) and the results (industry prices, commodity prices,
    PCE prices, burden by final demand, summary, shocks).

Supporting files: `requirements.txt` with the four libraries; a comment at the
top of the script with the three commands to create the virtual environment.

## Tests

`tests/test_script.py`:

- With `IMPORTS = "combined"`: Z, y, price changes and PCE burdens equal the
  package's for the same shocks, and again with the carbon example on.
- With `IMPORTS = "split"`: accounting identities hold; industry output equals
  the make table's; the burden identity holds for a tariff, for a domestic
  shock and for both together; a tariff on a commodity nobody imports changes
  nothing; a hand-worked three-industry example with imports gives the expected
  prices.
- `"price"` shock: the target industry's price change equals the target, and the
  other prices equal those from solving the system with that industry's
  equation removed.

## Builder's calls and things to verify

- The import matrix is published before redefinitions only. For the
  after-redefinitions table, apply each cell's import share (import matrix cell
  over the before-redefinitions use cell) to the after-redefinitions use table.
  Verify that shares are constant along a commodity row, as BEA's construction
  implies; if so a row share is enough.
- What BEA puts in the import matrix's imports column and the noncomparable
  imports row, and how D_d is formed so that y still equals industry output.
- Scrap treatment applied consistently to U_d and U_m.
- The carbon example under the split: the same rate per ton on domestic and
  imported fuel (a domestic industry shock plus an import shock).
- Margins on imported consumer goods in the PCE bridge (assume the same margin
  rates as domestic goods of the same commodity).
- Variable names (prefer the symbols above), how much each cell prints, and
  whether the test runs the script with `runpy` or as a subprocess.

## Revisions after the first build (2026-11-22)

Decided after running the script end to end. Where these differ from the text
above, these hold.

- The script lives in its own self-contained folder, `script/`, with its
  `requirements.txt` and a short README. It downloads into `script/data/` and
  writes to `script/output/`.
- One method only. The `REDEFINITIONS`, `SCRAP` and `FORMULATION` settings are
  gone: the script uses BEA's before-redefinitions tables (the basis of the
  import matrix, which is then used exactly as published, with no mapping), the
  handbook nonscrap-ratio treatment, and the standard price model. `IMPORTS`
  remains, with `"split"` the default.
- The comparison with BEA's requirements table (cell 8) reads the
  after-redefinitions make and use tables itself, since that is the basis of
  BEA's published table.
- An industry's output of any removed commodity (scrap, and the rest-of-world
  adjustment that federal general government records) counts in its nonscrap
  ratio, so every industry's output equals BEA's to within rounding.
- The package holds the same method as its default and must give the same
  results: before redefinitions, imports split, `ImportTariff` and
  `IndustryPrice` shocks, PCE import shares, and the carbon example at one rate
  on domestic and imported fuel. `wp6`, `redistribute`, `keep` and
  after-redefinitions remain in the package as options. Tests require the
  script and the package to agree, in Python and through `iotables run`.
- Results are CSV only, including `summary.csv` and `shocks.csv`.
- The package is an importable module only. Its command line, its Excel export
  and its reading of a written table back in are removed; `SquareIOTable.to_csv`
  and `PriceResult.to_csv` write CSV files.
- The script is written to be taught from: about 280 lines, ten cells, each a
  short header with its formula and the code for it. Comments name the step;
  they do not justify or caveat. There is no shock list and no parser: cell 5
  sets `tau`, `tariff` and `fixed` directly. The `IMPORTS` switch, the carbon
  example and flow shocks are not in the script (the module has them). The
  comparison with BEA's table is the last cell, an appendix. Three helpers
  (download, read a table, read the bridge) sit in the setup cell.
- The module holds the script's method and nothing else, apart from the carbon
  example. Removed from it: combined imports (the import matrix is a required
  input), the `redistribute` and `keep` scrap treatments, after-redefinitions
  tables, the `wp6` formulation, flow shocks, and the tests and fixtures that
  reproduced the 2002 tables and the 2009 paper.
- One neutral vocabulary, "cost", in both. The model does not ask whether a
  cost comes from policy (a tax, a tariff) or from the economy (a world price,
  wages). Script: `c` (new cost per dollar of output), `import_price`,
  `total_cost`, cell 5 "The cost change". Module: `iotables.costs` with
  `IndustryCost`, `CommodityCost`, `ValueAddedCost`, `ImportPrice`,
  `IndustryPrice`; the result's summary has `total_cost` and
  `pce_share_of_cost`.
