# tests/test_leontief.py
import dataclasses
import numpy as np
import pandas as pd
import pytest
from iotables import leontief, shocks
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
