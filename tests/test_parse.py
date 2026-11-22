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


def test_make_from_grid(toy_make):
    assert toy_make.industries == ["A", "B", "C"] and toy_make.commodities == ["A", "B", "C", "S00401"]
    assert list(toy_make.industry_output) == [328, 412, 265]
    assert list(toy_make.commodity_output) == [330, 400, 270, 5]

def test_use_from_grid(toy_use):
    assert toy_use.industries == ["A", "B", "C"] and toy_use.commodities == ["A", "B", "C", "S00401"]
    assert list(toy_use.final_demand.columns) == ["F01000"]
    assert list(toy_use.value_added.index) == ["V00100", "V00200", "V00300"]
    assert toy_use.value_added.loc["V00300", "B"] == 109 and list(toy_use.industry_output) == [328, 412, 265]
    assert toy_use.commodity_output["S00401"] == 5

def test_use_requires_all_value_added_rows(toy_use_grid):
    g = parse.BeaGrid(values=toy_use_grid.values.drop(index="V00200"), row_labels=toy_use_grid.row_labels.drop("V00200"),
                      col_labels=toy_use_grid.col_labels, title=toy_use_grid.title)
    with pytest.raises(ValueError, match="V00200"):
        parse.UseTable.from_grid(g)

def test_parse_make_latest_sheet(tmp_path):
    p = tmp_path / "make.xlsx"
    write_bea_workbook(p, sheet="2012", col_codes=["A", "T008"], col_descs=["a", "Total Industry Output"], rows=[("A", "a", [1, 1])])
    import openpyxl; wb = openpyxl.load_workbook(p); ws = wb.copy_worksheet(wb["2012"]); ws.title = "2017"; ws["C7"] = 2; wb.save(p)
    m = parse.parse_make(p)                       # year="latest"
    assert m.meta["year"] == 2017 and m.values.loc["A", "A"] == 2.0
    assert parse.parse_make(p, 2012).values.loc["A", "A"] == 1.0

def test_from_grid_splits_by_code_not_position(toy_make_grid, toy_use_grid):
    def shuffled(g, rows, cols):
        return parse.BeaGrid(values=g.values.loc[rows, cols], row_labels=g.row_labels, col_labels=g.col_labels, title=g.title)
    use = parse.UseTable.from_grid(shuffled(toy_use_grid, ["V00300", "T008", "S00401", "A", "V00100", "C", "V00200", "B"],
                                            ["T007", "F01000", "C", "A", "B"]))
    assert sorted(use.industries) == ["A", "B", "C"] and sorted(use.commodities) == ["A", "B", "C", "S00401"]
    assert use.value_added.loc["V00300", "B"] == 109 and use.industry_output["C"] == 265 and use.commodity_output["B"] == 400
    assert use.intermediate.loc["C", "B"] == 150 and use.final_demand.loc["B", "F01000"] == 130
    make = parse.MakeTable.from_grid(shuffled(toy_make_grid, ["T007", "C", "A", "B"], ["T008", "S00401", "B", "A", "C"]))
    assert make.values.loc["B", "C"] == 20 and make.industry_output["B"] == 412 and make.commodity_output["S00401"] == 5

def test_labels_follow_their_codes(toy_make, toy_use):
    assert toy_make.industry_labels["B"] == "Industry B" and toy_make.commodity_labels["S00401"] == "Scrap"
    assert list(toy_make.industry_labels.index) == toy_make.industries
    assert toy_use.commodity_labels["C"] == "Commodity C" and toy_use.industry_labels["A"] == "Industry A"
    assert toy_use.final_demand_labels["F01000"] == "Personal consumption expenditures"

def test_from_grid_without_total_rows_leaves_outputs_none(toy_make_grid, toy_use_grid):
    make = parse.MakeTable.from_grid(parse.BeaGrid(values=toy_make_grid.values.drop(columns="T008", index="T007"),
                                                   row_labels=toy_make_grid.row_labels, col_labels=toy_make_grid.col_labels, title=""))
    use = parse.UseTable.from_grid(parse.BeaGrid(values=toy_use_grid.values.drop(columns="T007", index="T008"),
                                                 row_labels=toy_use_grid.row_labels, col_labels=toy_use_grid.col_labels, title=""))
    assert make.industry_output is None and make.commodity_output is None
    assert use.industry_output is None and use.commodity_output is None

def test_parse_use_rejects_year_without_sheet(tmp_path):
    p = tmp_path / "use.xlsx"
    write_bea_workbook(p, sheet="2012", col_codes=["A"], col_descs=["a"], rows=[("A", "a", [1])])
    with pytest.raises(ValueError, match="2019.*2012"):
        parse.parse_use(p, 2019)

def test_load_bea_tables_rejects_summary_level():
    with pytest.raises(NotImplementedError, match="summary level arrives in Phase 2"):
        parse.load_bea_tables("summary")

def test_load_bea_tables_downloads_into_bea_dir_and_records_meta(tmp_path, monkeypatch):
    import json
    from iotables import download, sources
    calls = []
    def fake_fetch(url, dest_dir, **kw):
        calls.append((url, dest_dir, kw))
        path = dest_dir / ("make.xlsx" if "Make" in url else "use.xlsx")
        dest_dir.mkdir(parents=True, exist_ok=True)
        if "Make" in url:
            write_bea_workbook(path, col_codes=["A", "T008"], col_descs=["a", "Total Industry Output"], rows=[("A", "a", [1, 1]), ("T007", "Total Commodity Output", [1, None])])
        else:
            write_bea_workbook(path, row_label="Commodity Description", col_codes=["A", "F01000", "T007"],
                               col_descs=["a", "PCE", "Total Commodity Output"],
                               rows=[("A", "a", [1, 0, 1]), ("V00100", "c", [0, 0, 0]), ("V00200", "t", [0, 0, 0]), ("V00300", "s", [0, 0, 0]), ("T008", "Total Industry Output", [1, 0, 0])])
        path.with_name(path.name + ".provenance.json").write_text(json.dumps({"url": url, "sha256": "abc", "bytes": 1, "downloaded_at": "now"}))
        return path
    monkeypatch.setattr(download, "fetch", fake_fetch)
    make, use = parse.load_bea_tables("detail", "latest", "before", data_dir=tmp_path, force=True)
    assert [c[0] for c in calls] == [sources.bea_detail_url("make", "before"), sources.bea_detail_url("use", "before")]
    assert all(c[1] == tmp_path / "bea" and c[2] == {"force": True} for c in calls)
    assert make.meta["redefinitions"] == use.meta["redefinitions"] == "before"
    assert make.meta["provenance"]["url"] == sources.bea_detail_url("make", "before") and use.meta["provenance"]["sha256"] == "abc"
    assert make.meta["year"] == use.meta["year"] == 2017 and make.industries == use.industries == ["A"]
    assert make.meta["level"] == use.meta["level"] == "detail"

@pytest.mark.network
def test_load_bea_tables_detail_2017_shapes():
    make, use = parse.load_bea_tables("detail", 2017, "after")
    assert make.values.shape == (402, 402) and use.intermediate.shape == (402, 402)
    assert make.commodities == use.commodities
    assert set(make.commodities) - set(make.industries) == {"S00300", "S00401", "S00402", "S00900"}
    assert use.final_demand.shape[1] == 20 and list(use.final_demand.columns)[:2] == ["F01000", "F02E00"]
    assert make.industries == use.industries
    assert (use.industry_output - make.industry_output).abs().max() <= 1.0
    assert use.meta["redefinitions"] == "after" and "sha256" in use.meta["provenance"]
    assert make.meta["level"] == use.meta["level"] == "detail" and make.meta["year"] == use.meta["year"] == 2017
