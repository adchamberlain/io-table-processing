# tests/test_validate.py
import pandas as pd, pytest
from iotables import square, validate

def test_compare_tables_reports_violations():
    a = pd.DataFrame([[1.0, 2.0]], index=["r"], columns=["x", "y"]); b = a.copy(); b.loc["r", "y"] = 2.5
    out = validate.compare_tables(a, b)
    assert len(out) == 1 and out.iloc[0]["col"] == "y"
    with pytest.raises(ValueError):
        validate.compare_tables(a, b.rename(columns={"y": "z"}))

def test_compare_tables_aligns_by_label_within_tolerance():
    a = pd.DataFrame([[1.0, 2.0], [3.0, 4.0]], index=["r", "s"], columns=["x", "y"])
    b = a.loc[["s", "r"], ["y", "x"]] + 1e-9
    out = validate.compare_tables(a, b)
    assert out.empty and list(out.columns) == ["row", "col", "a", "b", "diff"]

def test_check_identities_raises_beyond_tolerance(toy_make, toy_use):
    sq = square.build_square_table(toy_make, toy_use, scrap="keep")
    res = validate.check_identities(sq)
    assert set(res) == {"row_minus_col", "shares_minus_one", "y_minus_rowsum"} and max(res.values()) < 1e-9
    sq.Z.loc["A", "B"] += 1.0
    with pytest.raises(ValueError, match="row_minus_col"):
        sq.check_identities()
