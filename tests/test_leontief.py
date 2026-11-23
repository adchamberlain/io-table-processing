# tests/test_leontief.py
import dataclasses
import numpy as np
import pandas as pd
import pytest
from iotables import bridge, leontief, costs, square

def test_baseline_is_ones(two_by_two):
    assert np.allclose(leontief.PriceModel(two_by_two).baseline_prices().values, 1.0)

def test_cost_on_an_industry(two_by_two):
    r = leontief.PriceModel(two_by_two).run([costs.IndustryCost("1", rate=0.1)])
    assert np.allclose(r.industry_prices["price_change"].values, [0.125, 0.0416667], atol=1e-6)
    assert r.burden_by_final_demand.loc[0, "burden"] == pytest.approx(10.0)       # 0.125*70 + 0.0416667*30
    assert r.summary["total_cost"] == pytest.approx(10.0) and abs(r.summary["identity_residual"]) < 1e-9

def test_price_model_rejects_zero_output(two_by_two):
    with pytest.raises(ValueError, match="zero output"):
        leontief.PriceModel(dataclasses.replace(two_by_two, y=pd.Series({"1": 100.0, "2": 0.0})))

def test_price_model_rejects_an_unbalanced_table(two_by_two):
    Z = two_by_two.Z.copy(); Z.loc["1", "2"] += 1.0                                  # row 1 and column 2 sum to 101
    with pytest.raises(ValueError, match="row_minus_col"):
        leontief.PriceModel(dataclasses.replace(two_by_two, Z=Z))

def test_baseline_uses_the_value_added_rows(two_by_two):
    V = two_by_two.V.copy(); V.loc["V00300", "2"] += 5e-7                            # within check_identities' 1e-6
    with pytest.raises(ValueError, match=r"baseline prices are not 1 .*industry '2'"):  # p - 1 = [3.1e-9, 9.4e-9]
        leontief.PriceModel(dataclasses.replace(two_by_two, V=V))

def test_price_model_rejects_bad_margin_codes(two_by_two):
    b = synthetic_bridge()
    with pytest.raises(ValueError, match=r"exactly the keys .*missing \['retail'\], unexpected \[\]"):
        leontief.PriceModel(two_by_two, pce_bridge=b, margin_codes={"transport": ["b"], "wholesale": ["b"]})
    with pytest.raises(ValueError, match=r"missing \[\], unexpected \['trade'\]"):
        leontief.PriceModel(two_by_two, pce_bridge=b,
                            margin_codes={"transport": ["b"], "wholesale": ["b"], "retail": ["b"], "trade": ["a"]})
    with pytest.raises(ValueError, match=r"margin_codes\['wholesale'\]: none of \['zzz'\]"):
        leontief.PriceModel(two_by_two, pce_bridge=b, margin_codes={"transport": ["b"], "wholesale": ["zzz"], "retail": ["a"]})
    no_b = {**two_by_two.meta, "commodity_output": pd.Series({"a": 90.0, "b": 0.0})}  # "b" has no output
    with pytest.raises(ValueError, match=r"margin_codes\['transport'\]"):
        leontief.PriceModel(dataclasses.replace(two_by_two, meta=no_b), pce_bridge=b,
                            margin_codes={"transport": ["b"], "wholesale": ["a"], "retail": ["a"]})

def synthetic_bridge():
    rows = pd.DataFrame([["1", "Thing", "a", "Alpha", 80, 5, 5, 10, 100],
                         ["2", "Other", "b", "Beta", 50, 0, 0, 0, 50],
                         ["3", "Missing", "zzz", "Gone", 10, 0, 0, 0, 10]],
                        columns=["nipa_line", "pce_category", "commodity", "commodity_desc", "producers_value", "transport", "wholesale", "retail", "purchasers_value"])
    return bridge.PCEBridge(rows=rows, year=2017, meta={})

def test_commodity_and_pce_prices(two_by_two):
    m = leontief.PriceModel(two_by_two, pce_bridge=synthetic_bridge(), margin_codes={"transport": ["b"], "wholesale": ["b"], "retail": ["b"]})
    r = m.run([costs.IndustryCost("1", rate=0.1)])
    c = r.commodity_prices.set_index("code")["price_change"]
    assert c["a"] == pytest.approx(0.125) and c["b"] == pytest.approx(0.0492424, abs=1e-6)
    p = r.pce_prices.set_index("nipa_line")
    assert p.loc["1", "price_change"] == pytest.approx(0.10984848, abs=1e-6)       # (80*.125 + 20*.0492424)/100
    assert p.loc["2", "price_change"] == pytest.approx(0.0492424, abs=1e-6)
    assert p.loc["3", "price_change"] == 0.0
    assert r.summary["pce_burden"] == pytest.approx(13.44697, abs=1e-4)
    assert any("zzz" in n for n in r.notes)

def test_bridge_missing_commodity_noted(two_by_two):
    b = synthetic_bridge(); b.rows.loc[b.rows.nipa_line == "2", "purchasers_value"] = 0
    r = leontief.PriceModel(two_by_two, pce_bridge=b, margin_codes={"transport": ["b"], "wholesale": ["b"], "retail": ["b"]}).run([costs.IndustryCost("1", rate=0.1)])
    assert r.pce_prices.set_index("nipa_line").loc["2", "price_change"] == 0.0 and any("purchasers" in n for n in r.notes)

def test_pce_frames_summary_and_notes(two_by_two):
    rows = synthetic_bridge().rows.iloc[[2, 1, 0]]                                   # lines 3, 2, 1: sorted back by number
    m = leontief.PriceModel(two_by_two, pce_bridge=bridge.PCEBridge(rows=rows, year=2017, meta={}),
                            margin_codes={"transport": ["b"], "wholesale": ["b"], "retail": ["b"]})
    r = m.run([costs.IndustryCost("1", rate=0.1)])
    assert list(r.commodity_prices.columns) == ["code", "description", "price_change"]
    assert r.commodity_prices["description"].tolist() == ["Alpha", "Beta"]
    assert list(r.pce_prices.columns) == ["nipa_line", "pce_category", "price_change", "base_spending", "burden"]
    assert r.pce_prices["nipa_line"].tolist() == ["1", "2", "3"] and r.pce_prices["base_spending"].tolist() == [100.0, 50.0, 10.0]
    assert r.summary["pce_share_of_cost"] == pytest.approx(r.summary["pce_burden"] / 10.0)
    assert len(r.notes) == 1                                                         # one note for "zzz"
    plain = leontief.PriceModel(two_by_two).run([costs.IndustryCost("1", rate=0.1)])
    assert plain.pce_prices is None and plain.summary["pce_burden"] is None and plain.summary["pce_share_of_cost"] is None
    assert plain.commodity_prices.equals(r.commodity_prices) and plain.notes == []

def test_margin_price_changes(two_by_two):
    dp_c = pd.Series({"a": 0.1, "b": 0.2})
    m = leontief.PriceModel(two_by_two, margin_codes={"transport": ["a", "b", "absent"], "wholesale": ["b"], "retail": ["a"]})
    assert m.margin_price_changes(dp_c) == pytest.approx({"transport": (90 * 0.1 + 110 * 0.2) / 200, "wholesale": 0.2, "retail": 0.1})
    with pytest.raises(ValueError, match="retail"):
        leontief.PriceModel(two_by_two, margin_codes={"transport": ["a"], "wholesale": ["b"], "retail": ["absent"]}).margin_price_changes(dp_c)
    with pytest.raises(ValueError, match="margin_codes"):                             # level "toy" has no built-in margin codes
        leontief.PriceModel(two_by_two, pce_bridge=synthetic_bridge()).run([costs.IndustryCost("1", rate=0.1)])
    assert bridge.MARGIN_CODES["detail"]["retail"][-1] == "4B0000"

