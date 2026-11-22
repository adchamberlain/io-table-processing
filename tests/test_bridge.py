# tests/test_bridge.py
import openpyxl
import pytest
from iotables import bridge
from conftest import write_pce_bridge_workbook

def test_parse_pce_bridge_synthetic(tmp_path):   # write a tiny workbook in the BEA bridge layout with 3 rows, 2 NIPA lines
    b = bridge.parse_pce_bridge(write_pce_bridge_workbook(tmp_path / "b.xlsx"), 2017)
    assert list(b.rows.columns) == ["nipa_line", "pce_category", "commodity", "commodity_desc", "producers_value", "transport", "wholesale", "retail", "purchasers_value"]
    assert b.rows["nipa_line"].tolist() == ["7", "7", "13"] and b.categories().shape[0] == 2

def test_parse_pce_bridge_codes_values_and_categories(tmp_path):
    b = bridge.parse_pce_bridge(write_pce_bridge_workbook(tmp_path / "b.xlsx"))       # "latest" = the 2017 sheet
    assert b.year == 2017 and b.rows["commodity"].tolist() == ["336111", "336211", "S00401"]
    assert b.rows.loc[0, ["producers_value", "transport", "wholesale", "retail", "purchasers_value"]].tolist() == [14874.0, 711.0, 4699.0, 31275.0, 51558.0]
    c = b.categories()
    assert list(c.columns) == ["nipa_line", "pce_category", "purchasers_value"]
    assert c.values.tolist() == [["7", "New domestic autos", 51958.0], ["13", "Used autos", -10652.0]]

def test_parse_pce_bridge_rejects_unexpected_layout(tmp_path):
    p = write_pce_bridge_workbook(tmp_path / "b.xlsx")
    wb = openpyxl.load_workbook(p); wb["2017"].cell(4, 9).value = None; wb.save(p)       # no "Purchasers' Value" label
    with pytest.raises(ValueError, match="purchasers' value"):
        bridge.parse_pce_bridge(p, 2017)
    with pytest.raises(ValueError, match="2012"):
        bridge.parse_pce_bridge(write_pce_bridge_workbook(tmp_path / "c.xlsx"), 2012)

@pytest.mark.network
def test_parse_pce_bridge_2017_detail():
    b = bridge.load_pce_bridge("detail", 2017)
    assert b.rows["nipa_line"].nunique() == 212 and b.rows["commodity"].nunique() == 259
    assert (b.rows["purchasers_value"] - b.rows[["producers_value", "transport", "wholesale", "retail"]].sum(axis=1)).abs().max() <= 1.0
