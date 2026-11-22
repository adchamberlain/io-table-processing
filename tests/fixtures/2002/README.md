# 2002 regression fixtures

Used by `tests/test_regression_2002.py`, which rebuilds Andrew's hand-built 2002 summary and
detailed input-output tables from BEA's 2002 make and use tables.

Extracted on 2026-11-22 by `scripts/extract_2002_fixtures.py` (run with a scratch interpreter
that has pandas, openpyxl and xlrd; xlrd is not an iotables dependency). Re-running it
reproduces these files byte for byte. Sources, read-only, under
`~/Library/CloudStorage/Dropbox/Research/Models and Studies (Pre-Grad School)/`:

| Fixture | Source |
| --- | --- |
| `summary_make.csv`, `summary_make_labels.csv` | `Carbon Tax Model/Data FIles/2002summary_makeuse.xls`, sheet `MAKE` (BEA Table 1, before redefinitions) |
| `summary_use.csv`, `summary_use_labels.csv` | same file, sheet `USE` (BEA Table 2) |
| `summary_target.csv` | `U.S. Input-Output Tables/2002 Summary Input-Output Table.xlsx`, sheet `2002 Summary-Level` |
| `detail_make.csv.gz` | `U.S. Input-Output Tables/Supporting Files/2002 Detailed Make.xlsx`, sheet `Data` (4,759 records) |
| `detail_use.csv.gz` | `U.S. Input-Output Tables/Supporting Files/2002 Detailed Use.xlsx`, sheet `Data` (56,759 records) |
| `detail_target.csv.gz` | `U.S. Input-Output Tables/2002 Detailed Input-Output Table.xlsx`, sheet `2002 Detailed Level` |

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
  Andrew's own `M` matrix pasted below the table is not read. Summary use: the `T005` and `T006`
  total rows are left out.
- Detailed make and use: the flat records are pivoted wide (duplicate pairs would be summed;
  there are none; absent pairs are 0). The make gains a zero column for `S00101`, the one
  regular use commodity it lacks (its use row is all zero). `S00300`, `S00900` and `S00402`
  stay out of the make, as in BEA's file; the build drops or redistributes them.
- Targets: the total-output column (summary: mislabeled `T007` "Total Industry Output";
  detailed: uncoded "Total") and row (summary: uncoded "Total industry output"; detailed:
  "Total") become `T008`. The sheets leave the value-added rows and the total row blank under
  final demand and `T008` (56 cells each); those are filled by `to_frame()`'s rule from the
  sheet's own cells: value added under final demand 0, a value-added row's `T008` its row sum,
  the total row under final demand the column sums over industries, its `T008` its row sum.

## Where the legacy tables deviate (the tests encode these; tolerances are not loosened)

Every deviation below was traced to the legacy workbook and reproduced: rebuilding with the
legacy's choices reproduces each target to floating-point precision.

1. **Summary: market shares over BEA's published commodity output.** Andrew's summary shares
   divide the make table by its published `T007` row (Total commodity output; see his `M`
   matrix in the `MAKE` sheet, e.g. 114683.2 / 114703.2), not by the make column totals q that
   the pipeline uses (spec section 7). The two differ by BEA's rounding in 43 of 134
   commodities (q - T007 between -0.3 and +0.4). Effect on the table: up to 0.375 in industry
   cells (2301 / T008) and 1.88 in the grand total, 509 cells beyond rtol 1e-6 / atol 1e-3.
   The test compares against the legacy table plus the exact effect of the difference,
   dN = M diag(1/q - 1/T007) applied to U and D; then every cell matches (max |diff| 3.7e-9).

2. **Detailed: MMULT pairs commodities by position, three of them wrongly.** In
   `Supporting Files/Derivation Model - Detailed I-O Table.xlsx` the table is
   `MMULT(M, U)` and `MMULT(M, D)` over named ranges `M = 'Make Table'!$C$436:$PJ$861`,
   `U = 'Use Table'!$C$7:$PL$430`, `D = 'Use Table'!$PM$7:$PY$430`. Make columns 418-420 are
   `S00102, S00203, S00401` while use rows 418-420 are `S00101, S00102, S00203`, so S00102's
   producers got S00101's (zero) uses, S00203's producers got S00102's, and the scrap (S00401)
   producers got S00203's. Every cell of the 89 industries that make S00102, S00203 or S00401
   is off (largest: S00203 / T008 by 48,561), and so are the `V00300` and `T008` rows.
   The test excludes those rows.

3. **Detailed: the use pivot skips the last four records.** The pivot cache in
   `2002 Detailed Use.xlsx` reads `Data!A1:E56756` (56,755 of the 56,759 records), dropping
   Data rows 56757-56760, all in column S00800 (owner-occupied dwellings): 811400 30.4,
   813800 9,275.5, V00200 99,182.8, V00300 603,942.5. The legacy S00800 column therefore lacks
   those purchases and its taxes. The test excludes the S00800 and T008 cells of `V00200` and of
   the industries that make 811400 or 813800.

With those exclusions the detailed test compares 149,126 of 189,200 cells, including every
column's redistributed scrap and used goods, and all match (max |diff| 9.3e-10).

A second detailed test, `test_rebuild_2002_detailed_table_replaying_legacy_quirks`, replays
errors 2 and 3 on the inputs, inside the test and labeled as reproducing legacy errors. It
zeroes the four records the pivot missed, and it relabels make columns S00102, S00203 and
S00401 with the use rows they met (S00101, S00102, S00203), so that code alignment pairs them
the way the legacy positions did. It then runs the unchanged pipeline (`redistribute` mode) and
compares every one of the 189,200 cells at the same tolerances (max |diff| 1.1e-8, at the
3.0e7 grand total). Neither replay is enough on its own: without the pivot replay 66 cells
differ, and without the MMULT replay 24,957 do. Together the two detailed tests show that
(a) the pipeline matches the legacy table everywhere the legacy table is right, and (b) the
only differences are those two identified legacy errors.
