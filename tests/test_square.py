"""The square table: market shares, the removed commodities and the layout it is written in.

The toy economy is the three-industry example of BEA's Concepts and Methods
manual (tables 12.5 and 12.7), with scrap; nothing in it is imported.
"""

import dataclasses
import json

import numpy as np
import pandas as pd
import pytest

from conftest import add_make_column, add_use_row, no_imports
from iotables import parse, square


def build(make, use):
    return square.build_square_table(make, use, no_imports(use))


def test_market_shares_columns_sum_to_one(toy_make):
    ms = square.market_shares(toy_make.values)
    assert np.allclose(ms.sum(axis=0), 1.0)
    assert ms.loc["A", "A"] == pytest.approx(300 / 330)


def test_market_shares_zero_output_column_is_zero():
    m = pd.DataFrame([[1.0, 0.0], [1.0, 0.0]], index=["i", "j"], columns=["a", "b"])
    ms = square.market_shares(m)
    assert (ms["b"] == 0).all() and not ms.isna().any().any()


def test_matches_the_handbook_example(toy_make, toy_use, toy_square):
    sq = toy_square
    assert list(sq.meta["diagnostics"]["nonscrap_ratio"].round(3)) == [0.991, 0.995, 1.000]
    W = sq.N
    expected_W = pd.DataFrame([[.917, .063, .000], [.091, .904, .074], [.000, .038, .926]], index=list("ABC"), columns=list("ABC"))
    assert np.allclose(W.values, expected_W.values, atol=5e-4)
    assert np.allclose(sq.y.values, [328, 412, 265])                      # industry output is BEA's
    assert "S00401" not in sq.market_shares.columns and sq.check_identities()["row_minus_col"] < 1e-9
    # total requirements: commodity-by-commodity (I - BW)^-1 and industry-by-commodity W(I - BW)^-1
    B = toy_use.intermediate.drop(index="S00401").div(toy_use.industry_output, axis=1)
    cxc = np.linalg.inv(np.eye(3) - B.values @ W.values)
    assert np.allclose(cxc, [[2.487, 1.500, 1.778], [1.736, 2.300, 1.579], [1.292, 1.322, 2.323]], atol=2e-3)
    ixc = W.values @ cxc
    assert np.allclose(ixc, [[2.391, 1.521, 1.731], [1.893, 2.316, 1.763], [1.261, 1.310, 2.210]], atol=2e-3)
    A = sq.Z.div(sq.y, axis=1)
    assert np.allclose(np.linalg.inv(np.eye(3) - A.values) @ W.values, ixc, atol=1e-9)


def test_table_parts_and_meta(toy_make, toy_use):
    toy_make.meta.update(year=2017, level="detail")
    sq = build(toy_make, toy_use)
    assert sq.Z.shape == (3, 3) and list(sq.F.columns) == ["F01000"] and list(sq.V.index) == ["V00100", "V00200", "V00300"]
    assert sq.industries == ["A", "B", "C"] and sq.n == 3
    assert sq.meta["year"] == 2017 and sq.meta["level"] == "detail"
    assert sq.meta["source"] == {"make": toy_make.meta, "use": toy_use.meta}
    pd.testing.assert_series_equal(sq.meta["commodity_output"], pd.Series([330.0, 400.0, 270.0], index=list("ABC")), check_names=False)
    d = sq.meta["diagnostics"]
    assert d["removed"] == ("S00401",) and d["y_minus_g"].abs().max() < 1e-9
    assert d["gos_minus_bea"].abs().max() < 2                             # scrap leaves the inputs
    assert sq.final_demand_labels["F01000"] == "Personal consumption expenditures"
    assert (sq.imported_inputs == 0).all().all() and sq.total_imports.sum() == 0


def test_build_aligns_by_code(toy_make, toy_use):
    use2 = parse.UseTable(**{**toy_use.__dict__, "intermediate": toy_use.intermediate[["C", "A", "B"]],
                             "value_added": toy_use.value_added[["C", "A", "B"]]})
    pd.testing.assert_frame_equal(build(toy_make, toy_use).Z, build(toy_make, use2).Z)


def test_commodities_without_producers_are_removed(toy_make, toy_use, toy_square):
    # like the real 2017 tables: used goods and noncomparable imports have use rows but no producer,
    # and the rest-of-world adjustment is recorded as output of one industry
    make2 = add_make_column(toy_make, "S00900", [0, 3, 0])
    use2 = add_use_row(add_use_row(add_use_row(toy_use, "S00402", [1, 0, 0], fd=[-1]), "S00300", [2, 0, 0], fd=[-2]),
                       "S00900", [0, 0, 0], fd=[3])
    use2 = dataclasses.replace(use2, industry_output=make2.industry_output)
    sq = build(make2, use2)
    assert sq.meta["diagnostics"]["removed"] == ("S00401", "S00402", "S00300", "S00900")
    assert not {"S00401", "S00402", "S00300", "S00900"} & set(sq.market_shares.columns)
    assert sq.check_identities()["row_minus_col"] < 1e-9
    assert np.allclose(sq.y.values, [328, 415, 265])                      # output is still BEA's, the adjustment included
    assert sq.meta["diagnostics"]["nonscrap_ratio"]["B"] == pytest.approx((415 - 2 - 3) / 415)
    assert list(sq.imported_inputs.index) == ["A", "B", "C", "S00300"]    # noncomparable imports stay as imports


def test_build_rejects_tables_that_do_not_fit(toy_make, toy_use):
    bad = parse.UseTable(**{**toy_use.__dict__, "intermediate": toy_use.intermediate.rename(columns={"C": "Q"}),
                            "value_added": toy_use.value_added.rename(columns={"C": "Q"})})
    with pytest.raises(ValueError, match="Q"):
        build(toy_make, bad)
    with pytest.raises(ValueError, match=r"\['X'\]"):                     # made but never used
        build(add_make_column(toy_make, "X", [1, 0, 0]), toy_use)
    build(toy_make, add_use_row(toy_use, "Z", [0, 0, 0], fd=[0]))         # neither made nor used: fine
    with pytest.raises(ValueError, match=r"bought but that no industry makes: \['Z'\]"):
        build(toy_make, add_use_row(toy_use, "Z", [1, 0, 0], fd=[0]))
    values = toy_make.values.copy()
    values.loc["C"] = [0.0, 0.0, 0.0, 265.0]
    with pytest.raises(ValueError, match=r"no output left .*\['C'\]"):   # an industry that makes only scrap
        build(dataclasses.replace(toy_make, values=values), toy_use)


def test_to_frame_layout(toy_square):
    sq, f = toy_square, toy_square.to_frame()
    assert list(f.index) == ["A", "B", "C", "IMPORTS", "V00100", "V00200", "V00300", "T008"]
    assert list(f.columns) == ["Description", "A", "B", "C", "F01000", "T008"]
    assert f.loc["A", "T008"] == pytest.approx(sq.y["A"]) and f.loc["T008", "A"] == pytest.approx(sq.y["A"])
    assert f.loc["A", "B"] == sq.Z.loc["A", "B"] and f.loc["B", "F01000"] == sq.F.loc["B", "F01000"]
    assert f.loc["V00300", "C"] == sq.V.loc["V00300", "C"] and f.loc["V00300", "F01000"] == 0.0
    assert f.loc["T008", "T008"] == pytest.approx(sq.y.sum() + sq.F.values.sum())
    assert list(f["Description"]) == ["Industry A", "Industry B", "Industry C", "Imported inputs",
                                      "Compensation of employees", "Taxes on production and imports, less subsidies",
                                      "Gross operating surplus", "Total industry output"]
    assert all(dtype == "float64" for dtype in f.drop(columns="Description").dtypes)


def test_to_csv(tmp_path, toy_make, toy_use):
    toy_make.meta.update(year=2017, level="detail")
    sq = build(toy_make, toy_use)
    paths = sq.to_csv(tmp_path / "out")
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == [
        "F.csv", "V.csv", "Z.csv", "imported_final.csv", "imported_inputs.csv", "labels.csv", "market_shares.csv",
        "meta.json", "pce_import_share.csv", "square.csv", "y.csv"]

    def read(name):
        return pd.read_csv(paths[name], index_col="Code").rename_axis(None)

    pd.testing.assert_frame_equal(read("Z"), sq.Z)
    pd.testing.assert_frame_equal(read("V"), sq.V)
    pd.testing.assert_series_equal(read("y")["y"], sq.y, check_names=False)
    pd.testing.assert_frame_equal(read("square"), sq.to_frame())
    labels = pd.read_csv(paths["labels"])
    assert list(labels.columns) == ["kind", "code", "description"] and set(labels["kind"]) == {"industry", "final_demand", "commodity"}
    meta = json.loads(paths["meta"].read_text())
    assert meta["year"] == 2017 and meta["commodity_output"]["A"] == 330.0
    assert meta["diagnostics"]["nonscrap_ratio"]["A"] == pytest.approx(sq.meta["diagnostics"]["nonscrap_ratio"]["A"])
