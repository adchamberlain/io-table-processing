# tests/test_square.py
import numpy as np, pandas as pd, pytest
from iotables import square, parse
from conftest import add_use_row, add_make_column

def test_market_shares_columns_sum_to_one(toy_make):
    ms = square.market_shares(toy_make.values)
    assert np.allclose(ms.sum(axis=0), 1.0)
    assert ms.loc["A", "A"] == pytest.approx(300 / 330)

def test_market_shares_zero_output_column_is_zero():
    m = pd.DataFrame([[1.0, 0.0], [1.0, 0.0]], index=["i", "j"], columns=["a", "b"])
    ms = square.market_shares(m)
    assert (ms["b"] == 0).all() and not ms.isna().any().any()

def test_build_keep_mode_identities(toy_make, toy_use):
    sq = square.build_square_table(toy_make, toy_use, scrap="keep")
    assert sq.Z.shape == (3, 3) and list(sq.F.columns) == ["F01000"] and list(sq.V.index) == ["V00100", "V00200", "V00300"]
    res = sq.check_identities()
    assert res["row_minus_col"] < 1e-9
    assert sq.y.sum() == pytest.approx(328 + 412 + 265)       # scrap kept as a commodity: totals preserved
    assert sq.meta["diagnostics"]["scrap_mode"] == "keep"

def test_build_reorders_by_code(toy_make, toy_use):
    use2 = parse.UseTable(**{**toy_use.__dict__, "intermediate": toy_use.intermediate[["C", "A", "B"]],
                             "value_added": toy_use.value_added[["C", "A", "B"]]})
    a = square.build_square_table(toy_make, toy_use, scrap="keep"); b = square.build_square_table(toy_make, use2, scrap="keep")
    pd.testing.assert_frame_equal(a.Z, b.Z)

def test_build_rejects_industry_mismatch(toy_make, toy_use):
    bad = parse.UseTable(**{**toy_use.__dict__, "intermediate": toy_use.intermediate.rename(columns={"C": "Q"}),
                            "value_added": toy_use.value_added.rename(columns={"C": "Q"})})
    with pytest.raises(ValueError, match="Q"):
        square.build_square_table(toy_make, bad, scrap="keep")

def test_zero_output_commodity(toy_make, toy_use):
    # commodity "Z" used by nobody and made by nobody -> fine; used by somebody -> error
    use_zero = add_use_row(toy_use, "Z", [0, 0, 0], fd=[0]); use_pos = add_use_row(toy_use, "Z", [1, 0, 0], fd=[0])
    square.build_square_table(toy_make, use_zero, scrap="keep")
    with pytest.raises(ValueError, match="Z"):
        square.build_square_table(toy_make, use_pos, scrap="keep")

def test_build_keep_mode_values_and_meta(toy_make, toy_use):
    toy_make.meta.update(year=2017, level="detail", redefinitions="after")
    sq = square.build_square_table(toy_make, toy_use, scrap="keep")
    # hand-computed from BEA manual tables 12.5/12.7: Z_AA = sum_c (M_Ac / q_c) U_cA, scrap included
    assert sq.Z.loc["A", "A"] == pytest.approx(300 / 330 * 50 + 25 / 400 * 180 + 3 / 5 * 1)
    assert sq.F.loc["B", "F01000"] == pytest.approx(30 / 330 * 40 + 360 / 400 * 130 + 20 / 270 * 20)
    assert list(sq.y.round(9)) == [328, 412, 265] and list(sq.V.loc["V00300"].round(9)) == [47, 109, 34]
    assert sq.industries == ["A", "B", "C"] and sq.n == 3
    assert sq.meta["year"] == 2017 and sq.meta["level"] == "detail" and sq.meta["redefinitions"] == "after"
    assert sq.meta["source"] == {"make": toy_make.meta, "use": toy_use.meta}
    pd.testing.assert_series_equal(sq.meta["commodity_output"],
                                   pd.Series([330.0, 400.0, 270.0, 5.0], index=["A", "B", "C", "S00401"]), check_names=False)
    d = sq.meta["diagnostics"]
    assert d["dropped"] == {} and d["y_minus_g"].abs().max() < 1e-9 and d["gos_minus_bea"].abs().max() < 1e-9
    assert sq.commodity_labels["S00401"] == "Scrap" and sq.final_demand_labels["F01000"] == "Personal consumption expenditures"

def test_build_rejects_make_only_commodity(toy_make, toy_use):
    with pytest.raises(ValueError, match=r"\['X'\]"):
        square.build_square_table(add_make_column(toy_make, "X", [1, 0, 0]), toy_use, scrap="keep")

def test_drop_codes_removed_and_recorded_keep_mode(toy_make, toy_use):
    make2 = add_make_column(add_make_column(toy_make, "S00300", [0, 0, 0]), "S00900", [0, 3, 0])
    use2 = add_use_row(add_use_row(toy_use, "S00300", [2, 0, 0], fd=[-2]), "S00900", [0, 0, 0], fd=[3])
    sq = square.build_square_table(make2, use2, scrap="keep")
    d = sq.meta["diagnostics"]
    assert d["dropped"] == {"S00300": {"intermediate": 2.0, "final_demand": -2.0},
                            "S00900": {"intermediate": 0.0, "final_demand": 3.0}}
    assert d["dropped_make_output"] == {"S00300": 0.0, "S00900": 3.0}
    assert not {"S00300", "S00900"} & set(sq.market_shares.columns)
    assert sq.check_identities()["row_minus_col"] < 1e-9

def test_zero_make_column_with_nonzero_use_rejected(toy_make, toy_use):
    # spec 7.4: q = 0 requires zero use, also when the make column exists (S00300 kept here by drop=())
    make2 = add_make_column(toy_make, "S00300", [0, 0, 0]); use2 = add_use_row(toy_use, "S00300", [2, 0, 0], fd=[-2])
    with pytest.raises(ValueError, match=r"\['S00300'\]"):
        square.build_square_table(make2, use2, scrap="keep", drop=())

def test_build_rejects_unknown_scrap_mode(toy_make, toy_use):
    with pytest.raises(ValueError, match="bogus"):
        square.build_square_table(toy_make, toy_use, scrap="bogus")
