# tests/test_regression_2002.py
"""Rebuild the 2002 summary and detailed tables from BEA's make and use tables, cell for cell.

Tolerances rtol 1e-6, atol 1e-3. Summary: compared with the 2002 table's market shares taken over
the make column totals q in place of BEA's published T007 commodity output. Detailed: compared
outside the cell set defined in `test_rebuild_2002_detailed_table_matches_legacy`; a second test
applies the same column pairing and record set as the original workbook and compares every cell.
The scope is also stated in tests/fixtures/2002/README.md.
"""
import dataclasses
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
    """The 2002 summary table with its market shares taken over the make column totals q.

    The 2002 workbook's shares are over BEA's published total commodity output (the make table's
    T007 row). This adds dN = M diag(1/q - 1/T007), applied to U and D, to every cell; it uses the
    fixtures only, never the pipeline's output.
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

# The original workbook's column pairing and record set for the detailed table, used by the two detailed tests.
# Column pairing: each make column and the use row the workbook pairs it with.
POSITION_PAIRS_2002 = {"S00102": "S00101", "S00203": "S00102", "S00401": "S00203"}  # make column -> use row
# Record set: the four S00800 use records outside the workbook's pivot range.
UNPIVOTED_RECORDS_2002 = {("811400", "S00800"): 30.4, ("813800", "S00800"): 9275.5,
                          ("V00200", "S00800"): 99182.8, ("V00300", "S00800"): 603942.5}

def test_rebuild_2002_detailed_table_matches_legacy():
    make = parse.MakeTable.from_grid(grid_from_csv(FIX / "detail_make.csv.gz", None))
    use = parse.UseTable.from_grid(grid_from_csv(FIX / "detail_use.csv.gz", None))
    sq = square.build_square_table(make, use, scrap="redistribute")
    ours = sq.to_frame().drop(columns="Description"); theirs = _target("detail_target.csv.gz")
    bad = validate.compare_tables(ours, theirs, rtol=1e-6, atol=1e-3)
    # Compared outside this cell set (every other cell must match):
    # the rows of the industries that make S00102, S00203 or S00401 (the paired make columns);
    # the S00800 and T008 cells of V00200 and of the industries that make 811400 or 813800;
    # the V00300 and T008 rows in those industries' columns, S00800 and T008.
    M = make.values
    paired_makers = list(M.index[(M[list(POSITION_PAIRS_2002)] != 0).any(axis=1)])
    unpivoted_makers = list(M.index[(M[["811400", "813800"]] != 0).any(axis=1)])
    excluded = (bad["row"].isin(paired_makers)
                | (bad["row"].isin([*unpivoted_makers, "V00200"]) & bad["col"].isin(["S00800", "T008"]))
                | (bad["row"].isin(["V00300", "T008"])
                   & bad["col"].isin([*paired_makers, *unpivoted_makers, "S00800", "T008"])))
    assert bad[~excluded].empty, bad[~excluded].head(20)
    assert len(paired_makers) == 89 and len(unpivoted_makers) == 19 and len(bad) == 25_020
    assert sq.n == 426 and sq.meta["diagnostics"]["redistributed"]["final_demand"] != 0

def test_rebuild_2002_detailed_table_with_legacy_construction():
    """Applies the original workbook's column pairing and record set to the inputs (in this test only), then
    compares every cell."""
    make = parse.MakeTable.from_grid(grid_from_csv(FIX / "detail_make.csv.gz", None))
    use_grid = grid_from_csv(FIX / "detail_use.csv.gz", None)
    # Record set: the four records outside the pivot range are set to 0.
    values = use_grid.values.copy()
    for (row, col), value in UNPIVOTED_RECORDS_2002.items():
        assert values.loc[row, col] == value
        values.loc[row, col] = 0.0
    use = parse.UseTable.from_grid(dataclasses.replace(use_grid, values=values))
    # Column pairing: each make column takes the code of its paired use row, so the pipeline's code
    # alignment pairs them the same way. The fixture's S00101 make column is all zero and is dropped.
    assert not make.values["S00101"].any()
    make = dataclasses.replace(make, values=make.values.drop(columns="S00101").rename(columns=POSITION_PAIRS_2002),
                               commodity_labels=make.commodity_labels.drop("S00101").rename(POSITION_PAIRS_2002))
    sq = square.build_square_table(make, use, scrap="redistribute")
    ours = sq.to_frame().drop(columns="Description"); theirs = _target("detail_target.csv.gz")
    bad = validate.compare_tables(ours, theirs, rtol=1e-6, atol=1e-3)  # every cell
    assert bad.empty, bad.head(20)
