"""iotables: build square industry-by-industry U.S. input-output tables from BEA
make and use tables, and run Leontief price models on top of them.

Pipeline (one module per stage, see each module's docstring):

    download  ->  parse  ->  square  ->  leontief
    (BEA xlsx)   (clean      (n x n       (price pass-through
                  DataFrames) IO table)    model for policy)

Status: scaffolding only. Design doc lives in docs/superpowers/specs/.
"""

__version__ = "0.0.1"
