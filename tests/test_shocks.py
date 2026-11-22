# tests/test_shocks.py
import dataclasses
import pandas as pd
import pytest
from iotables import shocks

def test_industry_tax_rate_and_dollars_equivalent(two_by_two):
    tau1, T1 = shocks.to_tau_T([shocks.IndustryTax("1", rate=0.1)], two_by_two)
    tau2, T2 = shocks.to_tau_T([shocks.IndustryTax("1", dollars=10)], two_by_two)
    assert list(tau1) == [0.1, 0.0] and list(tau2) == [0.1, 0.0] and (T1.values == 0).all()

def test_commodity_tax_allocated_by_market_share(two_by_two):
    tau, _ = shocks.to_tau_T([shocks.CommodityTax("b", dollars=11)], two_by_two)
    assert tau["1"] == pytest.approx(0.01) and tau["2"] == pytest.approx(0.10)
    tau_r, _ = shocks.to_tau_T([shocks.CommodityTax("b", rate=0.1)], two_by_two)   # q_b = 110 -> $11
    assert tau_r["2"] == pytest.approx(0.10)

def test_flow_tax_fills_T(two_by_two):
    tau, T = shocks.to_tau_T([shocks.FlowTax("1", "2", 0.5)], two_by_two)
    assert (tau == 0).all() and T.loc["1", "2"] == 0.5 and T.values.sum() == 0.5

def test_value_added_tax(two_by_two):
    tau, _ = shocks.to_tau_T([shocks.ValueAddedTax("V00100", 0.1)], two_by_two)
    assert list(tau.round(6)) == [0.03, 0.02]
    tau2, _ = shocks.to_tau_T([shocks.ValueAddedTax("V00100", 0.1, industries=("2",))], two_by_two)
    assert list(tau2.round(6)) == [0.0, 0.02]

def test_shocks_compose_additively(two_by_two):
    tau, _ = shocks.to_tau_T([shocks.IndustryTax("1", rate=0.1), shocks.IndustryTax("1", dollars=5)], two_by_two)
    assert tau["1"] == pytest.approx(0.15)

def test_unknown_code_raises(two_by_two):
    with pytest.raises(KeyError, match="9"):
        shocks.to_tau_T([shocks.IndustryTax("9", rate=0.1)], two_by_two)
    with pytest.raises(ValueError):
        shocks.IndustryTax("1")                                   # neither dollars nor rate
    with pytest.raises(ValueError):
        shocks.IndustryTax("1", dollars=1, rate=0.1)

def test_unknown_commodity_component_and_flow_codes_raise(two_by_two):
    with pytest.raises(KeyError, match="unknown commodity code 'z'"):
        shocks.to_tau_T([shocks.CommodityTax("z", dollars=1)], two_by_two)
    with pytest.raises(KeyError, match="unknown value-added component 'V99999'"):
        shocks.to_tau_T([shocks.ValueAddedTax("V99999", 0.1)], two_by_two)
    with pytest.raises(KeyError, match="unknown industry code '9'"):
        shocks.to_tau_T([shocks.ValueAddedTax("V00100", 0.1, industries=("9",))], two_by_two)
    with pytest.raises(KeyError, match="unknown industry code '9'"):
        shocks.to_tau_T([shocks.FlowTax("1", "9", 0.5)], two_by_two)
    with pytest.raises(KeyError, match="unknown industry code '9'"):
        shocks.to_tau_T([shocks.FlowTax("9", "1", 0.5)], two_by_two)

def test_exactly_one_of_dollars_and_rate_for_commodity_tax():
    with pytest.raises(ValueError, match="exactly one"):
        shocks.CommodityTax("a")
    with pytest.raises(ValueError, match="exactly one"):
        shocks.CommodityTax("a", dollars=1, rate=0.1)

def test_flow_taxes_compose_additively(two_by_two):
    _, T = shocks.to_tau_T([shocks.FlowTax("1", "2", 0.5), shocks.FlowTax("1", "2", 0.25),
                            shocks.FlowTax("2", "1", 0.1)], two_by_two)
    assert T.loc["1", "2"] == pytest.approx(0.75) and T.loc["2", "1"] == pytest.approx(0.1)
    assert list(T.index) == ["1", "2"] and list(T.columns) == ["1", "2"]

def test_mixed_shocks_compose(two_by_two):
    tau, T = shocks.to_tau_T([shocks.IndustryTax("2", dollars=5), shocks.CommodityTax("b", dollars=11),
                              shocks.ValueAddedTax("V00100", 0.1), shocks.FlowTax("2", "1", 0.2)], two_by_two)
    assert tau["1"] == pytest.approx(0.01 + 0.03)
    assert tau["2"] == pytest.approx(0.05 + 0.10 + 0.02)
    assert T.values.sum() == pytest.approx(0.2)

def test_empty_shocks_give_zero_tau_and_T(two_by_two):
    tau, T = shocks.to_tau_T([], two_by_two)
    assert list(tau.index) == ["1", "2"] and (tau == 0).all() and T.shape == (2, 2) and (T.values == 0).all()

def test_industry_dollars_converts_rates_to_dollars(two_by_two):
    d = shocks.industry_dollars([shocks.IndustryTax("1", rate=0.1),                  # 0.1 * y_1 = 10
                                 shocks.CommodityTax("b", rate=0.1),                 # 0.1 * q_b = 11, split 1 : 10
                                 shocks.ValueAddedTax("V00100", 0.1, ("1",)),        # 0.1 * 30 = 3
                                 shocks.FlowTax("1", "2", 0.5)], two_by_two)         # not an industry-dollar shock
    assert list(d.index) == ["1", "2"]
    assert d["1"] == pytest.approx(10 + 1 + 3) and d["2"] == pytest.approx(10)

def test_industry_dollars_zeros_elsewhere_and_no_shocks(two_by_two):
    d = shocks.industry_dollars([shocks.IndustryTax("2", dollars=7)], two_by_two)
    assert list(d) == [0.0, 7.0]
    assert (shocks.industry_dollars([], two_by_two) == 0).all()

def test_inputs_are_not_mutated(two_by_two):
    before = two_by_two.market_shares.copy()
    shocks.to_tau_T([shocks.CommodityTax("b", dollars=11), shocks.ValueAddedTax("V00100", 0.1)], two_by_two)
    pd.testing.assert_frame_equal(two_by_two.market_shares, before)

def test_shock_on_zero_output_industry_raises_naming_it(two_by_two):
    sq = dataclasses.replace(two_by_two, y=pd.Series({"1": 0.0, "2": 100.0}))
    with pytest.raises(ValueError, match="'1'"):
        shocks.to_tau_T([shocks.IndustryTax("1", dollars=10)], sq)
    with pytest.raises(ValueError, match="'1'"):
        shocks.to_tau_T([shocks.IndustryTax("1", rate=0.1)], sq)       # a rate on zero output is still a shock
    with pytest.raises(ValueError, match="'1'"):
        shocks.to_tau_T([shocks.CommodityTax("b", dollars=11)], sq)    # $1 of it lands on industry 1
    tau, _ = shocks.to_tau_T([shocks.IndustryTax("2", rate=0.1), shocks.IndustryTax("1", dollars=0)], sq)
    assert list(tau) == [0.0, 0.1]                                     # zero shocks and other industries are fine

def test_commodity_rate_needs_commodity_output(two_by_two):
    sq = dataclasses.replace(two_by_two, meta={"year": 2017})
    with pytest.raises(ValueError, match="commodity_output"):
        shocks.to_tau_T([shocks.CommodityTax("b", rate=0.1)], sq)
    tau, _ = shocks.to_tau_T([shocks.CommodityTax("b", dollars=11)], sq)   # dollars do not need it
    assert tau["2"] == pytest.approx(0.10)

def test_unrecognised_shock_raises(two_by_two):
    with pytest.raises(TypeError, match="shock"):
        shocks.to_tau_T([("1", 0.1)], two_by_two)
