"""Tests of script/io_model.py.

The script is a sequence of "# %%" cells that work on module-level variables.
`run_script` executes those cells in a fresh namespace and returns it. The
script and the `iotables` module hold the same method and must agree.
"""

import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from iotables import (PriceModel, build_square_table, load_bea_tables, load_import_matrix, load_pce_bridge,
                      costs)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "script" / "io_model.py"
CHANGE_CELL = 5


def script_cells() -> dict[int, str]:
    """{0: everything above cell 1, 1: source of "# %% 1. ...", 2: ...}."""
    cells, number = {0: ""}, 0
    for line in SCRIPT.read_text().splitlines(keepends=True):
        match = re.match(r"# %% (\d+)\.", line)
        if match:
            number = int(match.group(1))
            cells[number] = ""
        cells[number] += line
    return cells


def run_script(change=None, cells=range(1, 9), inject=None, output=None) -> dict:
    """Run the setup and the listed cells; return the script's variables.

    `change(ns)` replaces the script's example: it is called after the cost-change
    cell with c, import_price and fixed reset to nothing. `inject` supplies variables
    in place of the data cell.
    """
    source = script_cells()
    ns: dict = {}
    exec(compile(source[0], str(SCRIPT), "exec"), ns)
    ns["DATA"] = ROOT / "data" / "raw" / "bea"          # the downloads the module's tests already cache
    if output is not None:
        ns["OUTPUT"] = Path(output)
    ns.update(inject or {})
    for number in sorted(cells):
        exec(compile(source[number], str(SCRIPT), "exec"), ns)
        if number == CHANGE_CELL and change is not None:
            ns["c"] = pd.Series(0.0, index=ns["industries"])
            ns["import_price"] = pd.Series(0.0, index=ns["U_m"].index)
            ns["fixed"] = {}
            change(ns)
    return ns


def test_script_is_self_contained():
    source = SCRIPT.read_text()
    assert "iotables" not in source and "to_excel" not in source
    assert sorted(script_cells()) == list(range(0, 11))
    assert len(source.splitlines()) < 320


# --- the script and the module agree ----------------------------------------------------


@pytest.fixture(scope="module")
def sq():
    return build_square_table(*load_bea_tables("detail", 2017), load_import_matrix("detail", 2017))


@pytest.fixture(scope="module")
def model(sq):
    return PriceModel(sq, pce_bridge=load_pce_bridge("detail", 2017))


def same(ours, theirs, atol=1e-6):
    pd.testing.assert_frame_equal(ours, theirs.loc[ours.index, ours.columns], check_names=False, atol=atol, rtol=0)


@pytest.mark.network
def test_table_matches_module(sq):
    ns = run_script(cells=range(1, 5))
    same(ns["Z"], sq.Z)
    same(ns["F"], sq.F)
    same(ns["V"], sq.V)
    same(ns["shares"], sq.market_shares, atol=1e-12)
    same(ns["U_m"], sq.imported_inputs)
    same(ns["D_m"], sq.imported_final)
    pd.testing.assert_series_equal(ns["y"], sq.y, check_names=False, atol=1e-6, rtol=0)


def domestic(ns):
    y, V, q, shares, c = ns["y"], ns["V"], ns["q"], ns["shares"], ns["c"]
    c["211000"] += 50_000 / y["211000"]
    c["212100"] += 0.02
    c += 0.05 * q["324110"] * shares["324110"] / y
    c += 4_000 * shares["325110"] / y
    c += 0.01 * V.loc["V00100"] / y
    some = ["484000", "481000"]
    c[some] += 0.10 * V.loc["V00200", some] / y[some]


def steel(ns):
    ns["import_price"]["331110"] = 0.25


def import_and_fixed_prices(ns):
    ns["import_price"][:] = 0.10
    ns["import_price"]["336111"] += 10_000 / ns["total_imports"]["336111"]
    ns["c"]["211000"] += 10_000 / ns["y"]["211000"]
    ns["fixed"].update({"211000": 0.20, "331110": 0.05})


CHANGES = {
    "domestic": (domestic, [
        costs.IndustryCost("211000", dollars=50_000), costs.IndustryCost("212100", rate=0.02),
        costs.CommodityCost("324110", rate=0.05), costs.CommodityCost("325110", dollars=4_000),
        costs.ValueAddedCost("V00100", rate=0.01),
        costs.ValueAddedCost("V00200", rate=0.10, industries=("484000", "481000"))]),
    "steel": (steel, [costs.ImportPrice("331110", rate=0.25)]),
    "import and fixed prices": (import_and_fixed_prices, [
        costs.ImportPrice("all", rate=0.10), costs.ImportPrice("336111", dollars=10_000),
        costs.IndustryCost("211000", dollars=10_000),
        costs.IndustryPrice("211000", 0.20), costs.IndustryPrice("331110", 0.05)]),
}


def assert_results_match(ns, result):
    np.testing.assert_allclose(ns["dp"].to_numpy(), result.industry_prices["price_change"].to_numpy(), atol=1e-10)
    assert ns["total_cost"] == pytest.approx(result.summary["total_cost"], rel=1e-10)
    fd = result.burden_by_final_demand
    np.testing.assert_allclose(ns["burden"].to_numpy(), fd["burden"].to_numpy(), atol=1e-6)
    np.testing.assert_allclose(ns["spending"].to_numpy(), fd["base_spending"].to_numpy(), atol=1e-6)
    ours, theirs = ns["pce"], result.pce_prices
    assert list(ours.index.astype(str)) == list(theirs["nipa_line"])
    assert list(ours["category"]) == list(theirs["pce_category"])
    np.testing.assert_allclose(ours["price_change"].to_numpy(), theirs["price_change"].to_numpy(), atol=1e-10)
    np.testing.assert_allclose(ours["spending"].to_numpy(), theirs["base_spending"].to_numpy(), atol=1e-9)
    np.testing.assert_allclose(ours["burden"].to_numpy(), theirs["burden"].to_numpy(), atol=1e-6)
    prices = result.commodity_prices.set_index("code")
    np.testing.assert_allclose(ns["dp_c"].to_numpy(), prices.loc[ns["dp_c"].index, "price_change"].to_numpy(), atol=1e-10)
    np.testing.assert_allclose(ns["import_share"].to_numpy(),
                               prices.loc[ns["import_share"].index, "pce_import_share"].to_numpy(), atol=1e-12)


@pytest.mark.network
@pytest.mark.parametrize("name", list(CHANGES))
def test_results_match_module(model, name):
    in_script, in_module = CHANGES[name]
    assert_results_match(run_script(in_script), model.run(in_module))


@pytest.mark.network
def test_carbon_price_matches_module(sq, model):
    carbon = costs.carbon_price(50, 2024, sq)

    def in_script(ns):
        for s in carbon:
            if isinstance(s, costs.IndustryCost):
                ns["c"][s.code] += s.dollars / ns["y"][s.code]
            else:
                ns["import_price"][s.code] += s.dollars / ns["total_imports"][s.code]

    ns = run_script(in_script)
    assert_results_match(ns, model.run(carbon))
    gasoline = ns["pce"].set_index("category").loc["Gasoline and other motor fuel", "price_change"]
    assert 0.15 < gasoline < 0.22           # $50 a ton is about $0.44 a gallon


@pytest.mark.network
def test_script_writes_the_modules_result_files(model, tmp_path):
    run_script(cells=range(1, 10), output=tmp_path / "script")                  # the script's example: the steel tariff
    model.run([costs.ImportPrice("331110", rate=0.25)]).to_csv(tmp_path / "module")
    assert not [p for p in (tmp_path / "script").iterdir() if p.suffix != ".csv"]
    for name, key in (("industry_prices", "code"), ("commodity_prices", "code"),
                      ("pce_prices", "nipa_line"), ("burden_by_final_demand", "code")):
        ours = pd.read_csv(tmp_path / "script" / f"{name}.csv", dtype={"code": str}).set_index(key)
        theirs = pd.read_csv(tmp_path / "module" / f"{name}.csv", dtype={"code": str}).set_index(key)
        assert list(ours.columns) == list(theirs.columns), name
        pd.testing.assert_frame_equal(ours, theirs.loc[ours.index], check_exact=False, atol=1e-9, rtol=1e-9, obj=name)


# --- the model on BEA's data -------------------------------------------------------------


@pytest.mark.network
def test_table_balances_and_output_is_beas():
    ns = run_script(cells=range(1, 5))
    assert (ns["y"] - ns["g"]).abs().max() < 50
    costs = ns["Z"].sum() + ns["U_m"].sum() + ns["V"].sum()
    assert (ns["y"] - costs).abs().max() < 1e-6
    pd.testing.assert_frame_equal(ns["U_d"] + ns["U_m"].loc[ns["goods"]], ns["U"], atol=1e-9, rtol=0)
    assert ns["U_m"].to_numpy().sum() == pytest.approx(1_409_373, abs=1)        # BEA's matrix, less scrap


@pytest.mark.network
def test_appendix_matches_beas_requirements():
    ns = run_script(cells=[1, 10])
    assert ns["gap"].max().max() < 1e-3


@pytest.mark.network
def test_import_price_cost_and_reach():
    ns = run_script(steel)
    assert ns["total_cost"] == pytest.approx(0.25 * ns["total_imports"]["331110"])
    dp = ns["dp"]
    assert (dp > -1e-12).all() and dp.idxmax() == "331200"
    assert (dp >= 0.25 * ns["B"].loc["331110"] - 1e-12).all()                   # at least the direct cost
    assert 0 < ns["pce"]["burden"].sum() < ns["total_cost"]


@pytest.mark.network
def test_consumer_price_blends_domestic_and_imported():
    def autos(ns):
        ns["import_price"]["336111"] = 0.10

    ns = run_script(autos)
    m = ns["import_share"]["336111"]
    assert 0 < m < 1
    rows = ns["bridge"][ns["bridge"]["commodity"] == "336111"]
    np.testing.assert_allclose(rows["dp"].to_numpy(), (1 - m) * ns["dp_c"]["336111"] + m * 0.10, atol=1e-15)


@pytest.mark.network
def test_fixed_price_matches_the_textbook_solution():
    def oil_and_steel(ns):
        ns["fixed"].update({"211000": 0.20, "331110": 0.05})
        ns["c"]["211000"] = 10_000 / ns["y"]["211000"]
        ns["import_price"]["324110"] = 0.10

    ns = run_script(oil_and_steel)
    dp, A, B, v = ns["dp"], ns["A"], ns["B"], ns["v"]
    assert dp["211000"] == pytest.approx(0.20, abs=1e-10) and dp["331110"] == pytest.approx(0.05, abs=1e-10)
    # Drop the fixed industries' equations and solve the rest with their prices given.
    held = ["211000", "331110"]
    free = [c for c in ns["industries"] if c not in held]
    rhs = v[free] + A.loc[held, free].T @ (1 + dp[held]) + B[free].T @ (1 + ns["import_price"])
    p_free = np.linalg.solve(np.eye(len(free)) - A.loc[free, free].to_numpy().T, rhs.to_numpy())
    np.testing.assert_allclose(dp[free].to_numpy(), p_free - 1, atol=1e-10)


# --- a three-industry economy worked by hand ------------------------------------------------


def toy_economy() -> dict:
    """Industries and commodities A, B, C; each industry makes only its own commodity.

    Per 100 of output: A buys 20 of commodity C, all of it imported; B buys 50 of
    A; C buys nothing. Households buy 50 of A, 100 of B and 100 of C. The four
    commodities the script removes are present and empty.
    """
    names = ["A", "B", "C"]
    removed = ["S00401", "S00402", "S00300", "S00900"]
    rows = names + removed
    M = pd.DataFrame(np.diag([100.0, 100.0, 100.0]), index=names, columns=names).reindex(columns=rows, fill_value=0.0)
    U = pd.DataFrame([[0, 50, 0], [0, 0, 0], [20, 0, 0]], index=names, columns=names, dtype=float).reindex(rows, fill_value=0.0)
    D = pd.DataFrame({"F01000": [50.0, 100.0, 100.0], "F05000": [0.0, 0.0, -20.0]}, index=names).reindex(rows, fill_value=0.0)
    VA = pd.DataFrame([[50, 30, 60], [0, 0, 0], [30, 20, 40]], index=["V00100", "V00200", "V00300"], columns=names, dtype=float)
    U_m = pd.DataFrame(0.0, index=rows, columns=names)
    U_m.loc["C", "A"] = 20.0
    return {
        "industries": names, "final_uses": ["F01000", "F05000"], "buyers": ["F01000"],
        "M": M, "U": U, "D": D, "VA": VA, "g": pd.Series(100.0, index=names),
        "U_m": U_m, "D_m": pd.DataFrame(0.0, index=rows, columns=["F01000"]),
        "industry_name": {c: f"Industry {c}" for c in names},
        "final_use_name": {"F01000": "Personal consumption", "F05000": "Imports"},
    }


def run_toy(change):
    return run_script(change, cells=range(2, 8), inject=toy_economy())


def test_toy_tariff():
    ns = run_toy(lambda ns: ns["import_price"].__setitem__("C", 0.25))
    # A's costs rise by 0.20 x 25%; B's by 0.50 x A's rise; C buys nothing.
    np.testing.assert_allclose(ns["dp"].to_numpy(), [0.05, 0.025, 0.0], atol=1e-15)
    assert ns["total_cost"] == pytest.approx(5.0)                               # 25% of 20 of imports
    assert ns["burden"]["F01000"] == pytest.approx(5.0)                    # 0.05 x 50 + 0.025 x 100
    assert ns["V"].loc["V00300"].to_list() == [30.0, 20.0, 40.0]


def test_toy_fixed_price():
    ns = run_toy(lambda ns: ns["fixed"].update(A=0.10))
    np.testing.assert_allclose(ns["dp"].to_numpy(), [0.10, 0.05, 0.0], atol=1e-15)
    assert ns["total_cost"] == pytest.approx(10.0)                              # 10% of A's output of 100


def test_toy_domestic_cost_does_not_move_import_prices():
    ns = run_toy(lambda ns: ns["c"].__setitem__("C", 0.10))
    # C's price rises 10%, but A buys its C from abroad, so A and B are untouched.
    np.testing.assert_allclose(ns["dp"].to_numpy(), [0.0, 0.0, 0.10], atol=1e-15)
