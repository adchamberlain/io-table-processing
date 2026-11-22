"""Smoke test: the package imports. Real tests arrive with the implementation."""

import iotables


def test_package_imports() -> None:
    assert iotables.__version__
