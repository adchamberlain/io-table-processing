"""iotables: square industry-by-industry U.S. input-output tables from BEA make
and use tables, and a Leontief price model on top of them.

Pipeline (one module per stage, see each module's docstring):

    download  ->  parse  ->  square  ->  leontief
    (BEA xlsx)   (clean      (n x n       (price pass-through
                  DataFrames) IO table)    model for policy)

`load_bea_tables` downloads and parses BEA's benchmark detail make and use
tables and `load_import_matrix` its import matrix, and `build_square_table`
turns them into a balanced square table
(intermediate flows Z, final demand F, value added V, industry output y) under
the industry-technology assumption, with BEA's nonscrap-ratio treatment of
scrap by default. `PriceModel` passes taxes and cost shocks through that table
(`shocks`: on an industry, a commodity, a buyer-seller flow or a value-added
component, plus a carbon-price preset from EIA emissions) and returns a
`PriceResult`: price changes by industry, by commodity and, with BEA's PCE
bridge (`load_pce_bridge`), by consumer spending category, with the burden on
each final-demand component. Dollars are millions and price changes are
fractions. `script/io_model.py` in the repository is the same method as one
script, and the two are tested to give the same results.
"""

__version__ = "0.0.1"

# square reads __version__, so the imports come after it.
from iotables import shocks  # noqa: E402
from iotables.bridge import load_pce_bridge  # noqa: E402
from iotables.leontief import PriceModel, PriceResult  # noqa: E402
from iotables.parse import load_bea_tables, load_import_matrix  # noqa: E402
from iotables.square import SquareIOTable, build_square_table  # noqa: E402

__all__ = [
    "PriceModel",
    "PriceResult",
    "SquareIOTable",
    "__version__",
    "build_square_table",
    "load_bea_tables",
    "load_import_matrix",
    "load_pce_bridge",
    "shocks",
]
