# tests/test_parse.py
import pytest
from iotables import parse
from conftest import write_bea_workbook

def test_normalize_code():
    assert parse.normalize_code(111200) == "111200"
    assert parse.normalize_code(1110.0) == "1110"
    assert parse.normalize_code(" TRADE ") == "TRADE"
    assert parse.normalize_code(None) is None and parse.normalize_code("  ") is None

def test_read_bea_grid_basic(tmp_path):
    p = tmp_path / "make.xlsx"
    write_bea_workbook(p, col_codes=["A", "B", "T008"], col_descs=["Alpha", "Beta", "Total Industry Output"],
                       rows=[("A", "Alpha ind", [300, 25, 325]), ("B", "Beta ind", [None, 360, 360]), ("T007", "Total Commodity Output", [300, 385, None])])
    g = parse.read_bea_grid(p, "2017")
    assert list(g.values.index) == ["A", "B", "T007"] and list(g.values.columns) == ["A", "B", "T008"]
    assert g.values.loc["B", "A"] == 0.0 and g.values.loc["A", "T008"] == 325.0
    assert g.row_labels["A"] == "Alpha ind" and g.col_labels["T008"] == "Total Industry Output"
    assert g.title.startswith("Make Table")

@pytest.mark.parametrize("header_row,int_codes", [(5, False), (7, True), (4, True)])
def test_read_bea_grid_tolerates_layout_shifts(tmp_path, header_row, int_codes):
    p = tmp_path / "use.xlsx"
    write_bea_workbook(p, header_row=header_row, int_codes=int_codes, row_label="Commodity Description",
                       col_codes=["111200", "T001", "F01000", None, None], 
                       col_descs=["Veg", "Total Intermediate", "PCE", "Total Final Uses (GDP)", "Total Commodity Output"],
                       rows=[("111200", "Veg", [1, 1, 5, 5, 6]), ("V00100", "Compensation", [2, 2, None, None, None])])
    g = parse.read_bea_grid(p, "2017")
    assert list(g.values.columns) == ["111200", "T001", "F01000", "T004", "T007"]
    assert list(g.values.index) == ["111200", "V00100"]
    assert g.values.loc["111200", "T007"] == 6.0

def test_list_year_sheets(tmp_path):
    p = tmp_path / "x.xlsx"
    write_bea_workbook(p, sheet="2012", col_codes=["A"], col_descs=["a"], rows=[("A", "a", [1])])
    import openpyxl; wb = openpyxl.load_workbook(p); wb.create_sheet("NAICS Codes"); wb.create_sheet("2017"); wb.save(p)
    assert parse.list_year_sheets(p) == [2012, 2017]

def test_read_bea_grid_missing_code_row_names_sheet(tmp_path):
    import openpyxl
    p = tmp_path / "nocode.xlsx"
    wb = openpyxl.Workbook(); wb.active.title = "2017"; wb.active.cell(1, 1, "Title"); wb.active.cell(5, 1, "Industry")
    wb.save(p)
    with pytest.raises(ValueError, match="'2017'.*'Code'"):
        parse.read_bea_grid(p, "2017")

def test_read_bea_grid_rejects_uncoded_unknown_column(tmp_path):
    p = tmp_path / "bad.xlsx"
    write_bea_workbook(p, col_codes=["A", None], col_descs=["Alpha", "Mystery total"], rows=[("A", "Alpha ind", [1, 2])])
    with pytest.raises(ValueError, match="Mystery total"):
        parse.read_bea_grid(p, "2017")

def test_read_bea_grid_rejects_duplicate_codes(tmp_path):
    p = tmp_path / "dup.xlsx"
    write_bea_workbook(p, col_codes=["A", "A"], col_descs=["Alpha", "Alpha again"], rows=[("A", "Alpha ind", [1, 2])])
    with pytest.raises(ValueError, match="duplicate column codes"):
        parse.read_bea_grid(p, "2017")

def test_read_bea_grid_non_numeric_cells_become_zero_and_note_is_excluded(tmp_path):
    p = tmp_path / "dots.xlsx"
    write_bea_workbook(p, col_codes=["A", "B"], col_descs=["Alpha", "Beta"],
                       rows=[("A", "Alpha ind", ["...", 7.5]), ("B", "Beta ind", [2, None])])
    g = parse.read_bea_grid(p, "2017")
    assert g.values.shape == (2, 2) and str(g.values.dtypes.unique()[0]) == "float64"
    assert g.values.loc["A", "A"] == 0.0 and g.values.loc["A", "B"] == 7.5 and g.values.loc["B", "A"] == 2.0
