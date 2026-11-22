# 2002 regression fixtures

Used by `tests/test_regression_2002.py`, which rebuilds the 2002 summary and detailed
input-output tables from BEA's 2002 make and use tables.

Extracted on 2026-11-22 by `scripts/extract_2002_fixtures.py` (run with a scratch interpreter
that has pandas, openpyxl and xlrd; xlrd is not an iotables dependency), using Python 3.12.7,
pandas 3.1.1, numpy 2.5.5, openpyxl 3.1.5 and xlrd 2.0.2. Re-running it reproduces these files
byte for byte. Sources: the original 2002 workbooks, held privately; see the script for the
expected file names.

| Fixture | Source |
| --- | --- |
| `summary_make.csv`, `summary_make_labels.csv` | the 2002 summary make and use workbook, sheet `MAKE` (BEA Table 1, before redefinitions) |
| `summary_use.csv`, `summary_use_labels.csv` | the same workbook, sheet `USE` (BEA Table 2) |
| `summary_target.csv` | the 2002 summary input-output table workbook, sheet `2002 Summary-Level` |
| `detail_make.csv.gz` | the 2002 detailed make workbook, sheet `Data` (4,759 records) |
| `detail_use.csv.gz` | the 2002 detailed use workbook, sheet `Data` (56,759 records) |
| `detail_target.csv.gz` | the 2002 detailed input-output table workbook, sheet `2002 Detailed Level` |

## Format

Each value file is a grid in $ millions at full stored precision: first header `code`, row
codes down the first column, column codes across the header (`.gz` files are gzip). Read with
`pd.read_csv(path, index_col=0, dtype={"code": str})`; `tests/conftest.py::grid_from_csv`
turns one into a `BeaGrid`. A labels file has columns `code,description` and lists the grid's
row codes in order, then its column codes in order (a code on both axes, like industry
"Crop production" and commodity "Crop products" 1110, appears once per axis).

| File | Rows | Columns |
| --- | --- | --- |
| `summary_make.csv` | 133 industries + `T007` | 134 commodities (incl. `S00400`) + `T008` |
| `summary_use.csv` | 134 commodities + `V00100 V00200 V00300 T008` | 133 industries + `T001` + 13 final demand (`F010`...`F09I`) + `T004 T007` |
| `summary_target.csv` | 133 industries + `V00100 V00200 V00300 T008` | 133 industries + 13 final demand + `T008` |
| `detail_make.csv.gz` | 426 industries | 425 commodities (424 made, incl. `S00401`, + zero `S00101`) |
| `detail_use.csv.gz` | 424 commodities + `S00300 S00401 S00402 S00900` + `V00100 V00200 V00300` | 426 industries + 13 final demand (`F01000`...`F09I00`) |
| `detail_target.csv.gz` | 426 industries + `V00100 V00200 V00300 T008` | 426 industries + 13 final demand + `T008` |

The targets are in `SquareIOTable.to_frame()` layout without the `Description` column.

## Normalizations (nothing else is changed)

- Codes are stripped strings; integer-valued numbers lose the decimal (`1110.0` -> `"1110"`).
- Summary codes: `S004` -> `S00400`, `V001/V002/V003` -> `V00100/V00200/V00300`.
- Summary make: the `N/A` "ROW of World" row is all zero and dropped (the script asserts it);
  the `M` matrix pasted below the table in the source sheet is not read. Summary use: the
  `T005` and `T006` total rows are left out.
- Detailed make and use: the flat records are pivoted wide (duplicate pairs would be summed;
  there are none; absent pairs are 0). The make gains a zero column for `S00101`, the one
  regular use commodity it lacks (its use row is all zero). `S00300`, `S00900` and `S00402`
  stay out of the make, as in BEA's file; the build drops or redistributes them.
- Targets: the total-output column (summary: coded `T007`, headed "Total Industry Output";
  detailed: uncoded "Total") and row (summary: uncoded "Total industry output"; detailed:
  "Total") become `T008`. The sheets leave the value-added rows and the total row blank under
  final demand and `T008` (56 cells each); those are filled by `to_frame()`'s rule from the
  sheet's own cells: value added under final demand 0, a value-added row's `T008` its row sum,
  the total row under final demand the column sums over industries, its `T008` its row sum.

## Comparison scope

Tolerances: rtol 1e-6, atol 1e-3.

- **Summary** (`test_rebuild_2002_summary_table_matches_legacy`): every cell, with the 2002
  table's market shares taken over the make column totals q in place of BEA's published total
  commodity output (the make table's `T007` row): dN = M diag(1/q - 1/T007), applied to U and
  D, is added to the 2002 table. It is computed from the fixtures alone, never from the
  pipeline's output.
- **Detailed** (`test_rebuild_2002_detailed_table_matches_legacy`): every cell outside this set:
  - the rows of the industries that make S00102, S00203 or S00401;
  - the S00800 and T008 cells of V00200 and of the industries that make 811400 or 813800;
  - the V00300 and T008 rows in those industries' columns, S00800 and T008.
- **Detailed, every cell** (`test_rebuild_2002_detailed_table_with_legacy_construction`): the
  test applies the same column pairing and record set as the original workbook to the inputs
  (`POSITION_PAIRS_2002` and `UNPIVOTED_RECORDS_2002`, in the test only), runs the pipeline
  unchanged and compares every cell.
