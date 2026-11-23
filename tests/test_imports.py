"""Imports in the module: the table built with an import matrix, import prices and fixed prices.

The economy is small enough to work by hand. Industries and commodities A, B, C;
each industry makes only its own commodity. Per 100 of output: A buys 20 of
commodity C, all of it imported; B buys 50 of A; C buys nothing. Households buy
50 of A, 100 of B and 100 of C, and the imports column is -20 of C.
"""

import numpy as np
import pandas as pd
import pytest

from iotables import PriceModel, build_square_table, parse, costs

NAMES = ["A", "B", "C"]


@pytest.fixture
def grids():
    """The make, use and import-matrix grids of the economy, as BeaGrids: (make, use, imports)."""
    make = pd.DataFrame([[100, 0, 0, 100], [0, 100, 0, 100], [0, 0, 100, 100], [100, 100, 100, 0]],
                        index=[*NAMES, "T007"], columns=[*NAMES, "T008"], dtype=float)
    use = pd.DataFrame(
        [[0, 50, 0, 50, 0, 100],
         [0, 0, 0, 100, 0, 100],
         [20, 0, 0, 100, -20, 100],
         [50, 30, 60, 0, 0, 0],
         [0, 0, 0, 0, 0, 0],
         [30, 20, 40, 0, 0, 0],
         [100, 100, 100, 0, 0, 0]],
        index=[*NAMES, "V00100", "V00200", "V00300", "T008"], columns=[*NAMES, "F01000", "F05000", "T007"], dtype=float)
    imports = pd.DataFrame([[0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [20, 0, 0, 0, -20]],
                           index=NAMES, columns=[*NAMES, "F01000", "F05000"], dtype=float)

    def grid(values, title):
        return parse.BeaGrid(values=values, row_labels=pd.Series([f"Row {c}" for c in values.index], index=values.index),
                             col_labels=pd.Series([f"Column {c}" for c in values.columns], index=values.columns), title=title)

    return grid(make, "Make"), grid(use, "Use"), grid(imports, "Import Matrix")


@pytest.fixture
def tables(grids):
    make, use, imports = grids
    meta = {"year": 2017, "level": "detail"}
    return (parse.MakeTable.from_grid(make, meta), parse.UseTable.from_grid(use, meta),
            parse.ImportMatrix.from_grid(imports, meta))


@pytest.fixture
def split(tables):
    make, use, imports = tables
    return build_square_table(make, use, imports)


def price_changes(result):
    return result.industry_prices.set_index("code")["price_change"]


# --- the table ---------------------------------------------------------------------


def test_table_keeps_output_and_separates_imports(split):
    assert split.y.to_list() == [100.0, 100.0, 100.0]
    assert split.Z.loc["C", "A"] == 0 and split.imported_inputs.loc["C", "A"] == 20   # A's purchase of C is imported
    assert split.F.loc["C"].to_list() == [100.0, 0.0]                               # nothing left in the imports column
    assert list(split.imported_final.columns) == ["F01000"]                         # without the imports column
    assert split.V.loc["V00300"].to_list() == [30.0, 20.0, 40.0]                    # imported inputs are a cost
    assert split.total_imports.to_dict() == {"A": 0.0, "B": 0.0, "C": 20.0}
    assert split.check_identities()["row_minus_col"] == 0


def test_the_matrix_own_imports_column_is_not_used(tables):
    make, use, imports = tables
    imports.final_demand.loc["C", "F05000"] = -19.0                                # as if rounded
    assert build_square_table(make, use, imports).y.to_list() == [100.0, 100.0, 100.0]


def test_import_matrix_must_cover_the_use_table(tables):
    make, use, imports = tables
    imports.intermediate = imports.intermediate.drop(index="B")
    with pytest.raises(ValueError, match="lacks commodities"):
        build_square_table(make, use, imports)


# --- tariffs and fixed prices ---------------------------------------------------------


def test_import_price_passes_through_imported_inputs(split):
    result = PriceModel(split).run([costs.ImportPrice("C", rate=0.25)])
    # A's costs rise by 0.20 x 25%; B's by 0.50 x A's rise; C buys nothing.
    np.testing.assert_allclose(price_changes(result).to_numpy(), [0.05, 0.025, 0.0], atol=1e-15)
    assert result.summary["total_cost"] == pytest.approx(5.0)                       # 25% of 20 of imports
    assert result.summary["identity_residual"] == pytest.approx(0.0, abs=1e-12)
    assert result.burden_by_final_demand.set_index("code")["burden"]["F01000"] == pytest.approx(5.0)
    prices = result.commodity_prices.set_index("code")
    assert prices.loc["C", "import_price_change"] == 0.25 and prices.loc["C", "price_change"] == 0


def test_import_price_in_dollars_and_on_all_imports(split):
    model = PriceModel(split)
    by_rate = price_changes(model.run([costs.ImportPrice("C", rate=0.25)]))
    pd.testing.assert_series_equal(price_changes(model.run([costs.ImportPrice("C", dollars=5.0)])), by_rate)
    pd.testing.assert_series_equal(price_changes(model.run([costs.ImportPrice("all", rate=0.25)])), by_rate)


def test_domestic_cost_does_not_move_import_prices(split):
    result = PriceModel(split).run([costs.IndustryCost("C", rate=0.10)])
    np.testing.assert_allclose(price_changes(result).to_numpy(), [0.0, 0.0, 0.10], atol=1e-15)


def test_industry_price_is_hit_exactly(split):
    result = PriceModel(split).run([costs.IndustryPrice("A", 0.10), costs.IndustryCost("A", dollars=3.0)])
    np.testing.assert_allclose(price_changes(result).to_numpy(), [0.10, 0.05, 0.0], atol=1e-15)
    assert result.summary["total_cost"] == pytest.approx(10.0)                      # 10% of A's output
    assert result.summary["identity_residual"] == pytest.approx(0.0, abs=1e-12)


@pytest.mark.parametrize("shock, error, text", [
    (costs.ImportPrice("ZZZ", rate=0.1), KeyError, "ZZZ"),
    (costs.ImportPrice("A", dollars=5.0), ValueError, "no imports"),
    (costs.IndustryPrice("ZZZ", 0.1), KeyError, "ZZZ"),
])
def test_bad_import_and_fixed_prices(split, shock, error, text):
    with pytest.raises(error, match=text):
        PriceModel(split).run([shock])


def test_import_price_needs_exactly_one_of_rate_and_dollars():
    with pytest.raises(ValueError, match="exactly one"):
        costs.ImportPrice("C")


# --- writing a split table and its results ------------------------------------------------


def test_split_table_layout_and_files(split, tmp_path):
    frame = split.to_frame()
    assert list(frame.index) == [*NAMES, "IMPORTS", "V00100", "V00200", "V00300", "T008"]
    assert frame.loc["IMPORTS", "A"] == 20 and frame.loc["T008", NAMES].to_list() == [100.0, 100.0, 100.0]
    assert frame.loc[frame.index[:-1], NAMES].sum().to_list() == [100.0, 100.0, 100.0]      # columns add up
    paths = split.to_csv(tmp_path / "table")
    assert {"imported_inputs", "imported_final", "pce_import_share"} <= set(paths)
    back = pd.read_csv(paths["imported_inputs"], index_col="Code")
    pd.testing.assert_frame_equal(back.rename_axis(None), split.imported_inputs)
    assert not list(tmp_path.rglob("*.xlsx"))


def test_result_to_csv(split, tmp_path):
    result = PriceModel(split).run([costs.ImportPrice("C", rate=0.25), costs.IndustryCost("A", dollars=1.0)])
    paths = result.to_csv(tmp_path / "results")
    assert sorted(p.name for p in (tmp_path / "results").iterdir()) == [
        "burden_by_final_demand.csv", "changes.csv", "commodity_prices.csv", "industry_prices.csv", "summary.csv"]
    assert "pce_prices" not in paths                                               # no PCE bridge in this run
    pd.testing.assert_frame_equal(pd.read_csv(paths["industry_prices"]), result.industry_prices)
    summary = pd.read_csv(paths["summary"]).set_index("item")["value"]
    assert float(summary["total_cost"]) == pytest.approx(result.summary["total_cost"])
    written = pd.read_csv(paths["changes"])
    assert list(written["type"]) == ["ImportPrice", "IndustryCost"] and list(written["code"]) == ["C", "A"]
