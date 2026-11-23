# tests/conftest.py
import dataclasses
import openpyxl, pandas as pd, pytest
from pathlib import Path
from iotables import parse, square

def write_bea_workbook(path: Path, *, sheet="2017", title="Make Table, After Redefinitions, 2017",
                       row_label="Industry Description", col_codes=None, col_descs=None, rows=None,
                       header_row=5, int_codes=False, trailing_note=True):
    """rows: list of (code, desc, [values...]). Writes BEA's layout: title rows, blank, desc row, 'Code' row, data."""
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = sheet
    ws.cell(1, 1, title); ws.cell(2, 1, "[Millions of Dollars]"); ws.cell(3, 1, "Bureau of Economic Analysis")
    ws.cell(header_row, 1, "Industry / Commodity")
    for j, d in enumerate(col_descs): ws.cell(header_row, 3 + j, d)
    ws.cell(header_row + 1, 1, "Code"); ws.cell(header_row + 1, 2, row_label)
    for j, c in enumerate(col_codes):
        if c is not None: ws.cell(header_row + 1, 3 + j, int(c) if int_codes and str(c).isdigit() else c)
    r = header_row + 2
    for code, desc, vals in rows:
        ws.cell(r, 1, int(code) if int_codes and str(code).isdigit() else code); ws.cell(r, 2, desc)
        for j, v in enumerate(vals):
            if v is not None: ws.cell(r, 3 + j, v)
        r += 1
    if trailing_note: ws.cell(r + 1, 1, "Note. Detail may not add to total due to rounding.")
    wb.save(path)


# Toy tables from BEA's Concepts and Methods manual (tables 12.5 and 12.7), spec section 9.
# Industries and commodities A, B, C plus scrap S00401; one final-demand column F01000.

@pytest.fixture
def toy_make_grid():
    """The toy make table as a BeaGrid: 3 industries x (3 commodities + scrap), with T008 and T007 totals."""
    values = pd.DataFrame(
        [[300, 25, 0, 3, 328],
         [30, 360, 20, 2, 412],
         [0, 15, 250, 0, 265],
         [330, 400, 270, 5, 0]],
        index=["A", "B", "C", "T007"], columns=["A", "B", "C", "S00401", "T008"], dtype=float)
    return parse.BeaGrid(
        values=values,
        row_labels=pd.Series(["Industry A", "Industry B", "Industry C", "Total Commodity Output"], index=values.index),
        col_labels=pd.Series(["Commodity A", "Commodity B", "Commodity C", "Scrap", "Total Industry Output"], index=values.columns),
        title="Make Table, Toy Economy")

@pytest.fixture
def toy_use_grid():
    """The toy use table as a BeaGrid: commodity rows, value-added rows and T008 total over industry, final-demand and T007 columns."""
    values = pd.DataFrame(
        [[50, 120, 120, 40, 330],
         [180, 30, 60, 130, 400],
         [50, 150, 50, 20, 270],
         [1, 3, 1, 0, 5],
         [0, 0, 0, 0, 0],
         [0, 0, 0, 0, 0],
         [47, 109, 34, 0, 0],
         [328, 412, 265, 0, 0]],
        index=["A", "B", "C", "S00401", "V00100", "V00200", "V00300", "T008"],
        columns=["A", "B", "C", "F01000", "T007"], dtype=float)
    return parse.BeaGrid(
        values=values,
        row_labels=pd.Series(["Commodity A", "Commodity B", "Commodity C", "Scrap", "Compensation of employees",
                              "Taxes on production and imports, less subsidies", "Gross operating surplus",
                              "Total Industry Output"], index=values.index),
        col_labels=pd.Series(["Industry A", "Industry B", "Industry C", "Personal consumption expenditures",
                              "Total Commodity Output"], index=values.columns),
        title="Use Table, Toy Economy")

def write_grid_workbook(path: Path, grid: parse.BeaGrid, *, sheet="2017", row_label="Industry Description"):
    """Write a BeaGrid with write_bea_workbook (BEA's layout, every code in the "Code" row)."""
    write_bea_workbook(path, sheet=sheet, title=grid.title, row_label=row_label,
                       col_codes=list(grid.values.columns), col_descs=list(grid.col_labels.loc[grid.values.columns]),
                       rows=[(code, grid.row_labels[code], [float(v) for v in grid.values.loc[code]])
                             for code in grid.values.index])

@pytest.fixture
def toy_workbooks(tmp_path, toy_make_grid, toy_use_grid):
    """The toy make and use grids as BEA-layout workbooks (sheet "2017") in tmp_path/input; (make_path, use_path)."""
    (tmp_path / "input").mkdir()
    make_p, use_p = tmp_path / "input" / "toy_make.xlsx", tmp_path / "input" / "toy_use.xlsx"
    write_grid_workbook(make_p, toy_make_grid, row_label="Industry Description")
    write_grid_workbook(use_p, toy_use_grid, row_label="Commodity Description")
    return make_p, use_p

@pytest.fixture
def toy_make(toy_make_grid):
    return parse.MakeTable.from_grid(toy_make_grid)

@pytest.fixture
def toy_use(toy_use_grid):
    return parse.UseTable.from_grid(toy_use_grid)


@pytest.fixture
def two_by_two():
    """A hand-built 2-industry, 2-commodity SquareIOTable for the shock and price-model tests.

    Industries "1", "2": Z = [[10, 20], [30, 40]], F01000 = [70, 30], y = [100, 100], value added
    V00100 = [30, 20], V00200 = [0, 0], V00300 = [30, 20]. Commodities "a", "b" with make
    M = [[90, 10], [0, 100]] (q = [90, 110]), so market shares are [[1, 10/110], [0, 100/110]].
    """
    industries, commodities = ["1", "2"], ["a", "b"]
    market_shares = pd.DataFrame([[1.0, 10 / 110], [0.0, 100 / 110]], index=industries, columns=commodities)
    return square.SquareIOTable(
        Z=pd.DataFrame([[10.0, 20.0], [30.0, 40.0]], index=industries, columns=industries),
        F=pd.DataFrame({"F01000": [70.0, 30.0]}, index=industries),
        V=pd.DataFrame([[30.0, 20.0], [0.0, 0.0], [30.0, 20.0]],
                       index=["V00100", "V00200", "V00300"], columns=industries),
        y=pd.Series([100.0, 100.0], index=industries),
        N=market_shares.copy(),
        market_shares=market_shares,
        industry_labels=pd.Series({"1": "One", "2": "Two"}),
        final_demand_labels=pd.Series({"F01000": "PCE"}),
        commodity_labels=pd.Series({"a": "Alpha", "b": "Beta"}),
        meta={"year": 2017, "level": "toy", "commodity_output": pd.Series({"a": 90.0, "b": 110.0})})


def add_use_row(use, code, intermediate_values, fd):
    """A copy of `use` with one extra commodity row `code`: `intermediate_values` over the
    industry columns and `fd` over the final-demand columns, in table order."""
    intermediate = pd.concat([use.intermediate, pd.DataFrame([intermediate_values], index=[code],
                                                             columns=use.intermediate.columns, dtype=float)])
    final_demand = pd.concat([use.final_demand, pd.DataFrame([fd], index=[code],
                                                             columns=use.final_demand.columns, dtype=float)])
    labels = pd.concat([use.commodity_labels, pd.Series([f"Commodity {code}"], index=[code])])
    output = (None if use.commodity_output is None else
              pd.concat([use.commodity_output, pd.Series([float(sum(intermediate_values) + sum(fd))], index=[code])]))
    return dataclasses.replace(use, intermediate=intermediate, final_demand=final_demand,
                               commodity_labels=labels, commodity_output=output)

def add_make_column(make, code, values):
    """A copy of `make` with one extra commodity column `code` (`values` over the industries, in table order)."""
    column = pd.Series(values, index=make.values.index, dtype=float)
    new_values = make.values.copy(); new_values[code] = column
    labels = pd.concat([make.commodity_labels, pd.Series([f"Commodity {code}"], index=[code])])
    industry_output = None if make.industry_output is None else make.industry_output + column
    commodity_output = (None if make.commodity_output is None else
                        pd.concat([make.commodity_output, pd.Series([column.sum()], index=[code])]))
    return dataclasses.replace(make, values=new_values, commodity_labels=labels,
                               industry_output=industry_output, commodity_output=commodity_output)


VALUE_ADDED_CODES = ["V00100", "V00200", "V00300"]

def write_pce_bridge_workbook(path: Path) -> Path:
    """A tiny PCE bridge in the layout of BEA's PCEBridge_2017_DET.xlsx; returns `path`.

    Sheets "Data Layout" and "2017". In "2017": title, units and source in rows 1-3, the group labels
    (Producers' Value, Transportation Costs, Trade Margins, Purchasers' Value) in row 4, the column
    header in row 5 (its producers', transportation and purchasers' cells blank, as in BEA's file), and
    from row 6 three data rows: NIPA lines 7, 7 and 13 (as ints), commodity codes 336111 and 336211
    (ints) and "S00401"; then a blank row and a note the parser must not read.
    """
    wb = openpyxl.Workbook(); wb.active.title = "Data Layout"; ws = wb.create_sheet("2017")
    for r, text in enumerate(["PCE Bridge Table, 2017", "[Millions of dollars]", "Bureau of Economic Analysis"], start=1):
        ws.cell(r, 1, text)
    for j, label in {5: "Producers' Value", 6: "Transportation Costs", 7: "            Trade Margins", 9: "Purchasers' Value"}.items():
        ws.cell(4, j, label)
    for j, label in enumerate(["NIPA Line", "PCE Category", "Commodity Code", "Commodity Description",
                               None, None, "Wholesale", "Retail", None, "Year"], start=1):
        if label is not None: ws.cell(5, j, label)
    rows = [(7, "New domestic autos", 336111, "Automobile manufacturing", 14874, 711, 4699, 31275, 51558, 2017),
            (7, "New domestic autos", 336211, "Motor vehicle body manufacturing", 81, 1, 25, 293, 400, 2017),
            (13, "Used autos", "S00401", "Scrap", -10652, 0, 0, 0, -10652, 2017)]
    for i, row in enumerate(rows, start=6):
        for j, v in enumerate(row, start=1): ws.cell(i, j, v)
    ws.cell(6 + len(rows) + 1, 1, "Note. Detail may not add to total due to rounding.")
    wb.save(path)
    return path


def no_imports(use):
    """An import matrix of zeros for `use`: nothing is imported."""
    return parse.ImportMatrix(intermediate=use.intermediate * 0.0, final_demand=use.final_demand * 0.0, meta={})


@pytest.fixture
def toy_square(toy_make, toy_use):
    """The toy economy's square table."""
    return square.build_square_table(toy_make, toy_use, no_imports(toy_use))
