# io-table-processing

Build a clean, square, industry-by-industry U.S. input-output table from the
Bureau of Economic Analysis (BEA) make and use tables, entirely in Python, and
use it to run Leontief price models of climate policy (carbon tax, cap and trade).

This replaces a spreadsheet workflow described in `docs/reference/IO_Methodology.pdf`
and applied in `docs/reference/wp6.pdf`.

## Status

Scaffolding only (2026-11-22). See `DEVLOG.txt` for the running work log and
`docs/superpowers/specs/` for the design document once written.

## Planned layout

```
src/iotables/
  download.py   fetch BEA make/use tables to data/raw/
  parse.py      raw xlsx -> clean labeled DataFrames
  square.py     make + use -> n x n industry table (+ final demand, value added)
  leontief.py   price pass-through model for policy analysis
  cli.py        `iotables build`
tests/          pytest suite (validates against the hand-built 2002 tables)
data/raw/       downloaded sources (git-ignored)
data/output/    generated square tables (git-ignored)
docs/           design docs and reference notes
archive/        earlier attempt, for reference only
```

## Development

```
pip install -e ".[dev]"
pytest
```
