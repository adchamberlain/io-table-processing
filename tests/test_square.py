# tests/test_square.py
import dataclasses
import datetime
import json
import numpy as np, openpyxl, pandas as pd, pytest
import iotables
from iotables import square, parse
from conftest import add_use_row, add_make_column

def test_market_shares_columns_sum_to_one(toy_make):
    ms = square.market_shares(toy_make.values)
    assert np.allclose(ms.sum(axis=0), 1.0)
    assert ms.loc["A", "A"] == pytest.approx(300 / 330)

def test_market_shares_zero_output_column_is_zero():
    m = pd.DataFrame([[1.0, 0.0], [1.0, 0.0]], index=["i", "j"], columns=["a", "b"])
    ms = square.market_shares(m)
    assert (ms["b"] == 0).all() and not ms.isna().any().any()

def test_build_keep_mode_identities(toy_make, toy_use):
    sq = square.build_square_table(toy_make, toy_use, scrap="keep")
    assert sq.Z.shape == (3, 3) and list(sq.F.columns) == ["F01000"] and list(sq.V.index) == ["V00100", "V00200", "V00300"]
    res = sq.check_identities()
    assert res["row_minus_col"] < 1e-9
    assert sq.y.sum() == pytest.approx(328 + 412 + 265)       # scrap kept as a commodity: totals preserved
    assert sq.meta["diagnostics"]["scrap_mode"] == "keep"

def test_build_reorders_by_code(toy_make, toy_use):
    use2 = parse.UseTable(**{**toy_use.__dict__, "intermediate": toy_use.intermediate[["C", "A", "B"]],
                             "value_added": toy_use.value_added[["C", "A", "B"]]})
    a = square.build_square_table(toy_make, toy_use, scrap="keep"); b = square.build_square_table(toy_make, use2, scrap="keep")
    pd.testing.assert_frame_equal(a.Z, b.Z)

def test_build_rejects_industry_mismatch(toy_make, toy_use):
    bad = parse.UseTable(**{**toy_use.__dict__, "intermediate": toy_use.intermediate.rename(columns={"C": "Q"}),
                            "value_added": toy_use.value_added.rename(columns={"C": "Q"})})
    with pytest.raises(ValueError, match="Q"):
        square.build_square_table(toy_make, bad, scrap="keep")

def test_zero_output_commodity(toy_make, toy_use):
    # commodity "Z" used by nobody and made by nobody -> fine; used by somebody -> error
    use_zero = add_use_row(toy_use, "Z", [0, 0, 0], fd=[0]); use_pos = add_use_row(toy_use, "Z", [1, 0, 0], fd=[0])
    square.build_square_table(toy_make, use_zero, scrap="keep")
    with pytest.raises(ValueError, match="Z"):
        square.build_square_table(toy_make, use_pos, scrap="keep")

def test_build_keep_mode_values_and_meta(toy_make, toy_use):
    toy_make.meta.update(year=2017, level="detail", redefinitions="after")
    sq = square.build_square_table(toy_make, toy_use, scrap="keep")
    # hand-computed from BEA manual tables 12.5/12.7: Z_AA = sum_c (M_Ac / q_c) U_cA, scrap included
    assert sq.Z.loc["A", "A"] == pytest.approx(300 / 330 * 50 + 25 / 400 * 180 + 3 / 5 * 1)
    assert sq.F.loc["B", "F01000"] == pytest.approx(30 / 330 * 40 + 360 / 400 * 130 + 20 / 270 * 20)
    assert list(sq.y.round(9)) == [328, 412, 265] and list(sq.V.loc["V00300"].round(9)) == [47, 109, 34]
    assert sq.industries == ["A", "B", "C"] and sq.n == 3
    assert sq.meta["year"] == 2017 and sq.meta["level"] == "detail" and sq.meta["redefinitions"] == "after"
    assert sq.meta["source"] == {"make": toy_make.meta, "use": toy_use.meta}
    pd.testing.assert_series_equal(sq.meta["commodity_output"],
                                   pd.Series([330.0, 400.0, 270.0, 5.0], index=["A", "B", "C", "S00401"]), check_names=False)
    d = sq.meta["diagnostics"]
    assert d["dropped"] == {} and d["y_minus_g"].abs().max() < 1e-9 and d["gos_minus_bea"].abs().max() < 1e-9
    assert sq.commodity_labels["S00401"] == "Scrap" and sq.final_demand_labels["F01000"] == "Personal consumption expenditures"

def test_build_rejects_make_only_commodity(toy_make, toy_use):
    with pytest.raises(ValueError, match=r"\['X'\]"):
        square.build_square_table(add_make_column(toy_make, "X", [1, 0, 0]), toy_use, scrap="keep")

def test_drop_codes_removed_and_recorded_keep_mode(toy_make, toy_use):
    make2 = add_make_column(add_make_column(toy_make, "S00300", [0, 0, 0]), "S00900", [0, 3, 0])
    use2 = add_use_row(add_use_row(toy_use, "S00300", [2, 0, 0], fd=[-2]), "S00900", [0, 0, 0], fd=[3])
    sq = square.build_square_table(make2, use2, scrap="keep")
    d = sq.meta["diagnostics"]
    assert d["dropped"] == {"S00300": {"intermediate": 2.0, "final_demand": -2.0},
                            "S00900": {"intermediate": 0.0, "final_demand": 3.0}}
    assert d["dropped_make_output"] == {"S00300": 0.0, "S00900": 3.0}
    assert not {"S00300", "S00900"} & set(sq.market_shares.columns)
    assert sq.check_identities()["row_minus_col"] < 1e-9

def test_zero_make_column_with_nonzero_use_rejected(toy_make, toy_use):
    # spec 7.4: q = 0 requires zero use, also when the make column exists (S00300 kept here by drop=())
    make2 = add_make_column(toy_make, "S00300", [0, 0, 0]); use2 = add_use_row(toy_use, "S00300", [2, 0, 0], fd=[-2])
    with pytest.raises(ValueError, match=r"\['S00300'\]"):
        square.build_square_table(make2, use2, scrap="keep", drop=())

def test_build_rejects_unknown_scrap_mode(toy_make, toy_use):
    with pytest.raises(ValueError, match="bogus"):
        square.build_square_table(toy_make, toy_use, scrap="bogus")

def test_bea_mode_matches_manual_example(toy_make, toy_use):
    sq = square.build_square_table(toy_make, toy_use, scrap="bea")
    r = sq.meta["diagnostics"]["nonscrap_ratio"]
    assert list(r.round(3)) == [0.991, 0.995, 1.000]
    W = sq.N
    expected_W = pd.DataFrame([[.917, .063, .000], [.091, .904, .074], [.000, .038, .926]], index=list("ABC"), columns=list("ABC"))
    assert np.allclose(W.values, expected_W.values, atol=5e-4)
    assert np.allclose(sq.y.values, [328, 412, 265])                      # industry output preserved exactly
    assert "S00401" not in sq.market_shares.columns and sq.check_identities()["row_minus_col"] < 1e-9
    # total requirements: commodity-by-commodity (I - BW)^-1 and industry-by-commodity W(I - BW)^-1
    B = toy_use.intermediate.drop(index="S00401").div(toy_use.industry_output, axis=1)
    cxc = np.linalg.inv(np.eye(3) - B.values @ W.values)
    assert np.allclose(cxc, [[2.487, 1.500, 1.778], [1.736, 2.300, 1.579], [1.292, 1.322, 2.323]], atol=2e-3)
    ixc = W.values @ cxc
    assert np.allclose(ixc, [[2.391, 1.521, 1.731], [1.893, 2.316, 1.763], [1.261, 1.310, 2.210]], atol=2e-3)
    # our square table's own coefficients equal W B, so (I - A)^-1 W reproduces the same industry-by-commodity table
    A = sq.Z.div(sq.y, axis=1)
    assert np.allclose(np.linalg.inv(np.eye(3) - A.values) @ W.values, ixc, atol=1e-9)

def test_bea_mode_records_dropped_scrap(toy_make, toy_use):
    sq = square.build_square_table(toy_make, toy_use, scrap="bea")
    assert sq.meta["diagnostics"]["scrap_purchases_dropped"]["S00401"]["intermediate"] == 5

def test_bea_mode_scrap_code_without_make_column_is_dropped(toy_make, toy_use):
    # like the real 2017 S00402: a use row but no make column; no scrap output, still removed from U and D
    base = square.build_square_table(toy_make, toy_use, scrap="bea")
    sq = square.build_square_table(toy_make, add_use_row(toy_use, "S00402", [1, 0, 0], fd=[-1]), scrap="bea")
    assert sq.meta["diagnostics"]["scrap_purchases_dropped"]["S00402"] == {"intermediate": 1.0, "final_demand": -1.0}
    pd.testing.assert_series_equal(sq.meta["diagnostics"]["nonscrap_ratio"], base.meta["diagnostics"]["nonscrap_ratio"])
    pd.testing.assert_frame_equal(sq.Z, base.Z)
    assert "S00402" not in sq.commodity_labels.index

def test_bea_mode_rejects_all_scrap_industry(toy_make, toy_use):
    values = toy_make.values.copy(); values.loc["C"] = [0.0, 0.0, 0.0, 265.0]
    make2 = dataclasses.replace(toy_make, values=values)
    with pytest.raises(ValueError, match=r"\['C'\]"):
        square.build_square_table(make2, toy_use, scrap="bea")

def test_redistribute_rows_preserves_column_totals(toy_use):
    U2, un = square.redistribute_rows(toy_use.intermediate, ["S00401"])
    assert "S00401" not in U2.index and un == {}
    assert np.allclose(U2.sum(axis=0).values, toy_use.intermediate.sum(axis=0).values)   # 281, 303, 231
    assert U2.loc["A", "A"] == pytest.approx(50 + 1 * 50 / 280)

def test_redistribute_rows_reports_unallocated():
    blk = pd.DataFrame({"j": [0.0, 0.0, 4.0]}, index=["a", "b", "S00401"])
    out, un = square.redistribute_rows(blk, ["S00401"])
    assert un == {"j": 4.0} and (out["j"] == 0).all()

def test_redistribute_mode(toy_make, toy_use):
    sq = square.build_square_table(toy_make, toy_use, scrap="redistribute")
    assert sq.check_identities()["row_minus_col"] < 1e-9 and (sq.Z.values >= 0).all()
    assert not np.allclose(sq.y.values, [328, 412, 265])          # y is the row total, not BEA's g
    d = sq.meta["diagnostics"]
    assert d["redistributed"]["intermediate"] == pytest.approx(5.0) and d["y_minus_g"].abs().max() > 0

def test_drop_codes_removed_and_recorded(toy_make, toy_use):
    use3 = add_use_row(toy_use, "S00300", [2, 0, 0], fd=[-2]); make3 = add_make_column(toy_make, "S00300", [0, 0, 0])
    sq = square.build_square_table(make3, use3, scrap="bea")
    assert sq.meta["diagnostics"]["dropped"]["S00300"] == {"intermediate": 2.0, "final_demand": -2.0}
    assert "S00300" not in sq.market_shares.columns


def test_to_frame_layout(toy_make, toy_use):
    sq = square.build_square_table(toy_make, toy_use, scrap="bea"); f = sq.to_frame()
    assert list(f.index) == ["A", "B", "C", "V00100", "V00200", "V00300", "T008"]
    assert list(f.columns) == ["Description", "A", "B", "C", "F01000", "T008"]
    assert f.loc["A", "T008"] == pytest.approx(sq.y["A"]) and f.loc["T008", "A"] == pytest.approx(sq.y["A"])
    assert f.loc["T008", "T008"] == pytest.approx(sq.y.sum() + sq.F.values.sum())
    assert f.loc["V00300", "F01000"] == 0.0


def test_to_frame_values_and_descriptions(toy_make, toy_use):
    sq = square.build_square_table(toy_make, toy_use, scrap="bea"); f = sq.to_frame()
    assert f.loc["A", "B"] == sq.Z.loc["A", "B"] and f.loc["B", "F01000"] == sq.F.loc["B", "F01000"]
    assert f.loc["V00300", "C"] == sq.V.loc["V00300", "C"]
    assert f.loc["V00300", "T008"] == pytest.approx(sq.V.loc["V00300"].sum())
    assert f.loc["T008", "F01000"] == pytest.approx(sq.F["F01000"].sum())
    assert list(f["Description"]) == ["Industry A", "Industry B", "Industry C", "Compensation of employees",
                                      "Taxes on production and imports, less subsidies",
                                      "Gross operating surplus", "Total industry output"]
    assert (f.drop(columns="Description").dtypes == float).all()


def test_excel_roundtrip(tmp_path, toy_make, toy_use):
    sq = square.build_square_table(toy_make, toy_use, scrap="bea"); p = sq.to_excel(tmp_path / "t.xlsx")
    back = square.read_square_frame(p)
    pd.testing.assert_frame_equal(back.drop(columns="Description").astype(float), sq.to_frame().drop(columns="Description").astype(float), atol=1e-9)


@pytest.mark.parametrize("scrap", square.SCRAP_MODES)
def test_excel_roundtrip_keeps_descriptions_and_dtypes(tmp_path, toy_make, toy_use, scrap):
    sq = square.build_square_table(toy_make, toy_use, scrap=scrap)
    back = square.read_square_frame(sq.to_excel(tmp_path / "t.xlsx"))
    pd.testing.assert_frame_equal(back, sq.to_frame(), atol=1e-9)
    assert (back.drop(columns="Description").dtypes == float).all()


def test_excel_layout(tmp_path, toy_make, toy_use):
    toy_make.meta.update(year=2017, level="detail")
    sq = square.build_square_table(toy_make, toy_use, scrap="bea")
    ws = openpyxl.load_workbook(sq.to_excel(tmp_path / "out" / "t.xlsx"))["square"]
    assert [ws.cell(r, 1).value for r in (1, 2, 3)] == ["2017 detail-level U.S. Input-Output Table", "3 industries", "($ Millions)"]
    assert [ws.cell(5, c).value for c in range(1, 8)] == ["Code", None, "A", "B", "C", "F01000", "T008"]
    assert [ws.cell(6, c).value for c in range(1, 8)] == ["Industry", "Description", "Industry A", "Industry B", "Industry C",
                                                          "Personal consumption expenditures", "Total industry output"]
    assert [ws.cell(7, c).value for c in (1, 2)] == ["A", "Industry A"] and ws.cell(7, 3).value == pytest.approx(sq.Z.loc["A", "A"])
    assert ws.cell(13, 1).value == "T008" and ws.cell(14, 1).value is None
    assert ws.cell(15, 1).value == f"Source: Bureau of Economic Analysis; built with iotables {iotables.__version__} on {datetime.date.today().isoformat()}"
    assert openpyxl.load_workbook(sq.to_excel(tmp_path / "t2.xlsx", title="Custom"))["square"]["A1"].value == "Custom"


def test_excel_title_falls_back_without_year_and_level(tmp_path, toy_make, toy_use):
    sq = square.build_square_table(toy_make, toy_use, scrap="bea")
    assert openpyxl.load_workbook(sq.to_excel(tmp_path / "t.xlsx"))["square"]["A1"].value == "U.S. Input-Output Table"


def test_read_square_frame_finds_header_by_content(tmp_path, toy_make, toy_use):
    sq = square.build_square_table(toy_make, toy_use, scrap="bea"); p = sq.to_excel(tmp_path / "t.xlsx")
    wb = openpyxl.load_workbook(p); wb["square"].insert_rows(1, 4); wb.save(p)
    pd.testing.assert_frame_equal(square.read_square_frame(p), sq.to_frame(), atol=1e-9)


def test_read_square_frame_rejects_file_without_code_row(tmp_path):
    wb = openpyxl.Workbook(); wb.active.title = "square"; wb.active["A1"] = "nothing here"; wb.save(tmp_path / "t.xlsx")
    with pytest.raises(ValueError, match="Code"):
        square.read_square_frame(tmp_path / "t.xlsx")


def test_read_square_frame_rejects_blank_cells(tmp_path, toy_make, toy_use):
    p = square.build_square_table(toy_make, toy_use, scrap="bea").to_excel(tmp_path / "t.xlsx")
    wb = openpyxl.load_workbook(p); wb["square"]["D8"] = None; wb.save(p)
    with pytest.raises(ValueError, match="blank"):
        square.read_square_frame(p)


def test_read_square_frame_rejects_missing_sheet(tmp_path, toy_make, toy_use):
    p = square.build_square_table(toy_make, toy_use, scrap="bea").to_excel(tmp_path / "t.xlsx")
    wb = openpyxl.load_workbook(p); wb["square"].title = "other"; wb.save(p)
    with pytest.raises(ValueError, match=r"no sheet 'square'.*\['other'\]"):
        square.read_square_frame(p)


def test_read_square_frame_names_blank_and_non_numeric_cells(tmp_path, toy_make, toy_use):
    p = square.build_square_table(toy_make, toy_use, scrap="bea").to_excel(tmp_path / "t.xlsx")
    wb = openpyxl.load_workbook(p); wb["square"]["D8"] = "abc"; wb.save(p)       # row B, column B
    with pytest.raises(ValueError, match=r"row 'B', column 'B' is not a number: 'abc'"):
        square.read_square_frame(p)
    wb = openpyxl.load_workbook(p); wb["square"]["D8"] = None; wb.save(p)
    with pytest.raises(ValueError, match=r"row 'B', column 'B' is blank"):
        square.read_square_frame(p)


def test_read_square_frame_rejects_duplicate_codes(tmp_path, toy_make, toy_use):
    p = square.build_square_table(toy_make, toy_use, scrap="bea").to_excel(tmp_path / "t.xlsx")
    wb = openpyxl.load_workbook(p); wb["square"]["D5"] = "A"; wb.save(p)          # second header code A
    with pytest.raises(ValueError, match=r"duplicate column codes \['A'\]"):
        square.read_square_frame(p)
    p = square.build_square_table(toy_make, toy_use, scrap="bea").to_excel(tmp_path / "t2.xlsx")
    wb = openpyxl.load_workbook(p); wb["square"]["A8"] = "A"; wb.save(p)          # second row code A
    with pytest.raises(ValueError, match=r"duplicate row codes \['A'\]"):
        square.read_square_frame(p)


def test_read_square_frame_rejects_table_without_data_rows(tmp_path):
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "square"
    ws["A5"], ws["C5"] = "Code", "A"; wb.save(tmp_path / "t.xlsx")
    with pytest.raises(ValueError, match="0 data rows"):
        square.read_square_frame(tmp_path / "t.xlsx")


def test_read_square_frame_rejects_row_without_code(tmp_path, toy_make, toy_use):
    p = square.build_square_table(toy_make, toy_use, scrap="bea").to_excel(tmp_path / "t.xlsx")
    wb = openpyxl.load_workbook(p); wb["square"]["A8"] = None; wb.save(p)
    with pytest.raises(ValueError, match="Industry B"):
        square.read_square_frame(p)


@pytest.mark.parametrize("scrap", square.SCRAP_MODES)
def test_to_csv_writes_all_parts(tmp_path, toy_make, toy_use, scrap):
    paths = square.build_square_table(toy_make, toy_use, scrap=scrap).to_csv(tmp_path)
    assert set(paths) == {"square", "Z", "F", "V", "y", "market_shares", "labels", "meta"} and all(p.exists() for p in paths.values())
    assert sorted(p.name for p in tmp_path.iterdir()) == ["F.csv", "V.csv", "Z.csv", "labels.csv", "market_shares.csv", "meta.json",
                                                          "square.csv", "y.csv"]


def test_to_csv_contents(tmp_path, toy_make, toy_use):
    toy_make.meta.update(year=2017, level="detail")
    sq = square.build_square_table(toy_make, toy_use, scrap="bea"); paths = sq.to_csv(tmp_path / "out")
    read = lambda name: pd.read_csv(paths[name], index_col="Code").rename_axis(None)
    pd.testing.assert_frame_equal(read("Z"), sq.Z)
    pd.testing.assert_frame_equal(read("V"), sq.V)
    pd.testing.assert_series_equal(read("y")["y"], sq.y, check_names=False)
    pd.testing.assert_frame_equal(read("square"), sq.to_frame())
    labels = pd.read_csv(paths["labels"])
    assert list(labels.columns) == ["kind", "code", "description"] and set(labels["kind"]) == {"industry", "final_demand", "commodity"}
    assert labels.set_index(["kind", "code"]).loc[("commodity", "A"), "description"] == "Commodity A"
    meta = json.loads(paths["meta"].read_text())
    assert meta["year"] == 2017 and meta["level"] == "detail"
    assert meta["diagnostics"]["scrap_mode"] == "bea"
    assert meta["diagnostics"]["nonscrap_ratio"]["A"] == pytest.approx(sq.meta["diagnostics"]["nonscrap_ratio"]["A"])
    assert meta["commodity_output"]["A"] == 330.0 and meta["source"]["make"]["year"] == 2017


@pytest.mark.parametrize("scrap", square.SCRAP_MODES)
def test_from_frame_with_csv_folder_recovers_the_table(tmp_path, toy_make, toy_use, scrap):
    toy_make.meta.update(year=2017, level="detail", redefinitions="after")
    sq = square.build_square_table(toy_make, toy_use, scrap=scrap)
    sq.to_csv(tmp_path / "t")
    frame = square.read_square_frame(sq.to_excel(tmp_path / "t.xlsx"))
    back = square.SquareIOTable.from_frame(frame, {"table": "t.xlsx"}, csv_dir=tmp_path / "t")
    for name in ("Z", "F", "V", "N", "market_shares"):
        pd.testing.assert_frame_equal(getattr(back, name), getattr(sq, name), check_names=False, obj=name)
    for name in ("y", "industry_labels", "final_demand_labels", "commodity_labels"):
        pd.testing.assert_series_equal(getattr(back, name), getattr(sq, name), check_names=False, obj=name)
    pd.testing.assert_series_equal(back.meta["commodity_output"], sq.meta["commodity_output"], check_names=False)
    assert back.meta["year"] == 2017 and back.meta["level"] == "detail" and back.meta["table"] == "t.xlsx"
    assert back.meta["diagnostics"]["scrap_mode"] == scrap
    assert back.check_identities() == pytest.approx(sq.check_identities(), abs=1e-9)

def test_from_frame_without_csv_folder(toy_make, toy_use):
    sq = square.build_square_table(toy_make, toy_use, scrap="bea")
    back = square.SquareIOTable.from_frame(sq.to_frame())
    for name in ("Z", "F", "V"):
        pd.testing.assert_frame_equal(getattr(back, name), getattr(sq, name), check_names=False, obj=name)
    pd.testing.assert_series_equal(back.y, sq.y, check_names=False)
    assert list(back.industry_labels) == ["Industry A", "Industry B", "Industry C"]
    assert back.final_demand_labels.to_dict() == {"F01000": "F01000"}          # the layout has no column descriptions
    assert back.market_shares.empty and back.N.empty and back.commodity_labels.empty
    assert list(back.market_shares.index) == sq.industries and back.meta == {}

def test_from_frame_rejects_other_layouts(tmp_path, toy_make, toy_use, two_by_two):
    sq = square.build_square_table(toy_make, toy_use, scrap="bea")
    f = sq.to_frame()
    with pytest.raises(ValueError, match="V00100, V00200, V00300, T008"):
        square.SquareIOTable.from_frame(f.drop(index="V00200"))
    with pytest.raises(ValueError, match="T008"):
        square.SquareIOTable.from_frame(f.drop(columns="T008"))
    with pytest.raises(ValueError, match="Description"):
        square.SquareIOTable.from_frame(f.drop(columns="Description"))
    with pytest.raises(ValueError, match="industries"):
        square.SquareIOTable.from_frame(f[["Description", "B", "A", "C", "F01000", "T008"]])
    two_by_two.to_csv(tmp_path / "other")                                       # a CSV folder for another table
    with pytest.raises(ValueError, match="industries"):
        square.SquareIOTable.from_frame(f, csv_dir=tmp_path / "other")
