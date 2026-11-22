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


def grid_from_csv(values_path: Path, labels_path: Path | None) -> parse.BeaGrid:
    """A BeaGrid from a fixture CSV (codes as index and headers, first header "code"; ".gz" = gzip;
    ValueError for a blank cell).

    `labels_path` is a CSV with columns code,description listing the row codes in table order,
    then the column codes in table order (a code on both axes, like industry and commodity 1110,
    has one entry per axis); ValueError if its codes are not exactly those. None labels every
    code with itself. Skips the calling test when a fixture file is missing (the 2002 fixtures
    come from scripts/extract_2002_fixtures.py)."""
    values_path = Path(values_path)
    for p in (values_path, labels_path):
        if p is not None and not Path(p).exists(): pytest.skip(f"fixture {Path(p).name} missing")
    values = pd.read_csv(values_path, index_col=0, dtype={"code": str}).astype(float)
    if values.isna().to_numpy().any(): raise ValueError(f"{values_path.name}: blank or non-numeric cells")
    if labels_path is None:
        row_labels, col_labels = pd.Series(values.index, index=values.index), pd.Series(values.columns, index=values.columns)
    else:
        labels = pd.read_csv(labels_path, dtype=str, keep_default_na=False)
        if list(labels["code"]) != [*values.index, *values.columns]:
            raise ValueError(f"{Path(labels_path).name}: codes are not {values_path.name}'s row codes then its column codes")
        n = len(values.index)
        row_labels = pd.Series(list(labels["description"][:n]), index=values.index, dtype=object)
        col_labels = pd.Series(list(labels["description"][n:]), index=values.columns, dtype=object)
    return parse.BeaGrid(values=values, row_labels=row_labels, col_labels=col_labels, title=values_path.name)


FIX_2002 = Path(__file__).parent / "fixtures" / "2002"
VALUE_ADDED_CODES = ["V00100", "V00200", "V00300"]

def build_2002_summary() -> square.SquareIOTable:
    """Andrew's legacy 2002 summary table (`summary_target.csv`) as a SquareIOTable, for the price-model tests.

    Z, F, V and y are the legacy table's own cells (y its T008 column), so the price model is tested
    apart from any table-construction convention. The target CSV has no descriptions, so the labels,
    N, market shares and commodity output come from `build_square_table(make, use, scrap="keep",
    drop=())` on the summary fixtures, whose industry and final-demand codes must be the legacy
    table's (ValueError otherwise). Skips the calling test when a fixture file is missing.
    """
    target = FIX_2002 / "summary_target.csv"
    if not target.exists(): pytest.skip(f"fixture {target.name} missing")
    make = parse.MakeTable.from_grid(grid_from_csv(FIX_2002 / "summary_make.csv", FIX_2002 / "summary_make_labels.csv"))
    use = parse.UseTable.from_grid(grid_from_csv(FIX_2002 / "summary_use.csv", FIX_2002 / "summary_use_labels.csv"))
    built = square.build_square_table(make, use, scrap="keep", drop=())
    legacy = pd.read_csv(target, index_col=0, dtype={"code": str})
    industries = [c for c in legacy.index if c not in (*VALUE_ADDED_CODES, "T008")]
    final_demand = [c for c in legacy.columns if c not in (*industries, "T008")]
    if (sorted(industries) != sorted(built.industries) or sorted(final_demand) != sorted(built.F.columns)
            or list(legacy.index[len(industries):]) != [*VALUE_ADDED_CODES, "T008"]):
        raise ValueError(f"{target.name}: codes differ from the summary make and use fixtures'")
    return square.SquareIOTable(
        Z=legacy.loc[industries, industries], F=legacy.loc[industries, final_demand],
        V=legacy.loc[VALUE_ADDED_CODES, industries], y=legacy.loc[industries, "T008"],
        N=built.N.loc[industries], market_shares=built.market_shares.loc[industries],
        industry_labels=built.industry_labels.loc[industries],
        final_demand_labels=built.final_demand_labels.loc[final_demand],
        commodity_labels=built.commodity_labels,
        meta={"year": 2002, "level": "summary", "commodity_output": built.meta["commodity_output"]})
