"""iotables: build square industry-by-industry U.S. input-output tables from BEA
make and use tables, and run Leontief price models on top of them.

Pipeline (one module per stage, see each module's docstring):

    download  ->  parse  ->  square  ->  leontief
    (BEA xlsx)   (clean      (n x n       (price pass-through
                  DataFrames) IO table)    model for policy)

Status: scaffolding only. Design doc lives in docs/superpowers/specs/.
"""

__version__ = "0.0.1"

from iotables.parse import load_bea_tables  # noqa: E402  (after __version__: square reads it)
from iotables.square import SquareIOTable, build_square_table  # noqa: E402

__all__ = ["SquareIOTable", "__version__", "build_square_table", "load_bea_tables"]
