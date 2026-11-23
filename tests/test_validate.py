import pytest

from iotables import validate


def test_check_identities_raises_beyond_tolerance(toy_square):
    res = validate.check_identities(toy_square)
    assert set(res) == {"row_minus_col", "shares_minus_one", "y_minus_rowsum"} and max(res.values()) < 1e-9
    toy_square.Z.loc["A", "B"] += 1.0
    with pytest.raises(ValueError, match="row_minus_col"):
        toy_square.check_identities()
