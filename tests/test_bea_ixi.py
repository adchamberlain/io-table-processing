# tests/test_bea_ixi.py
import dataclasses
import numpy as np, pandas as pd, pytest
from iotables import download, parse, sources, square, validate

def test_ixi_total_requirements_inverts_i_minus_a(toy_make, toy_use):
    sq = square.build_square_table(toy_make, toy_use, scrap="bea")
    L = validate.ixi_total_requirements(sq)
    assert list(L.index) == list(L.columns) == sq.industries
    A = sq.Z.to_numpy() / sq.y.to_numpy()          # A_ij = Z_ij / y_j: buyer j's input from i per dollar of j's output
    assert np.allclose((np.eye(sq.n) - A) @ L.to_numpy(), np.eye(sq.n), rtol=0, atol=1e-12)
    assert (np.diag(L.to_numpy()) >= 1).all()

def test_ixi_total_requirements_aligns_by_code(toy_make, toy_use):
    sq = square.build_square_table(toy_make, toy_use, scrap="bea")
    shuffled = dataclasses.replace(sq, Z=sq.Z.loc[:, ["C", "A", "B"]], y=sq.y.loc[["B", "C", "A"]])
    pd.testing.assert_frame_equal(validate.ixi_total_requirements(shuffled), validate.ixi_total_requirements(sq))

def test_ixi_total_requirements_rejects_zero_output(toy_make, toy_use):
    sq = square.build_square_table(toy_make, toy_use, scrap="bea")
    with pytest.raises(ValueError, match=r"\['C'\]"):
        validate.ixi_total_requirements(dataclasses.replace(sq, y=sq.y.where(sq.y.index != "C", 0.0)))

def test_ixi_total_requirements_rejects_nonsquare_z(toy_make, toy_use):
    sq = square.build_square_table(toy_make, toy_use, scrap="bea")
    with pytest.raises(ValueError, match="Q"):
        validate.ixi_total_requirements(dataclasses.replace(sq, Z=sq.Z.rename(columns={"C": "Q"})))

def _abs_diff_from_published(redefinitions, **build_options):
    """|ours - BEA| for the 2017 detail table built with `build_options`, against BEA's published IxI table."""
    make, use = parse.load_bea_tables("detail", 2017, redefinitions)
    sq = square.build_square_table(make, use, **build_options)
    ours = validate.ixi_total_requirements(sq)
    bea = parse.read_bea_grid(download.fetch(sources.bea_detail_url("ixi_tr", "any"), sources.RAW_DIR / "bea"), "2017").values
    bea = bea.loc[ours.index, ours.columns]
    return (ours - bea).abs()

@pytest.mark.network
@pytest.mark.parametrize("redefinitions", ["after", "before"])
def test_bea_mode_reproduces_bea_industry_by_industry_requirements(redefinitions, record_property):
    """BEA's published 2017 IxI total requirements follow scrap="bea" with scrap_codes=("S00402",) on after-redefinitions inputs: scrap S00401 is an ordinary commodity and used goods S00402 are removed."""
    diff = _abs_diff_from_published(redefinitions, scrap="bea", scrap_codes=("S00402",))
    record_property(f"max_abs_diff_{redefinitions}", float(diff.values.max()))
    print(f"published convention, {redefinitions}: max {diff.values.max():.2e} mean {diff.values.mean():.2e}")
    if redefinitions == "after":          # the documented default must match
        assert diff.values.max() < 1e-3
    else:                                 # and the other inputs must not: the data pins 'after'
        assert diff.values.max() >= 1e-3

@pytest.mark.network
def test_default_bea_mode_difference_from_published_requirements(record_property):
    """The default build (nonscrap ratio for S00401 and S00402) against the published table: recorded, not bounded."""
    diff = _abs_diff_from_published("after", scrap="bea")
    record_property("max_abs_diff_default_bea_after", float(diff.values.max()))
    print(f"default bea, after: max {diff.values.max():.2e} mean {diff.values.mean():.2e}")
    assert diff.shape == (402, 402) and np.isfinite(diff.values).all()
