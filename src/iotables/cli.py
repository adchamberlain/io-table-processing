"""Command-line entry point: `iotables build` and `iotables check`.

    iotables build [--level detail] [--year latest|2017|2012|2007]
                   [--redefinitions after|before] [--scrap bea|redistribute|keep]
                   [--scrap-codes S00401,S00402] [--out data/output]
                   [--make PATH --use PATH] [--force]
    iotables check [the build options] [--tol 1e-3]

`build` downloads (cached) and parses BEA's make and use tables, or reads the
`--make`/`--use` workbooks, builds the square table, prints its identity
residuals and the industries with the largest |y - g| and |GOS - BEA GOS|
gaps, and writes <out>/us_io_<year>_<level>_<redefinitions>_<scrap>.xlsx plus a
CSV folder of the same stem. `check` does the build, then compares the table's
industry-by-industry total requirements (I - A)^-1, A = Z diag(y)^-1, with
BEA's published IxI total requirements table for the same year.

`check` builds with BEA's published-table convention by default: scrap mode
"bea" with scrap codes S00402 only, so scrap S00401 stays an ordinary
commodity and used goods S00402 are removed (`build` defaults to both codes,
the handbook's nonscrap-ratio treatment). Output names gain
"_scrap-<codes>" when the scrap codes are not the library default.

Exit status: 0 success (for `check`, max |ours - BEA| <= --tol); 1 `check`
found a larger difference; 2 bad arguments or a failure (missing file,
download or parse error, broken identity), reported in one line on stderr.
"""

import argparse
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl.utils.exceptions import InvalidFileException

from iotables import download, parse, sources, square, validate

YEARS = ("latest", "2017", "2012", "2007")
# Default --scrap-codes per command. BEA's published requirements tables keep
# scrap S00401 as an ordinary commodity and remove only used goods S00402.
PUBLISHED_SCRAP_CODES = ("S00402",)
DEFAULT_SCRAP_CODES = {"build": square.SCRAP_CODES, "check": PUBLISHED_SCRAP_CODES}
_N_GAPS = 10  # industries listed per build diagnostic
_N_WORST = 5  # cells listed by check
# Failures reported as "iotables: error: ..." instead of a traceback. OSError
# covers missing files and requests' download errors; ValueError covers parse
# and identity errors and numpy's LinAlgError; KeyError a missing worksheet.
_ERRORS = (OSError, ValueError, KeyError, NotImplementedError, zipfile.BadZipFile, InvalidFileException)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI on `argv` (default sys.argv[1:]); returns the exit status.

    Argument errors exit through argparse (SystemExit with status 2).
    """
    parser = _parser()
    args = parser.parse_args(argv)
    if (args.make is None) != (args.use is None):
        parser.error("--make and --use must be given together")
    for option in ("make", "use"):
        path = getattr(args, option)
        if path is not None and not path.is_file():
            parser.error(f"--{option}: no such file: {path}")
    if args.command == "check" and not args.tol >= 0:  # also rejects NaN
        parser.error(f"--tol must be a nonnegative number, got {args.tol}")
    args.scrap_codes_given = args.scrap_codes is not None
    if args.scrap_codes_given and args.scrap == "keep":
        parser.error("--scrap-codes has no effect with --scrap keep")
    if not args.scrap_codes_given:
        args.scrap_codes = DEFAULT_SCRAP_CODES[args.command]
    try:
        if args.command == "build":
            _build(args)
            return 0
        return _check(args)
    except _ERRORS as e:
        print(f"iotables: error: {e}", file=sys.stderr)
        return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="iotables",
        description="Square industry-by-industry U.S. input-output tables from BEA make and use tables.",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    build = commands.add_parser("build", help="build the square table and write it",
                                description="Build the square table, print its checks and write xlsx and CSV.")
    check = commands.add_parser("check",
                                help="build, then compare with BEA's industry-by-industry total requirements",
                                description="Build the table, then compare (I - A)^-1 with BEA's IxI "
                                            "total requirements table; exit 1 if any cell differs by more than --tol.")
    for command, sub in (("build", build), ("check", check)):
        _add_table_options(sub, DEFAULT_SCRAP_CODES[command])
    check.add_argument("--tol", type=float, default=1e-3,
                       help="largest allowed |ours - BEA| (default %(default)s)")
    return parser


def _add_table_options(sub: argparse.ArgumentParser, scrap_codes_default: tuple[str, ...]) -> None:
    """The options `build` and `check` share; --scrap-codes defaults to None (resolved in `main`)."""
    sub.add_argument("--level", choices=("detail",), default="detail",
                     help="table level (summary arrives in Phase 2; default %(default)s)")
    sub.add_argument("--year", choices=YEARS, default="latest",
                     help="table year; latest = the newest year sheet (default %(default)s)")
    sub.add_argument("--redefinitions", choices=("after", "before"), default="after",
                     help="BEA make/use tables after or before redefinitions (default %(default)s)")
    sub.add_argument("--scrap", choices=square.SCRAP_MODES, default="bea",
                     help="treatment of scrap and used goods (default %(default)s)")
    sub.add_argument("--scrap-codes", type=_codes, metavar="CODES",
                     help="comma-separated commodity codes the scrap mode treats as scrap and used goods "
                          f"(default {','.join(scrap_codes_default)})")
    sub.add_argument("--out", type=Path, default=sources.OUTPUT_DIR, metavar="DIR",
                     help="output directory (default %(default)s)")
    sub.add_argument("--make", type=Path, metavar="PATH",
                     help="read this make workbook instead of downloading BEA's (needs --use)")
    sub.add_argument("--use", type=Path, metavar="PATH",
                     help="read this use workbook instead of downloading BEA's (needs --make)")
    sub.add_argument("--force", action="store_true",
                     help="download BEA files again even when cached")


def _codes(text: str) -> tuple[str, ...]:
    """Parse a comma-separated code list; empty entries are an error."""
    codes = tuple(c.strip() for c in text.split(","))
    if not all(codes):
        raise argparse.ArgumentTypeError(f"empty code in {text!r}")
    return codes


def _build(args: argparse.Namespace) -> square.SquareIOTable:
    """Load, build, check, print the diagnostics and write the outputs; returns the table."""
    year = args.year if args.year == "latest" else int(args.year)
    if args.make is None:
        make, use = parse.load_bea_tables(args.level, year, args.redefinitions, force=args.force)
    else:
        make, use = parse.parse_make(args.make, year), parse.parse_use(args.use, year)
        for table in (make, use):
            table.meta.update(level=args.level, redefinitions=args.redefinitions)
    if make.meta["year"] != use.meta["year"]:
        raise ValueError(f"the make table is for {make.meta['year']} but the use table for {use.meta['year']}")
    if args.scrap_codes_given:  # the library ignores absent codes; a code named on the command line must exist
        absent = [c for c in args.scrap_codes if c not in use.commodities]
        if absent:
            raise ValueError(f"--scrap-codes: not commodities in the use table: {absent}")
    sq = square.build_square_table(make, use, scrap=args.scrap, scrap_codes=args.scrap_codes)
    residuals = sq.check_identities()
    meta = sq.meta
    scrap = args.scrap if args.scrap == "keep" else f"{args.scrap} (scrap codes {','.join(args.scrap_codes)})"
    print(f"Built the {meta['year']} {meta['level']} table, {meta['redefinitions']} redefinitions, "
          f"scrap mode {scrap}: {sq.n} industries, {len(sq.F.columns)} final-demand columns")
    print()
    print("Identity residuals ($ millions):")
    for name, value in residuals.items():
        print(f"  {name:<18} {value:.3e}")
    diagnostics = meta["diagnostics"]
    _print_gaps("|y - g| (our industry output minus BEA's)", diagnostics["y_minus_g"], sq.industry_labels)
    _print_gaps("|GOS - BEA GOS| (our gross operating surplus minus BEA's)",
                diagnostics["gos_minus_bea"], sq.industry_labels)
    stem = f"us_io_{meta['year']}_{meta['level']}_{meta['redefinitions']}_{args.scrap}"
    if args.scrap != "keep" and set(args.scrap_codes) != set(square.SCRAP_CODES):
        stem += "_scrap-" + "-".join(args.scrap_codes)
    xlsx = sq.to_excel(args.out / f"{stem}.xlsx")
    sq.to_csv(args.out / stem)
    print()
    print("Wrote:")
    print(f"  table {xlsx}")
    print(f"  CSVs  {args.out / stem}")
    return sq


def _print_gaps(heading: str, gaps: pd.Series, labels: pd.Series) -> None:
    """The industries with the largest |gap|: code, signed value ($ millions), description."""
    largest = gaps.loc[gaps.abs().sort_values(ascending=False, kind="stable").index[:_N_GAPS]]
    print()
    print(f"Largest {heading}, $ millions; total {gaps.sum():+,.3f}:")
    for code, value in largest.items():
        print(f"  {code:<8} {value:>+15,.3f}  {labels.loc[code]}")


def _check(args: argparse.Namespace) -> int:
    """Build, then compare with BEA's IxI total requirements; 0 within --tol, else 1."""
    if args.scrap == "bea" and tuple(args.scrap_codes) == PUBLISHED_SCRAP_CODES:
        print("Comparing with BEA's published table convention: scrap S00401 kept as a commodity, "
              "used goods S00402 removed; pass --scrap/--scrap-codes to compare another configuration")
        print()
    sq = _build(args)
    ours = validate.ixi_total_requirements(sq)
    path = download.fetch(sources.bea_detail_url("ixi_tr", "any"), sources.RAW_DIR / "bea", force=args.force)
    sheet = str(sq.meta["year"])
    years = parse.list_year_sheets(path)
    if int(sheet) not in years:
        raise ValueError(f"{path}: no sheet for year {sheet}; available years: {years}")
    grid = parse.read_bea_grid(path, sheet).values
    bea = grid.loc[  # BEA's totals (row T009) are not requirements
        [c for c in grid.index if not c.startswith("T0")], [c for c in grid.columns if not c.startswith("T0")]
    ]
    for axis, theirs in (("row", bea.index), ("column", bea.columns)):
        only_ours, only_bea = ours.index.difference(theirs), theirs.difference(ours.index)
        if len(only_ours) or len(only_bea):
            raise ValueError(f"BEA's requirements table and ours have different {axis} industries: "
                             f"only in ours {list(only_ours)}, only in BEA's {list(only_bea)}")
    bea = bea.loc[ours.index, ours.columns]
    diff = ours.to_numpy() - bea.to_numpy()
    abs_diff = np.abs(diff)
    max_abs, mean_abs = float(abs_diff.max()), float(abs_diff.mean())  # NaN propagates
    print()
    print(f"Industry-by-industry total requirements vs BEA ({path.name}, sheet {sheet}), {sq.n} x {sq.n} cells:")
    print(f"  max_abs_diff   {max_abs:.3e}")
    print(f"  mean_abs_diff  {mean_abs:.3e}")
    print(f"  cells beyond tol {args.tol:g}: {int((~(abs_diff <= args.tol)).sum())}")
    print()
    print("Largest |ours - BEA| (row: industry whose output is required; column: industry whose final demand requires it):")
    worst = np.argsort(abs_diff, axis=None)[::-1][:_N_WORST]  # NaN sorts last, so first after the reversal
    labels = sq.industry_labels
    for i, j in zip(*np.unravel_index(worst, abs_diff.shape)):
        row, col = ours.index[i], ours.columns[j]
        print(f"  {row:<8} {col:<8} ours {ours.iat[i, j]:.7f}  BEA {bea.iat[i, j]:.7f}  diff {diff[i, j]:+.2e}"
              f"  {labels.loc[row]} / {labels.loc[col]}")
    print()
    if max_abs <= args.tol:
        print(f"Within tolerance {args.tol:g}.")
        return 0
    print(f"Exceeds tolerance {args.tol:g}.")
    return 1
