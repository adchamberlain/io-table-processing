# tests/test_end_to_end.py
import json
import pandas as pd
import pytest
from iotables import cli

@pytest.mark.network
def test_carbon_50_on_2017_detail(tmp_path):
    rc = cli.main(["run", "--year", "2017", "--carbon", "50", "--emissions-year", "2024", "--out", str(tmp_path)])
    assert rc == 0
    s = json.loads((tmp_path / "summary.json").read_text())
    assert abs(s["identity_residual"]) < 1e-6 * s["total_tax"]
    # pce_share_of_burden is relative to the tax. Imports enter final demand as a negative column, so they carry a
    # negative burden and the positive components (PCE, investment, government, exports) together bear more than the
    # tax: PCE's share of the tax can come close to 1 (0.965 here) while its share of the positive burden is near half.
    assert 0.3 < s["pce_share_of_burden"] < 1.0
    fd = pd.read_csv(tmp_path / "burden_by_final_demand.csv").set_index("code")["burden"]
    without_imports = fd.drop(index="F05000")                         # imports of goods and services
    assert fd["F05000"] < 0 and without_imports.sum() > s["total_tax"]
    assert 0.3 < s["pce_burden"] / without_imports.sum() < 0.9
    pce = pd.read_csv(tmp_path / "pce_prices.csv")
    top = pce.sort_values("price_change", ascending=False).head(5)["pce_category"].str.lower().str.cat(sep=" ")
    assert "gas" in top or "electric" in top or "fuel" in top         # energy categories must lead
