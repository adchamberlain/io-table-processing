"""Smoke test: the package imports and exports its public API."""

import iotables


def test_package_imports() -> None:
    assert iotables.__version__


def test_package_exports_the_pipeline_and_price_model() -> None:
    from iotables import (PriceModel, PriceResult, SquareIOTable, build_square_table, load_bea_tables,
                          load_import_matrix, load_pce_bridge, costs)
    assert PriceModel is iotables.leontief.PriceModel and PriceResult is iotables.leontief.PriceResult
    assert load_pce_bridge is iotables.bridge.load_pce_bridge and costs.carbon_price
    assert {"PriceModel", "PriceResult", "load_pce_bridge", "costs"} <= set(iotables.__all__)
    assert "scaffolding" not in iotables.__doc__
