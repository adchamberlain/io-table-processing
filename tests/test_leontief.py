# tests/test_leontief.py
import dataclasses
import numpy as np
import pandas as pd
import pytest
from iotables import bridge, leontief, shocks
from conftest import build_2002_summary

def test_baseline_is_ones(two_by_two):
    assert np.allclose(leontief.PriceModel(two_by_two).baseline_prices().values, 1.0)

def test_output_tax_on_industry(two_by_two):
    r = leontief.PriceModel(two_by_two).run([shocks.IndustryTax("1", rate=0.1)])
    assert np.allclose(r.industry_prices["pct_change"].values, [0.125, 0.0416667], atol=1e-6)
    assert r.burden_by_final_demand.loc[0, "burden"] == pytest.approx(10.0)       # 0.125*70 + 0.0416667*30
    assert r.summary["total_tax"] == pytest.approx(10.0) and abs(r.summary["identity_residual"]) < 1e-9

def test_flow_tax(two_by_two):
    r = leontief.PriceModel(two_by_two).run([shocks.FlowTax("1", "2", 0.5)])
    assert np.allclose(r.industry_prices["pct_change"].values, [0.0666667, 0.2], atol=1e-6)
    assert r.summary["total_tax"] == pytest.approx(10.6666667, abs=1e-6)         # 0.5*20*1.0666667
    assert abs(r.summary["identity_residual"]) < 1e-9

def test_wp6_formulation(two_by_two):
    m = leontief.PriceModel(two_by_two, formulation="wp6")
    r = m.run([shocks.IndustryTax("1", dollars=3)])                                # t_1 = 3/30 = 0.1
    assert np.allclose(r.industry_prices["pct_change"].values, [0.0256410, 0.0427350], atol=1e-6)
    r2 = m.run([shocks.IndustryTax("1", rate=0.1)])
    assert np.allclose(r2.industry_prices["pct_change"].values, r.industry_prices["pct_change"].values)
    with pytest.raises(ValueError):
        m.run([shocks.FlowTax("1", "2", 0.1)])

def test_wp6_replicates_2009_price_impacts():
    """Distributional Model.xlsx, Pi sheet column E, with Policy Inputs L10/L11 as rates (spec §9)."""
    sq = build_2002_summary()                                   # helper in conftest using the Task 8 fixtures (keep mode)
    r = leontief.PriceModel(sq, formulation="wp6").run([shocks.IndustryTax("2110", rate=0.3954367423979727),
                                                         shocks.IndustryTax("2121", rate=1.8694564238089508)])
    p = r.industry_prices.set_index("code")["pct_change"] + 1
    for code, expected in {"1110": 1.0249967298379448, "2110": 1.0202324094628146, "2121": 1.1472503329037465,
                           "2211": 1.1650275425430783, "2212": 1.185103762352647, "S007": 1.0104328673003136}.items():
        assert p[code] == pytest.approx(expected, abs=1e-6)

def test_output_tax_identity_on_2002_table():
    """Every shock type at once on a real table: the burden on final demand equals the tax (spec 8.3)."""
    sq = build_2002_summary()
    r = leontief.PriceModel(sq).run([shocks.IndustryTax("2110", dollars=5000), shocks.CommodityTax("3240", rate=0.05),
                                     shocks.FlowTax("2211", "331A", 0.1), shocks.ValueAddedTax("V00100", 0.01)])
    assert r.summary["formulation"] == "output_tax" and r.summary["total_tax"] > 5000
    assert abs(r.summary["identity_residual"]) < 1e-9 * r.summary["total_tax"]
    assert list(r.burden_by_final_demand.columns) == ["code", "description", "base_spending", "burden"]
    assert list(r.industry_prices["code"]) == sq.industries

def test_price_model_rejects_bad_inputs(two_by_two):
    with pytest.raises(ValueError, match="formulation"):
        leontief.PriceModel(two_by_two, formulation="leontief")
    with pytest.raises(ValueError, match="zero output"):
        leontief.PriceModel(dataclasses.replace(two_by_two, y=pd.Series({"1": 100.0, "2": 0.0})))
    no_sales = dataclasses.replace(two_by_two, Z=pd.DataFrame([[10.0, 20.0], [0.0, 0.0]], index=["1", "2"], columns=["1", "2"]),
                                   F=pd.DataFrame({"F01000": [70.0, 100.0]}, index=["1", "2"]))
    with pytest.raises(ValueError, match="intermediate sales"):                     # industry 2 sells nothing to industries
        leontief.PriceModel(no_sales, formulation="wp6").run([shocks.IndustryTax("2", dollars=1)])

def synthetic_bridge():
    rows = pd.DataFrame([["1", "Thing", "a", "Alpha", 80, 5, 5, 10, 100],
                         ["2", "Other", "b", "Beta", 50, 0, 0, 0, 50],
                         ["3", "Missing", "zzz", "Gone", 10, 0, 0, 0, 10]],
                        columns=["nipa_line", "pce_category", "commodity", "commodity_desc", "producers_value", "transport", "wholesale", "retail", "purchasers_value"])
    return bridge.PCEBridge(rows=rows, year=2017, meta={})

def test_commodity_and_pce_prices(two_by_two):
    m = leontief.PriceModel(two_by_two, pce_bridge=synthetic_bridge(), margin_codes={"transport": ["b"], "wholesale": ["b"], "retail": ["b"]})
    r = m.run([shocks.IndustryTax("1", rate=0.1)])
    c = r.commodity_prices.set_index("code")["pct_change"]
    assert c["a"] == pytest.approx(0.125) and c["b"] == pytest.approx(0.0492424, abs=1e-6)
    p = r.pce_prices.set_index("nipa_line")
    assert p.loc["1", "pct_change"] == pytest.approx(0.10984848, abs=1e-6)       # (80*.125 + 20*.0492424)/100
    assert p.loc["2", "pct_change"] == pytest.approx(0.0492424, abs=1e-6)
    assert p.loc["3", "pct_change"] == 0.0
    assert r.summary["pce_burden"] == pytest.approx(13.44697, abs=1e-4)
    assert any("zzz" in n for n in r.notes)

def test_bridge_missing_commodity_noted(two_by_two):
    b = synthetic_bridge(); b.rows.loc[b.rows.nipa_line == "2", "purchasers_value"] = 0
    r = leontief.PriceModel(two_by_two, pce_bridge=b, margin_codes={"transport": ["b"], "wholesale": ["b"], "retail": ["b"]}).run([shocks.IndustryTax("1", rate=0.1)])
    assert r.pce_prices.set_index("nipa_line").loc["2", "pct_change"] == 0.0 and any("purchasers" in n for n in r.notes)

def test_pce_frames_summary_and_notes(two_by_two):
    rows = synthetic_bridge().rows.iloc[[2, 1, 0]]                                   # lines 3, 2, 1: sorted back by number
    m = leontief.PriceModel(two_by_two, pce_bridge=bridge.PCEBridge(rows=rows, year=2017, meta={}),
                            margin_codes={"transport": ["b"], "wholesale": ["b"], "retail": ["b"]})
    r = m.run([shocks.IndustryTax("1", rate=0.1)])
    assert list(r.commodity_prices.columns) == ["code", "description", "pct_change"]
    assert r.commodity_prices["description"].tolist() == ["Alpha", "Beta"]
    assert list(r.pce_prices.columns) == ["nipa_line", "pce_category", "pct_change", "base_spending", "burden"]
    assert r.pce_prices["nipa_line"].tolist() == ["1", "2", "3"] and r.pce_prices["base_spending"].tolist() == [100.0, 50.0, 10.0]
    assert r.summary["pce_share_of_burden"] == pytest.approx(r.summary["pce_burden"] / 10.0)
    assert len(r.notes) == 1                                                         # one note for "zzz"
    plain = leontief.PriceModel(two_by_two).run([shocks.IndustryTax("1", rate=0.1)])
    assert plain.pce_prices is None and plain.summary["pce_burden"] is None and plain.summary["pce_share_of_burden"] is None
    assert plain.commodity_prices.equals(r.commodity_prices) and plain.notes == []

def test_margin_price_changes(two_by_two):
    dp_c = pd.Series({"a": 0.1, "b": 0.2})
    m = leontief.PriceModel(two_by_two, margin_codes={"transport": ["a", "b", "absent"], "wholesale": ["b"], "retail": ["a"]})
    assert m.margin_price_changes(dp_c) == pytest.approx({"transport": (90 * 0.1 + 110 * 0.2) / 200, "wholesale": 0.2, "retail": 0.1})
    with pytest.raises(ValueError, match="retail"):
        leontief.PriceModel(two_by_two, margin_codes={"transport": ["a"], "wholesale": ["b"], "retail": ["absent"]}).margin_price_changes(dp_c)
    with pytest.raises(ValueError, match="margin_codes"):                             # level "toy" has no built-in margin codes
        leontief.PriceModel(two_by_two, pce_bridge=synthetic_bridge()).run([shocks.IndustryTax("1", rate=0.1)])
    assert bridge.MARGIN_CODES["detail"]["retail"][-1] == "4B0000"

def test_table_without_commodity_output_gives_industry_prices_only(two_by_two):
    meta = {k: v for k, v in two_by_two.meta.items() if k != "commodity_output"}
    bare = dataclasses.replace(two_by_two, meta=meta, market_shares=two_by_two.market_shares.iloc[:, :0],
                               N=two_by_two.N.iloc[:, :0], commodity_labels=pd.Series(dtype=object))
    r = leontief.PriceModel(bare).run([shocks.IndustryTax("1", rate=0.1)])
    full = leontief.PriceModel(two_by_two).run([shocks.IndustryTax("1", rate=0.1)])
    pd.testing.assert_frame_equal(r.industry_prices, full.industry_prices)
    pd.testing.assert_frame_equal(r.burden_by_final_demand, full.burden_by_final_demand)
    assert r.commodity_prices is None and r.pce_prices is None and r.summary == full.summary
    with pytest.raises(ValueError, match="commodity_output"):
        leontief.PriceModel(bare, pce_bridge=synthetic_bridge(), margin_codes={"transport": ["b"], "wholesale": ["b"], "retail": ["b"]})
