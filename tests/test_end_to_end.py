"""The carbon example on BEA's 2017 detail tables, from download to consumer prices."""

import pandas as pd
import pytest

from iotables import PriceModel, build_square_table, load_bea_tables, load_import_matrix, load_pce_bridge, shocks


@pytest.mark.network
def test_carbon_50_on_2017_detail(tmp_path):
    sq = build_square_table(*load_bea_tables("detail", 2017), imports=load_import_matrix("detail", 2017))
    model = PriceModel(sq, pce_bridge=load_pce_bridge("detail", 2017))
    result = model.run(shocks.carbon_price(dollars_per_ton_co2=50, emissions_year=2024, sq=sq))
    s = result.summary
    assert abs(s["identity_residual"]) < 1e-6 * s["total_tax"]
    # The table separates imports from domestic purchases, so every component of final demand bears a
    # share of the cost and the shares sum to it. What is left in the imports column is BEA's
    # reconciliation of duties and freight, a small amount.
    assert 0.3 < s["pce_share_of_burden"] < 0.9
    fd = result.burden_by_final_demand.set_index("code")["burden"]
    assert fd.sum() == pytest.approx(s["total_tax"], rel=1e-6)
    assert abs(fd["F05000"]) < 0.01 * s["total_tax"] and fd["F04000"] > 0      # imports column; exports
    pce = pd.read_csv(result.to_csv(tmp_path)["pce_prices"])
    top = pce.sort_values("price_change", ascending=False).head(5)["pce_category"].str.lower().str.cat(sep=" ")
    assert "gas" in top or "electric" in top or "fuel" in top         # energy categories must lead
    # $50 per ton is about $0.44 per gallon of gasoline, some 18 percent of the 2017 pump price.
    gasoline = pce.loc[pce["pce_category"] == "Gasoline and other motor fuel", "price_change"].item()
    assert 0.15 < gasoline < 0.22
