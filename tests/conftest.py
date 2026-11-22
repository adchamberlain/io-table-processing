# tests/conftest.py
import dataclasses
import openpyxl, pandas as pd, pytest
from pathlib import Path
from iotables import parse

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

@pytest.fixture
def toy_make(toy_make_grid):
    return parse.MakeTable.from_grid(toy_make_grid)

@pytest.fixture
def toy_use(toy_use_grid):
    return parse.UseTable.from_grid(toy_use_grid)


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
