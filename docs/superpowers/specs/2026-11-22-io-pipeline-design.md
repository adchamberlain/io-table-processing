# Design: square U.S. input-output tables and a general price pass-through model

Date: 2026-11-22
Status: approved by the project owner, 2026-11-22
Author: project design document, written with the project owner
Supersedes: the spreadsheet workflow in `docs/reference/IO_Methodology.pdf` (2011) and
`docs/reference/wp6.pdf` (2009).

## 1. Intent

Replace a hand-built Excel workflow with a Python package that anyone can run:

1. Fetch the latest BEA make and use tables.
2. Convert them into a clean, balanced, square industry-by-industry input-output
   table (intermediate flows, final demand, value added), held as pandas objects.
3. Run a Leontief price model on that table that answers: "if a tax or cost increase
   of X lands on some industry, commodity, transaction, or factor, how do prices change
   throughout the economy, and what do consumers end up paying by spending category?"

Carbon pricing (the WP6 application) is one preset of that general model, not the
model itself. The package will be open-sourced on GitHub.

## 2. Goals, non-goals, anti-goals

Goals
- One command rebuilds everything from BEA source files: `iotables build`.
- Output is a square n x n industry table that satisfies the accounting identities
  (row total = column total = industry output) to floating-point precision.
- Exact replication of the legacy results as tests: the 2002 summary and detailed
  tables, the WP6 price impacts, and BEA's own 2017 industry-by-industry requirements.
- A general shock interface: tax on an industry, on a commodity, on a specific
  buyer-seller flow, or on a value-added component; dollars or ad valorem.
- Results down to PCE (personal consumption) categories in purchasers' prices, with
  dollar burdens, plus burden split across final-demand components.
- Readable code a careful economist can audit against the methodology paper.

Non-goals (this round)
- Household distribution using CEX microdata (WP6 sections III.A to III.D). PCE
  categories are the hand-off point; a later project can add the PCE-to-CEX step.
- Quantity-side (demand-driven) multipliers, employment, RIMS II. The table supports
  them; we do not build them now.
- Regional tables, import matrices, tariffs, commodity-by-commodity tables.
- A GUI or web service.

Anti-goals (would make this a failure even if it "works")
- Hidden hard-coded row/column offsets or industry counts (the failure mode of an earlier attempt).
- Fuzzy name matching to align industries. Alignment is by BEA code, always.
- Silent fallbacks that fabricate data (an earlier attempt had `np.random` as a fallback).
- Results that cannot be traced to a BEA file, a date, and a formula.

## 3. Constraints

- Python 3.10+, pandas, numpy, openpyxl, requests. No heavier dependencies.
- Must run with no credentials for the 2017 benchmark detail tables (static URLs).
  Annual summary tables may require a free BEA API key; the key is read from the
  environment (`BEA_API_KEY`) or a git-ignored `.env`, never committed.
- Downloaded files are untrusted input: parse with pandas/openpyxl only; never
  execute anything from them; cache them under `data/raw/` with provenance.
- Everything in the final table must be derivable from the raw files plus this document.

## 4. Decisions already made

By the project owner
- Stop at PCE categories; no CEX microdata.
- The model is a general tax/cost pass-through model; carbon pricing is a preset.
- Default pass-through formulation: the textbook Leontief price model where the tax
  enters an industry's unit cost and every buyer pays the higher price. WP6's
  intermediate-sales-only variant is retained as an option for replication.
- Default scrap treatment: BEA's nonscrap-ratio method (`bea`, section 7.3). The
  methodology paper's proportional redistribution is kept as `redistribute` for
  replicating the 2002 detailed table. (Decided 2026-11-22 after the builder-check
  review quantified the distortion on 2017 data.)
- Two phases: Phase 1 is the 2017 benchmark detail tables (no credentials). Phase 2
  adds annual summary tables through the BEA API once a key exists.
- Move entirely out of spreadsheets; pandas objects are the primary representation,
  Excel/CSV are exports.
- Daily entries in a private working log (not in the repository).

Design calls (flagged; the project owner can override)
- Package name `iotables`, src layout, CLI `iotables`.
- Default input tables: BEA "after redefinitions" (BEA's 2002 "standard" tables were
  after redefinitions; the 2002 legacy work used them). Before/after is a parameter.
- Scrap treatment: three modes are implemented (section 7.3) because each is needed
  to replicate one validation target. Default `bea` (project owner's decision, above).
- Commodity price changes are computed from the producers'-price market-share matrix;
  trade and transport margins are handled at the PCE bridge stage, not by adjusting
  the make table as WP6 did. (Section 8.5 explains why this is cleaner.)
- Results are reported in the table's own year and dollars. No GDP-growth inflation
  of the table (WP6 inflated 2002 to 2006); percent price changes are scale-free, and
  a user who wants a different dollar year scales the burden columns.

## 5. Architecture

Four stages, one module each, each independently testable, each returning plain
pandas/dataclass objects:

```
download.py   BEA/EIA source files  ->  data/raw/<source>/<file>  (+ provenance json)
parse.py      raw xlsx              ->  MakeTable, UseTable (clean, code-indexed)
square.py     MakeTable + UseTable  ->  SquareIOTable (Z, F, V, y, N, labels, meta)
leontief.py   SquareIOTable + shocks + PCEBridge -> PriceResult
cli.py        `iotables build`, `iotables run`
```

Supporting modules: `sources.py` (manifest of URLs and API table lookups),
`shocks.py` (shock specification types and converters, incl. the carbon preset),
`bridge.py` (PCE bridge parsing and aggregation), `validate.py` (identity checks and
comparison helpers used by tests and by the CLI's `--check` flag).

### 5.1 Data objects

`MakeTable`
- `values`: DataFrame, index = industry codes (str), columns = commodity codes (str),
  millions of dollars, NaN -> 0.
- `industry_labels`, `commodity_labels`: Series code -> description.
- `industry_output`: Series (BEA column T008), kept for checks.
- `meta`: year, level, redefinitions, source file, sha256, download date.

`UseTable`
- `intermediate`: DataFrame commodities x industries (all commodity rows incl.
  S00401 scrap, S00402 used, S00300 noncomparable imports, S00900 ROW adjustment).
- `final_demand`: DataFrame commodities x final-demand columns (codes F01000 ...),
  excluding BEA's total columns (T001 total intermediate, total final uses, T007).
- `value_added`: DataFrame 3 x industries (V00100, V00200, V00300).
- `industry_output`: Series (row T008). `commodity_output`: Series (column T007).
- labels and meta as above.

`SquareIOTable`
- `Z`: DataFrame n x n, industries x industries (seller rows, buyer columns).
- `F`: DataFrame n x k, industries x final-demand columns.
- `V`: DataFrame 3 x n, value-added components by buyer industry.
- `y`: Series n, total industry output (row totals of [Z | F]).
- `N`: DataFrame n x m, the market-share matrix actually used (needed later to map
  industry prices to commodity prices).
- `labels`: industry, final-demand and commodity descriptions.
- `meta`: everything from the inputs plus scrap mode, dropped rows, diagnostics.
- Methods: `check_identities()`, `to_frame()` (legacy layout: code, description,
  n industry columns, k final-demand columns, total; rows: n industries, V00100,
  V00200, V00300, total), `to_excel(path)`, `to_csv(dir)`, `to_parquet(dir)`.

`PCEBridge`: DataFrame with one row per (NIPA line, commodity): producers' value,
transportation costs, wholesale margin, retail margin, purchasers' value; plus
labels. Method `aggregate_to(level_crosswalk)`.

`PriceResult`: industry_prices, commodity_prices, pce_prices, burden_by_final_demand,
summary (total tax, total burden, checks), and the shock list that produced it.

### 5.2 Public API sketch

```python
from iotables import load_bea_tables, build_square_table, load_pce_bridge
from iotables import PriceModel, shocks

tables = load_bea_tables(level="detail", year=2017)            # cached download + parse
sq = build_square_table(tables, scrap="redistribute")           # SquareIOTable
sq.check_identities()                                            # raises if violated
sq.to_excel("data/output/us_io_2017_detail.xlsx")

model = PriceModel(sq, pce_bridge=load_pce_bridge(level="detail", year=2017))
result = model.run([
    shocks.IndustryTax("211000", dollars=50_000),       # $50B on oil & gas extraction
    shocks.CommodityTax("324110", rate=0.05),           # 5% ad valorem on refined petroleum
    shocks.FlowTax(seller="221100", buyer="331110", rate=0.10),   # electricity bought by steel
    shocks.ValueAddedTax("V00100", rate=0.01),          # 1% payroll tax, all industries
])
result.pce_prices.head()
```

Carbon preset:
```python
result = model.run(shocks.carbon_price(dollars_per_ton_co2=50, emissions_year=2024,
                                       coverage="upstream"))
```

### 5.3 CLI

- `iotables build [--level detail] [--year 2017|2012|2007|latest] [--redefinitions after|before] [--scrap bea|redistribute|keep] [--scrap-codes S00401,S00402] [--out data/output] [--make PATH --use PATH]`
  Output name `us_io_<year>_<level>_<redefinitions>_<scrap>.xlsx`, with a `_scrap-<codes>` suffix when the scrap codes differ from the library default.
  (`--level summary` arrives with Phase 2, section 6.1.)
- `iotables run --table data/output/... --shock 'industry:211000:dollars=50000' ... [--carbon 50 --emissions-year 2024]`
- `iotables check` runs identities and, when the BEA requirements file is present,
  the comparison in section 9.

## 6. Data sources

### 6.1 BEA make and use tables

2017 benchmark, 402 industries, static URLs verified 2026-11-22 (no key):

```
https://apps.bea.gov/industry/xls/io-annual/IOMake_After_Redefinitions_2017_Detail.xlsx
https://apps.bea.gov/industry/xls/io-annual/IOUse_After_Redefinitions_PRO_2017_Detail.xlsx
https://apps.bea.gov/industry/xls/io-annual/IOMake_Before_Redefinitions_2017_Detail.xlsx
https://apps.bea.gov/industry/xls/io-annual/IOUse_Before_Redefinitions_PRO_2017_Detail.xlsx
https://apps.bea.gov/industry/xls/io-annual/IxI_TR_2017_PRO_DET.xlsx          (validation)
https://apps.bea.gov/industry/xls/underlying-estimates/PCEBridge_2017_DET.xlsx
```

(Corrected 2026-11-22 during implementation: the shorter `..._DET.xlsx` make/use
names also resolve, but serve a 2021-vintage workbook holding only the 2007 and
2012 benchmarks. The `_2017_Detail.xlsx` files, dated May 2024, hold 2017.)

Workbook layout (all of the above): sheets `NAICS Codes`, `2007`, `2012`, `2017`.
In a year sheet: rows 1-3 title/units/source, row 5 descriptions, row 6 codes, data
from row 7; column A code, column B description. Codes can arrive as int or str;
always coerce to stripped str. Parsing locates the header by content (the cell
reading "Code" in column A with "Industry Description"/"Commodity Description" in
column B), never by fixed offsets, and stops at the first all-empty row.

Make (2017): 402 industry rows + T007 total row; 402 commodity columns (398
ordinary + S00401, S00402, S00300, S00900) + T008. Four industry codes have no
commodity of their own (331314, S00101, S00201, S00202), so the commodity and
industry sets differ and the make table is 402 x 402 only by coincidence. Use
(2017): the same 402 commodity rows + T005, V00100, V00200, V00300, T006, T008;
402 industry columns + T001 + 20 final-demand columns
(F01000, F02E00, F02N00, F02R00, F02S00, F03000, F04000, F05000, F06C00, F06E00,
F06N00, F06S00, F07C00, F07E00, F07N00, F07S00, F10C00, F10E00, F10N00, F10S00)
+ "Total Final Uses (GDP)" + "Total Commodity Output" (last two have no code).

Annual summary tables (71 industries, 1997 to latest): static file names not found;
served through BEA's interactive app and the BEA API (dataset `InputOutput`,
parameters `TableID`, `Year`). This is PHASE 2 and is built only once a
`BEA_API_KEY` is available, so that the code is written against recorded real
responses (committed as fixtures) and tested. Design: `BeaApiSource` discovers
TableIDs at runtime with `GetParameterValues` and selects by description regex
(e.g. "Make Table.*After Redefinitions"), so no IDs are hard-coded; the response
(RowCode, ColCode, DataValue) is pivoted into the same MakeTable/UseTable objects;
a per-level code map normalizes summary codes (value-added rows, government,
scrap) onto the detail-style codes the rest of the package uses. Phase 1 ships
`--level detail` with years 2007, 2012, 2017 from the static workbooks ("latest"
means the newest sheet in the workbook). If the summary static files are located
later, they join the manifest and Phase 2 needs no key.

API facts verified with a registered key on 2026-11-22 (saved to
`docs/reference/bea_api_inputoutput_params_2026-11-22.json`): the InputOutput
dataset has ten tables: 258/259 "The Use of Commodities by Industries" (Sector /
Summary), 261/262 "The Domestic Supply of Commodities by Industries" (Sector /
Summary; this is the make table under BEA's supply-use naming), and 56-61 total
requirements (industry-by-commodity, commodity-by-commodity, industry-by-industry;
Sector / Summary). Years 1997-2025. No detail level, and no before/after
redefinitions label; Phase 2 must establish valuation and redefinition status by
comparing the 2017 summary response against the 2017 detail workbook aggregated
with the NAICS crosswalk.

Local files: `--make PATH --use PATH` bypasses download and accepts only the current
BEA workbook layout described above. The 2002 regression tests do not go through
this path; they load CSV fixtures directly (section 9).

### 6.2 PCE bridge

`PCEBridge_2017_DET.xlsx`: sheets `Data Layout`, `NAICS Codes`, `PCE Categories`,
`2007`, `2012`, `2017`. Columns: NIPA Line, PCE Category, Commodity Code, Commodity
Description, Producers' Value, Transportation Costs, Wholesale (margin), Retail
(margin), Purchasers' Value, Year. 2017 sheet: 212 NIPA lines, 259 commodity codes,
~700 rows. Some bridge rows reference non-industry commodities (S00401 scrap, e.g.
"Used autos" has negative scrap) and margins-only commodities; treatment in 8.5.

For a summary-level table, the detail bridge is aggregated to summary commodities
using the `NAICS Codes` crosswalk in the same workbook (2017 shares applied to the
chosen year), unless a bridge for that level/year is available.

### 6.3 Emissions (carbon preset only)

EIA Monthly Energy Review table 11.1, CSV, no key:
`https://www.eia.gov/totalenergy/data/browser/csv.php?tbl=T11.01`.
Series: CKTCEUS coal, NNTCEUS natural gas, PMTCEUS petroleum, TETCEUS total, million
metric tons CO2; annual values have `YYYYMM` ending in `13`. Latest year 2025.

## 7. Building the square table

Notation: M make (industries x commodities), U use intermediate (commodities x
industries), D use final demand (commodities x final-demand columns), q commodity
output (make column totals), g industry output (BEA T008).

### 7.1 Alignment and cleaning
- Industry set = make rows = use columns, matched by code; assert identical sets
  (order taken from the make table). Commodity set = make columns = use rows, by code.
- NaN -> 0. Keep negative entries (inventory change, imports, used-goods sales).
- The methodology paper's "recode alphabetic codes" step is unnecessary: alignment is
  by label, never by sort order. Codes stay strings.

### 7.2 Rows removed
Drop S00300 noncomparable imports and S00900 rest-of-world adjustment from U and D
(no domestic industry produces them). Drop the matching make columns (S00300 is all
zero; S00900 has one nonzero entry, $3.5B in 2017, which is noted in diagnostics).

### 7.3 Scrap and used/secondhand goods (S00401, S00402): three modes

What the original 2002 workbooks did (verified 2026-11-22):
- 2002 detailed table: scrap AND used goods were merged proportionally into the other
  commodity rows in EVERY column, final-demand columns included. Proof: the
  Derivation Model's PCE column sums to 7,534,494.4, which equals BEA's raw PCE
  column (7,498,829.3) minus noncomparable imports (53,186.4) minus the ROW
  adjustment (-88,851.5), i.e. with scrap (-4,622.7) and used goods (+72,968.6)
  still inside it. The scrap column was dropped from the make table.
- 2002 summary table: BEA then published one combined commodity, S004 "Scrap, used
  and secondhand goods". The 2002 summary table kept it as an ordinary commodity in
  both M (133 x 134) and U; no redistribution.

What the same rule does to the 2017 detail table (builder-check measurements on a
2017 copy of the tables): used goods now carry large offsetting final-demand transfers (PCE
+$94.3B, equipment investment -$116.1B, S&L equipment -$14.5B) with zero make
output, so redistributing them inside final-demand columns shrinks equipment
producers' row totals by up to 31% versus BEA's industry output (106 of 402
industries off by more than 1%, 49 by more than 5%), turns gross operating surplus
negative for 18 industries (BEA: 1), and mixes signs in the inventory and import
columns. In aggregate the gap is only -0.01%, which is why it looks small. On the
intermediate side, steel's scrap purchases are 43% of its other inputs, so
redistribution inflates its apparent exposure to every other supplier by 43%.

Modes:

`bea` (default; BEA manual ch. 12 nonscrap-ratio method)
- Drop S00401 and S00402 rows from U and D, and the matching make columns.
- Nonscrap ratio per industry r_i = (g_i − s_i) / g_i. Market shares
  N = M q_hat^-1 computed without the scrap column, then each row divided by r_i
  (BEA's W = (I - p_hat)^-1 D). Industry output is preserved exactly (y = g).
  Scrap and used-goods purchases leave the intermediate block and land in gross
  operating surplus; used-goods transfers in final demand are not attributed to any
  producer. Columns of N then sum to slightly more than 1; that is intended.
- Relation to BEA's published tables (established 2026-11-22 during
  implementation): BEA's published 2017 industry-by-industry total requirements
  table does not apply the handbook's scrap adjustment. It keeps scrap (S00401) as
  an ordinary commodity and removes only used and secondhand goods (S00402), on the
  after-redefinitions tables. The pipeline reproduces that table to 7e-4 (rounding
  in the published inputs) with `scrap="bea", scrap_codes=("S00402",)`; with the
  default two-code treatment the largest difference is 0.116, in rows of the state
  and local government industry, which generates 38% of scrap, against scrap-buying
  industries (steel, secondary aluminum). The default keeps the handbook treatment
  because scrap is a byproduct whose price is not the cost-plus price of the
  industries that generate it, which matters for a cost-push price model; the
  published-table convention is available by argument and is what `iotables check`
  uses. Before-redefinitions inputs do not reproduce the published table (0.279).

`redistribute` (legacy; methodology paper; needed for the 2002 detailed target)
- For each column of U and D separately, add the column's scrap + used value to the
  remaining commodity rows in proportion to those rows' values in that column; then
  drop the two rows. Columns whose remaining rows sum to zero keep nothing (log it).
- Drop S00401 and S00402 from the make columns. y is the row total; y differs from
  g by the redistributed amounts (see above), and the gap lands in gross operating
  surplus. The CLI prints a warning with the largest per-industry gaps.

`keep` (needed for the 2002 summary target)
- Treat S00401/S00402 (or the combined summary-level S004) as ordinary commodities.

In every mode S00300 and S00900 are dropped (7.2) and all moved or dropped amounts
are recorded in `meta["diagnostics"]`.

### 7.4 Transformation (Eurostat Model D, fixed product sales structure)
```
N = M * diag(q)^-1        industries x commodities, columns sum to 1
Z = N @ U                 industries x industries
F = N @ D                 industries x final-demand columns
y = Z.sum(axis=1) + F.sum(axis=1)
```
Commodities with q = 0 get a zero column in N (and must have zero use; assert).

### 7.5 Value added and balancing
```
V00100, V00200 = taken from the use table (by buyer industry)
V00300 (gross operating surplus) = y - Z.sum(axis=0) - V00100 - V00200
```
Diagnostics: V00300 - BEA's V00300, and y - g, per industry and in total. Expected:
in `bea` mode y - g is zero to rounding and V00300 differs from BEA's by each
industry's scrap and used-goods purchases plus the small nonscrap-ratio markup; in
`redistribute` mode y - g can reach tens of percent for equipment producers (7.3).
The CLI prints the largest ten either way.

### 7.6 Output layout
`to_frame()` reproduces the legacy layout exactly (section 5.1) so the result opens
like the 2002 tables. Codes and descriptions are both carried. Units: millions of
dollars.

## 8. The price model

Let n industries, Z, F, V, y from the square table. Base-year prices are 1.

### 8.1 Baseline
```
A = Z @ diag(y)^-1          technical coefficients (input i per $ of output j)
v = V.sum(axis=0) / y       value added per $ of output
p = (I - A')^-1 v           = 1 for every industry (assert, tolerance 1e-9)
```
(WP6 writes this with row-normalized A and a division by Y; it is the same thing by
a similarity transform. The code uses the column form.)

### 8.2 Shock specification
A shock is converted to one or both of:
- `tau`: n-vector, added cost per dollar of industry output (output taxes).
- `T`: n x n matrix of per-transaction ad valorem rates on intermediate purchases
  (T[i, j] = rate on j's purchases from i).

Types and conversions (dollars in millions, rates as fractions):
- `IndustryTax(code, dollars | rate)`: tau_i += dollars / y_i, or tau_i += rate.
- `CommodityTax(code, dollars | rate)`: allocate to producing industries by market
  share column N[:, c]: dollars_i = N[i, c] * (dollars or rate * q_c); then as above.
- `FlowTax(seller, buyer, rate)`: T[seller, buyer] += rate. (An input tax levied on
  the buyer; the seller's price to other buyers is unchanged.)
- `ValueAddedTax(component, rate, industries=None)`: tau_j += rate * V[component, j] / y_j.
- `carbon_price(dollars_per_ton_co2, emissions_year, coverage="upstream")`: fetch
  EIA CO2 by fuel; dollars = tons x price; map coal -> coal mining (212100), natural
  gas and petroleum -> oil and gas extraction (211000) at the detail level (summary:
  211 and 212 aggregates); returns `[IndustryTax(...)]`. EIA figures are domestic
  consumption emissions, so this approximates an upstream tax with border
  adjustment. `coverage="downstream"` is reserved for a later emissions-by-industry
  source; the engine already supports it via per-industry dollars.

Shocks compose additively. The result records total statutory tax
`sum(tau * y) + sum(T * Z)`.

### 8.3 Solve (default, "output-tax" formulation)
```
A_hat = A * (1 + T)                     elementwise; T = 0 when no flow taxes
p_hat = (I - A_hat')^-1 (v + tau)
dp = p_hat - 1                          percent change by industry
```
Identity (asserted when T = 0): dp' @ F.sum(axis=1) == sum(tau * y), i.e. the total
price increase on final demand equals the tax. With flow taxes the identity holds
with the flow-tax revenue added.

### 8.4 WP6 replication mode (`formulation="wp6"`)
```
t_i = dollars_i / Z.sum(axis=1)[i]       burden over the industry's intermediate sales
p_hat = (I - A' diag(1 + t))^-1 v
```
Used only to reproduce the 2009 numbers; documented as such.

### 8.5 Commodity and PCE prices
Commodity price change (producers' prices): `dp_c = N' @ dp` (market-share weighted
over producing industries; consistent with how Z was built).

PCE category price change, per NIPA line k, from the bridge in purchasers' prices:
```
dP_k = [ sum_c PV_ck dp_c + TC_k dp_transport + WM_k dp_wholesale + RM_k dp_retail ] / PurchV_k
```
where dp_transport, dp_wholesale, dp_retail are output-weighted averages of the
commodity price changes of the margin providers. At the 2017 detail level (verified
codes): wholesale = the ten 42xxxx commodities (423100 ... 425000), excluding 4200ID
customs duties; retail = 441000, 444000, 445000, 446000, 447000, 448000, 452000,
454000, 4B0000; transportation = 481000 air, 482000 rail, 483000 water, 484000 truck,
486000 pipeline. The code lists live in one place (`bridge.py`) keyed by level, and
the weights are exposed. Builder's call to refine with BEA's margins table later.
Bridge rows whose commodity is not in the table (S00401 scrap, used goods) get
dp_c = 0 and are reported.

This is where WP6's purchasers'-price adjustment of the make table is replaced: the
margin dollars get the margin industries' own price changes rather than the
commodity's. It is also why commodity prices stay in producers' prices.

Burdens:
- `pce_prices`: NIPA line, category, dP_k, base spending PurchV_k, burden = dP_k x PurchV_k.
- `burden_by_final_demand`: dp' @ F by final-demand column (producers' prices), plus
  the PCE total from the bridge; the two PCE figures differ only by margin treatment
  and the difference is reported.
- `summary`: total tax, total final-demand burden, PCE burden, share of tax falling
  on PCE, max identity residual.

## 9. Validation and tests

Unit (toy) fixture: the BEA manual's three-industry example, tables 12.5 to 12.15
(make 12.7, use 12.5, market shares 12.8, nonscrap ratios 12.9, W 12.10,
commodity-by-commodity direct requirements 12.11, total requirements 12.14 and 12.15).
These exact numbers are committed as a test and must be reproduced to the printed
precision by the `bea` scrap mode. The `redistribute` mode is tested on the same toy
for identities and non-negativity.

Regression (legacy 2002 tables, fixtures committed as CSV). Provenance, verified
2026-11-22, from the original 2002 workbooks (held privately; only the extracted
fixtures are in the repo):
- 2002 summary inputs: the 2002 BEA summary make/use workbook (`2002summary_makeuse.xls`), BEA's
  original "Table 1. The Make..." / "Table 2. The Use..." sheets (133 industries,
  134 commodities incl. S004 scrap/used, 13 final-demand columns F010...F09I, codes
  like 1110, 813A, S001). Target: the 2002 summary square table. Same codes on both sides.
- 2002 detailed inputs: the flat `Data` sheets of the 2002 detailed make workbook
  (4,759 rows: industry, commodity, value) and use workbook (56,759 rows:
  commodity, industry, value). These are
  BEA's raw flat files with S00401/S00402/S00300/S00900 still present, but with the
  methodology paper's step-1 recoding already applied (1111A0 -> 111170 etc.).
  Target: the 2002 detailed square table, which uses the same recoded codes,
  so no crosswalk is needed and the test exercises the full pipeline including the
  `redistribute` step.
- Fixture extraction is a one-time, documented script run outside the package (the
  .xls files need xlrd, which is not a package dependency); outputs are CSVs under
  `tests/fixtures/2002/`. The detailed fixtures (~3 MB) are stored gzip-compressed;
  the test skips if they are absent.
- Tests: summary rebuild with `scrap="keep"` matches cell by cell (1e-6 relative);
  detailed rebuild with `scrap="redistribute"` matches cell by cell.
- Reproduce WP6 price impacts: run the 2002 summary table through
  `formulation="wp6"` with the Policy Inputs from `Distributional Model.xlsx`
  (burden rates L10 = 0.3954 for 2110, L11 = 1.8695 for 2121) and match the Pi sheet
  (e.g. coal mining 1.14725, electric power 1.16503, natural gas distribution
  1.18510) to 1e-6.

External (BEA's own table):
- With 2017 detail inputs and the published-table convention (`scrap="bea",
  scrap_codes=("S00402",)`, after redefinitions), compute (I - Z diag(y)^-1)^-1 and
  compare with `IxI_TR_2017_PRO_DET.xlsx` (published to 7 decimals): max abs
  difference below 1e-3 (observed 7e-4). Before-redefinitions inputs are run and
  recorded as not matching, which pins the after-redefinitions default by data.

Identities (always, any input): row totals = column totals; N columns sum to 1;
baseline prices = 1; price-model burden identity (8.3).

Parsing robustness: tests that shift the header row, change int/str codes, add a
trailing note row, and reorder industries between make and use.

## 10. Repository layout and packaging

```
src/iotables/{__init__,download,sources,parse,square,leontief,shocks,bridge,validate,cli}.py
tests/{test_parse,test_square,test_leontief,test_bridge,test_regression_2002,test_bea_ixi}.py
tests/fixtures/            toy example, 2002 summary make/use/table CSVs, 2002 detailed (compressed)
data/raw/                  downloads (git-ignored), data/output/ (git-ignored)
docs/reference/            papers and literature notes
docs/superpowers/specs/    this document
README.md, pyproject.toml
```

Dated work notes go to a private working log (not in the repository).

README gets: purpose, one-paragraph method, install, the two CLI commands, a worked
example (carbon preset and a plain industry tax), how validation was done, citation
to the methodology paper and WP6. License: to be chosen by the project owner (MIT suggested).

## 11. Left to the builder

- Internal file formats for cache and provenance (json sidecar suggested).
- Exact dataclass vs. plain-dict choices, logging, progress output.
- Retail/transport margin weighting details (8.5), as long as weights are exposed.
- Aggregation helper from 20 final-demand columns to the six standard components.
- How to compress and store the 2002 detailed fixture.
- CLI argument syntax for shocks beyond the sketch in 5.3.

## 12. Open items

- BEA API key: Phase 2 needs one (free registration at
  https://apps.bea.gov/api/signup/); the package reads it from the `BEA_API_KEY`
  environment variable.
- License choice (MIT suggested).
- Whether to commit generated 2017 output tables to the repo (~5 MB) or publish
  them as release assets.
