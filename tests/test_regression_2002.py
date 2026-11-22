# tests/test_regression_2002.py
"""Rebuild Andrew's hand-built 2002 tables from BEA's make and use tables, cell for cell.

The legacy workbooks deviate from the pipeline's (correct) method in documented places
(tests/fixtures/2002/README.md); the tests encode those deviations explicitly rather than
loosening the tolerance or changing the pipeline.
"""
import pytest, pandas as pd
from pathlib import Path
from iotables import parse, square, validate
from conftest import grid_from_csv
FIX = Path(__file__).parent / "fixtures" / "2002"

def _target(name):
    p = FIX / name
    if not p.exists(): pytest.skip(f"fixture {name} missing")
    return pd.read_csv(p, index_col=0, dtype={"code": str}, compression="gzip" if name.endswith(".gz") else None)

def _with_make_column_totals(legacy, make, use):
    """The legacy summary table as it would be with market shares over the make column totals q.

    The legacy shares divide by BEA's published total commodity output (the make table's T007
    row), which differs from q by BEA's rounding (up to $0.4M, in 43 of 134 commodities). This
    adds back the exact effect of the difference, dN = M diag(1/q - 1/T007), on every cell.
    """
    inds, fd = make.industries, list(use.final_demand.columns)
    dN = make.values / make.values.sum(axis=0) - make.values / make.commodity_output
    dZ, dF = dN @ use.intermediate.loc[:, inds], dN @ use.final_demand
    dy = dZ.sum(axis=1) + dF.sum(axis=1)
    dgos = dy - dZ.sum(axis=0)  # gross operating surplus balances each column
    out = legacy.copy()
    out.loc[inds, inds] += dZ; out.loc[inds, fd] += dF; out.loc[inds, "T008"] += dy
    out.loc["V00300", inds] += dgos; out.loc["V00300", "T008"] += dgos.sum()
    out.loc["T008", inds] += dy; out.loc["T008", fd] += dF.sum(axis=0)
    out.loc["T008", "T008"] += dy.sum() + dF.to_numpy().sum()
    return out

def test_rebuild_2002_summary_table_matches_legacy():
    make = parse.MakeTable.from_grid(grid_from_csv(FIX / "summary_make.csv", FIX / "summary_make_labels.csv"))
    use = parse.UseTable.from_grid(grid_from_csv(FIX / "summary_use.csv", FIX / "summary_use_labels.csv"))
    sq = square.build_square_table(make, use, scrap="keep", drop=())
    ours = sq.to_frame().drop(columns="Description"); theirs = _target("summary_target.csv")
    bad = validate.compare_tables(ours, _with_make_column_totals(theirs, make, use), rtol=1e-6, atol=1e-3)
    assert bad.empty, bad.head(20)
    assert sq.n == 133

def test_rebuild_2002_detailed_table_matches_legacy():
    make = parse.MakeTable.from_grid(grid_from_csv(FIX / "detail_make.csv.gz", None))
    use = parse.UseTable.from_grid(grid_from_csv(FIX / "detail_use.csv.gz", None))
    sq = square.build_square_table(make, use, scrap="redistribute")
    ours = sq.to_frame().drop(columns="Description"); theirs = _target("detail_target.csv.gz")
    bad = validate.compare_tables(ours, theirs, rtol=1e-6, atol=1e-3)
    # Two legacy spreadsheet errors (README.md), whose cells are excluded; everything else must match.
    # (1) MMULT(M, U) paired make columns with use rows by position, and make columns S00102, S00203,
    #     S00401 sat against use rows S00101, S00102, S00203: every cell of an industry that makes
    #     one of those commodities is off, and so are the V00300 and T008 rows, which sum over them.
    # (2) The use pivot read Data!A1:E56756, dropping the file's last four records, all in column
    #     S00800 (811400 30.4, 813800 9275.5, V00200 99182.8, V00300 603942.5): the S00800 and T008
    #     cells of V00200 and of the industries that make 811400 or 813800 are off.
    M = make.values
    misaligned = M.index[(M[["S00102", "S00203", "S00401"]] != 0).any(axis=1)]
    unpivoted = [*M.index[(M[["811400", "813800"]] != 0).any(axis=1)], "V00200"]
    excluded = (bad["row"].isin([*misaligned, "V00300", "T008"])
                | (bad["row"].isin(unpivoted) & bad["col"].isin(["S00800", "T008"])))
    assert bad[~excluded].empty, bad[~excluded].head(20)
    assert len(misaligned) == 89 and excluded.any()
    assert sq.n == 426 and sq.meta["diagnostics"]["redistributed"]["final_demand"] != 0
