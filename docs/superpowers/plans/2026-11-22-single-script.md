# Single-Script Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One self-contained Python script, run cell by cell, that builds the square input-output table and traces any cost shock (including import tariffs) to consumer prices.

**Architecture:** `io_model.py` at the repository root, in twelve `# %%` cells that run top to bottom on module-level variables. Two helper functions only (`fetch`, `read_bea_sheet`). Tests execute the script's cells in a fresh namespace with the configuration overridden and compare the resulting variables with the `iotables` package and with independent calculations.

**Tech Stack:** Python 3.10+, pandas, numpy, openpyxl, requests; pytest.

**Spec:** `docs/superpowers/specs/2026-11-22-single-script-design.md`

**Status:** carried out on 2026-11-22. The spec's "Revisions after the first build" section records what changed afterwards (the `script/` folder, one method only, and the package brought into line); where it differs from this plan, the spec holds.

## Global Constraints

- The script imports pandas, numpy, openpyxl, requests and the standard library only; nothing from `iotables`.
- No Excel output. Results are CSV files only.
- Only two functions in the script: `fetch(url, filename)` and `read_bea_sheet(path, sheet)`.
- Vocabulary is "cost shock", not "tax". Carbon is an optional example, off by default.
- Every cell starts with a comment block that says what it does and gives its formula, and ends by printing a short summary. Variable names follow the spec's symbols.
- Codes are aligned by label, never by position. Dollars are millions; rates and price changes are fractions.
- Tracked files carry no personal paths or names; test prose stays neutral.

## Facts established from the data (2017 detail)

- BEA's import matrix (`ImportMatrices_Before_Redefinitions_DET_2017.xlsx`, sheet `2017`) has the use table's 402 commodity rows and its industry and final-demand columns. Its imports column `F05000` is minus each row's total, so every row sums to zero. Therefore `U_d = U - U_m` and `D_d = D - D_m` over all columns leave each commodity's total use, and so industry output, unchanged. What stays in the domestic `F05000` column is BEA's reconciliation (duties, freight and insurance on imports).
- Imported final uses are `D_m` without its `F05000` column.
- Import shares vary across buyers of a commodity, so the matrix is used cell by cell.
- The matrix is before redefinitions only. Final-demand columns are identical before and after redefinitions; intermediate cells differ. For `REDEFINITIONS = "after"`: each cell's import share comes from the before-redefinitions pair (the commodity's overall intermediate share where the before cell is zero), is applied to the after-redefinitions cell, and each commodity row is then scaled so its intermediate imports equal BEA's total.
- Noncomparable imports (`S00300`) are wholly imported. Split mode keeps that row in `U_m` and `D_m` as an imported commodity; the domestic side drops it as the package does.
- Scrap rows (`S00401`, `S00402`) are removed from `U_m` and `D_m` whenever they are removed from the use table.

## Variables each cell leaves in memory

| Cell | Names |
| --- | --- |
| 3 read | `M`, `U`, `D`, `VA`, `g`, `U_m`, `D_m`, `industry_labels`, `commodity_labels`, `final_demand_labels`, `bridge` |
| 4 scrap | `M`, `U`, `D`, `U_m`, `D_m` reduced; `nonscrap_ratio` |
| 5 shares | `q`, `market_shares`, `N` |
| 6 square | `U_d`, `D_d`, `Z`, `F`, `y`, `V`, `B`, `F_m` (imported final uses, commodities x final-demand columns) |
| 7 identities | `identities` (dict of residuals) |
| 8 BEA check | `bea_check` (dict: `max_abs_diff`, `mean_abs_diff`) |
| 9 shocks | `tau`, `T`, `dp_m`, `price_targets`, `shock_list` |
| 10 prices | `A`, `v`, `p`, `dp`, `total_shock`, `burden`, `summary` |
| 11 consumer | `dp_c`, `pce_import_share`, `margin_dp`, `pce_prices` |
| 12 outputs | `written` (list of paths) |

With `IMPORTS = "combined"`, `U_m` and `D_m` are zero frames, so `B` and `F_m` are zero and every formula is unchanged.

## Review Focus

- A code in `SHOCKS` that is not in the table: fail with a message naming the code and the kind.
- An `"import"` shock while `IMPORTS = "combined"`: fail with a message saying to set `"split"`.
- A commodity with no imports given an import shock in dollars: fail (rate undefined).
- A `"price"` target on an industry that also has a cost shock: the price ends exactly at the target.
- `FORMULATION = "wp6"` with a flow, price or import shock: fail with a clear message.

---

### Task 1: Table construction (cells 1 to 7) and the test harness

**Files:** Create `io_model.py`, `tests/test_script.py`, `requirements.txt`.

**Interfaces:** Produces the cell 3 to 7 variables above, and in the test file
`run_script(overrides: dict, inject: dict | None = None, only: range | None = None) -> dict`,
which splits `io_model.py` at lines starting `# %%`, executes cell 1, applies `overrides`, applies `inject`, executes the chosen cells and returns the namespace.

- [ ] Tests (network-marked where they read BEA files):
  - `test_combined_matches_package_table`: `IMPORTS="combined"`; `Z`, `F`, `y`, `V` equal `build_square_table(*load_bea_tables("detail", 2017, "after"))` to 1e-6, for `SCRAP` in `bea`, `redistribute`.
  - `test_split_keeps_industry_output`: `IMPORTS="split"`; `y` equals the combined run's `y` to 1e-6; `identities` residuals below 1e-6; `U_m.to_numpy().sum()` within 0.5 percent of 1,416,292.
  - `test_split_before_redefinitions_uses_bea_matrix`: `REDEFINITIONS="before"`; `U_m` equals BEA's matrix cells exactly (scrap rows aside).
  - `test_script_has_no_package_import_and_no_excel_output`: the source contains no `iotables` import, no `to_excel`, and exactly two `def` statements.
- [ ] Write cells 1 to 7. Run the tests.

### Task 2: BEA check, shocks and the price model (cells 8 to 10)

**Files:** Modify `io_model.py`, `tests/test_script.py`.

- [ ] Tests:
  - `test_bea_check`: `bea_check["max_abs_diff"] < 1e-3`.
  - `test_combined_prices_match_package`: for the shock set industry dollars, commodity rate, flow rate and value-added rate, `dp` and `summary["total_shock"]` equal `PriceModel.run` to 1e-9; again under `FORMULATION="wp6"` with an industry-dollars shock.
  - `test_burden_identity_split`: for a tariff alone, a domestic shock alone and both, `abs(summary["identity_residual"]) < 1e-6 * total`; tariff revenue equals rate times total imports of the commodity.
  - `test_price_target_is_hit`: `("industry","211000","price",0.20)` plus an industry cost shock on the same industry gives `dp["211000"] == 0.20` to 1e-12, and the other prices equal those from solving with that industry's equation removed.
  - `test_toy_tariff`: injected three-industry economy with a diagonal make table: A buys 20 of imported X per 100 of output, B buys 50 of A per 100, C buys nothing; a 25 percent tariff on X gives `dp` = 0.05, 0.025, 0.
  - `test_bad_shocks_fail`: the five Review Focus cases raise `ValueError` or `KeyError` with the code in the message.
- [ ] Write cells 8 to 10. Run the tests.

Price target algorithm: with `L = (I - A_hat')^-1`, `p0` the solution without the targets and `S` the targeted industries, solve `L[S,S] tau_S = (1 + target) - p0[S]`, add `tau_S` to `tau`, and solve again.

### Task 3: Consumer prices and outputs (cells 11 and 12)

**Files:** Modify `io_model.py`, `tests/test_script.py`.

- [ ] Tests:
  - `test_combined_pce_matches_package`: `pce_prices` (columns `nipa_line`, `pce_category`, `price_change`, `base_spending`, `burden`) equals the package's to 1e-9; the carbon example at $50 and 2024 gives the package's `carbon_price` result.
  - `test_split_pce_tariff`: for a tariff on one commodity with no intermediate imports effect removed (compare with a hand calculation: producers' value times PCE import share times the rate, plus the domestic pass-through), PCE burden is positive and no larger than the tariff revenue.
  - `test_outputs_are_csv`: `OUTPUT_DIR` set to a temporary folder holds no `.xlsx` file, and holds `Z.csv`, `F.csv`, `V.csv`, `y.csv`, `B.csv`, `market_shares.csv`, `labels.csv`, `industry_prices.csv`, `commodity_prices.csv`, `pce_prices.csv`, `burden_by_final_demand.csv`, `summary.csv`, `shocks.csv`.
- [ ] Write cells 11 and 12. Run the whole suite (`pytest -q`).

Consumer price of commodity c in a PCE line: `(1 - m_c) dp_c[c] + m_c dp_m[c]`, with `m_c` the import share of the commodity's PCE in the use table; margins take the domestic margin industries' price changes as in the package.

### Task 4: Documentation

- [ ] Add a short "The single script" section near the top of `README.md`: what it is, how to set up the virtual environment and run it, the shock table with the `import` kind and the `price` unit, and the note that domestic producers do not respond to tariffs. Replace the README's mention of the Excel workbook where it describes the script's outputs only; the package text stays.
- [ ] Run the script top to bottom with the default configuration and read the printed output for sense.
- [ ] Append the session to the private working log.
