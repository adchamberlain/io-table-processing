"""Command-line entry point: `iotables build`, `iotables check` and `iotables run`.

    iotables build [--level detail] [--year latest|2017|2012|2007]
                   [--redefinitions after|before] [--scrap bea|redistribute|keep]
                   [--scrap-codes S00401,S00402] [--out data/output]
                   [--make PATH --use PATH] [--force]
    iotables check [the build options] [--tol 1e-3]
    iotables run   [the build options | --table PATH.xlsx] (--shock SPEC)...
                   [--carbon DOLLARS_PER_TON --emissions-year YYYY]
                   [--formulation output_tax|wp6] [--no-pce]

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

`run` builds the table as `build` does (and writes it), or reads one that
`build` wrote (--table; its CSV folder of the same stem, when present, supplies
the market shares the xlsx lacks, and without it the run gives industry prices
and final-demand burdens only). It then runs the price model (`leontief`) on
the shocks, at least one: each --shock SPEC (SHOCK_GRAMMAR; dollars in $
millions, rates as fractions) and the --carbon preset, a $/ton CO2 price on the
emissions of --emissions-year (`shocks.carbon_price`). Unless --no-pce, the PCE
bridge for the table's year is loaded and the run reaches consumer prices. It
writes <out>/industry_prices.csv, commodity_prices.csv, pce_prices.csv,
burden_by_final_demand.csv, summary.json (the result's summary, the table, the
carbon price and the notes) and shocks.json (each shock's type and fields); a
part the run does not produce is written with its header row only, so a
directory never mixes two runs. It prints the summary and the 20 PCE categories
with the largest price increases. --level gives the carbon preset's level for
a --table that does not record one; --force also downloads the PCE bridge and
EIA data again.

Exit status: 0 success (for `check`, max |ours - BEA| <= --tol); 1 `check`
found a larger difference; 2 bad arguments or a failure (missing file,
download or parse error, broken identity, unknown shock code), reported in one
line on stderr.
"""

import argparse
import dataclasses
import json
import math
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl.utils.exceptions import InvalidFileException

from iotables import bridge, download, leontief, parse, shocks, sources, square, validate

YEARS = ("latest", "2017", "2012", "2007")
# Default --scrap-codes per command. BEA's published requirements tables keep
# scrap S00401 as an ordinary commodity and remove only used goods S00402.
PUBLISHED_SCRAP_CODES = ("S00402",)
DEFAULT_SCRAP_CODES = {"build": square.SCRAP_CODES, "check": PUBLISHED_SCRAP_CODES, "run": square.SCRAP_CODES}
# The table options' defaults; `run --table` rejects the ones that only apply to a build.
TABLE_DEFAULTS = {"level": "detail", "year": "latest", "redefinitions": "after", "scrap": "bea"}
SHOCK_GRAMMAR = ("industry:CODE:dollars=X | industry:CODE:rate=R | commodity:CODE:dollars=X | "
                 "commodity:CODE:rate=R | flow:SELLER:BUYER:rate=R | va:COMPONENT:rate=R[:industries=A,B]")
RESULT_FILES = ("industry_prices.csv", "commodity_prices.csv", "pce_prices.csv", "burden_by_final_demand.csv",
                "summary.json", "shocks.json")
# The PriceResult frames' columns, for the header-only file of a part a run does not produce.
_RESULT_COLUMNS = {
    "commodity_prices": ["code", "description", "pct_change"],
    "pce_prices": ["nipa_line", "pce_category", "pct_change", "base_spending", "burden"],
}
_TABLE_PARTS = ("market_shares.csv", "labels.csv", "meta.json")  # what --table needs from the CSV folder
_N_GAPS = 10  # industries listed per build diagnostic
_N_WORST = 5  # cells listed by check
_N_PCE = 20  # PCE categories listed by run
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
    if args.command == "run":
        _check_run_arguments(parser, args)
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
        if args.command == "run":
            return _run(args)
        return _check(args)
    except _ERRORS as e:
        message = e.args[0] if isinstance(e, KeyError) and e.args else e  # str(KeyError) adds quotes
        print(f"iotables: error: {message}", file=sys.stderr)
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
    run = commands.add_parser("run", help="run the price model on shocks: industry, commodity and consumer prices",
                              description="Build the table (or read one with --table), run the price model on "
                                          "the shocks and write the price changes and burdens.")
    for command, sub in (("build", build), ("check", check), ("run", run)):
        _add_table_options(sub, DEFAULT_SCRAP_CODES[command])
    check.add_argument("--tol", type=float, default=1e-3,
                       help="largest allowed |ours - BEA| (default %(default)s)")
    run.add_argument("--table", type=Path, metavar="PATH",
                     help="read this table (an xlsx file build wrote) instead of building one")
    run.add_argument("--shock", action="append", metavar="SPEC",
                     help=f"a shock, repeatable: {SHOCK_GRAMMAR} (dollars in $ millions, rates as fractions)")
    run.add_argument("--carbon", type=float, metavar="DOLLARS_PER_TON",
                     help="carbon price in $ per metric ton of CO2, upstream (needs --emissions-year)")
    run.add_argument("--emissions-year", type=int, metavar="YYYY",
                     help="year of the EIA CO2 emissions the carbon price applies to")
    run.add_argument("--formulation", choices=leontief.FORMULATIONS, default="output_tax",
                     help="price model formulation; wp6 only reproduces Tax Foundation WP6 (default %(default)s)")
    run.add_argument("--no-pce", action="store_true",
                     help="skip the PCE bridge: no consumer-category prices")
    return parser


def _add_table_options(sub: argparse.ArgumentParser, scrap_codes_default: tuple[str, ...]) -> None:
    """The options every command shares; --scrap-codes defaults to None (resolved in `main`)."""
    sub.add_argument("--level", choices=("detail",), default=TABLE_DEFAULTS["level"],
                     help="table level (summary arrives in Phase 2; default %(default)s)")
    sub.add_argument("--year", choices=YEARS, default=TABLE_DEFAULTS["year"],
                     help="table year; latest = the newest year sheet (default %(default)s)")
    sub.add_argument("--redefinitions", choices=("after", "before"), default=TABLE_DEFAULTS["redefinitions"],
                     help="BEA make/use tables after or before redefinitions (default %(default)s)")
    sub.add_argument("--scrap", choices=square.SCRAP_MODES, default=TABLE_DEFAULTS["scrap"],
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
                     help="download source files again even when cached")


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
    _print_residuals(residuals)
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


def _print_residuals(residuals: dict[str, float]) -> None:
    print()
    print("Identity residuals ($ millions):")
    for name, value in residuals.items():
        print(f"  {name:<18} {value:.3e}")


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


# --- iotables run ------------------------------------------------------------------


def parse_shock_spec(spec: str) -> shocks.Shock:
    """One --shock SPEC as a shock; the grammar is SHOCK_GRAMMAR.

    X is $ millions and R a fraction, both finite numbers; `industries=A,B` limits a
    value-added tax to those industries. A bad spec prints "iotables: error: ..."
    with the grammar to stderr and raises SystemExit(2), as argparse does.
    """
    try:
        return _shock_from_spec(spec)
    except ValueError as e:
        print(f"iotables: error: bad shock spec {spec!r}: {e}. A shock is one of: {SHOCK_GRAMMAR}", file=sys.stderr)
        raise SystemExit(2) from None


def _shock_from_spec(spec: str) -> shocks.Shock:
    kind, *fields = spec.split(":")
    if kind in ("industry", "commodity"):
        if len(fields) != 2:
            raise ValueError(f"{kind} takes CODE and dollars=X or rate=R")
        key, value = _number(fields[1], ("dollars", "rate"))
        shock_type = shocks.IndustryTax if kind == "industry" else shocks.CommodityTax
        return shock_type(_code(fields[0]), **{key: value})
    if kind == "flow":
        if len(fields) != 3:
            raise ValueError("flow takes SELLER, BUYER and rate=R")
        return shocks.FlowTax(_code(fields[0]), _code(fields[1]), _number(fields[2], ("rate",))[1])
    if kind == "va":
        if len(fields) not in (2, 3):
            raise ValueError("va takes COMPONENT, rate=R and optionally industries=A,B")
        industries = None
        if len(fields) == 3:
            industries = tuple(_code(c) for c in _field(fields[2], ("industries",))[1].split(","))
        return shocks.ValueAddedTax(_code(fields[0]), _number(fields[1], ("rate",))[1], industries)
    raise ValueError(f"unknown shock type {kind!r}")


def _field(text: str, keys: tuple[str, ...]) -> tuple[str, str]:
    """`text` as KEY=VALUE with KEY one of `keys`."""
    key, sep, value = text.partition("=")
    if not sep or key not in keys:
        raise ValueError(f"expected {' or '.join(k + '=...' for k in keys)}, got {text!r}")
    return key, value


def _number(text: str, keys: tuple[str, ...]) -> tuple[str, float]:
    """`text` as KEY=NUMBER with KEY one of `keys` and a finite number."""
    key, value = _field(text, keys)
    try:
        number = float(value)
    except ValueError:
        raise ValueError(f"{key} must be a number, got {value!r}") from None
    if not math.isfinite(number):
        raise ValueError(f"{key} must be a finite number, got {value!r}")
    return key, number


def _code(text: str) -> str:
    code = text.strip()
    if not code:
        raise ValueError("empty code")
    return code


def format_shock_spec(shock: shocks.Shock) -> str:
    """A shock in SHOCK_GRAMMAR form, the inverse of `parse_shock_spec`."""
    if isinstance(shock, (shocks.IndustryTax, shocks.CommodityTax)):
        kind = "industry" if isinstance(shock, shocks.IndustryTax) else "commodity"
        key, value = ("dollars", shock.dollars) if shock.dollars is not None else ("rate", shock.rate)
        return f"{kind}:{shock.code}:{key}={value}"
    if isinstance(shock, shocks.FlowTax):
        return f"flow:{shock.seller}:{shock.buyer}:rate={shock.rate}"
    industries = "" if shock.industries is None else f":industries={','.join(shock.industries)}"
    return f"va:{shock.component}:rate={shock.rate}{industries}"


def _check_run_arguments(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Reject inconsistent `run` options (exit 2) and parse the shock specs into `args.shocks`."""
    if args.table is not None:
        build_only = [f"--{name}" for name, default in TABLE_DEFAULTS.items()
                      if name != "level" and getattr(args, name) != default]
        build_only += [f"--{name}" for name in ("make", "use") if getattr(args, name) is not None]
        if args.scrap_codes is not None:
            build_only.append("--scrap-codes")
        if build_only:
            parser.error(f"--table reads a built table; {', '.join(build_only)} only apply when run builds one")
        if not args.table.is_file():
            parser.error(f"--table: no such file: {args.table}")
    if (args.carbon is None) != (args.emissions_year is None):
        parser.error("--carbon and --emissions-year must be given together")
    if args.carbon is not None and not math.isfinite(args.carbon):
        parser.error(f"--carbon must be a finite number, got {args.carbon}")
    if not args.shock and args.carbon is None:
        parser.error("run needs at least one --shock or --carbon")
    args.shocks = [parse_shock_spec(spec) for spec in args.shock or []]


def _run(args: argparse.Namespace) -> int:
    """Build or read the table, run the price model, write and print the results; returns 0."""
    if args.table is None:
        sq, notes = _build(args), []
        table = {k: sq.meta[k] for k in ("year", "level", "redefinitions")}
        table["scrap_mode"] = args.scrap
        if args.scrap != "keep":
            table["scrap_codes"] = list(args.scrap_codes)
    else:
        sq, notes = _read_table(args.table)
        table = {k: sq.meta[k] for k in ("year", "level", "redefinitions") if k in sq.meta}
        if "scrap_mode" in sq.meta.get("diagnostics", {}):
            table["scrap_mode"] = sq.meta["diagnostics"]["scrap_mode"]
        table["path"] = str(args.table)
    has_commodities = "commodity_output" in sq.meta
    run_shocks = list(args.shocks)
    if not has_commodities and any(isinstance(s, shocks.CommodityTax) for s in run_shocks):
        raise ValueError(f"commodity shocks need the table's market shares, which {args.table} lacks without "
                         f"its CSV folder {args.table.with_suffix('')}")
    level = sq.meta.get("level", args.level)
    carbon = None
    if args.carbon is not None:
        run_shocks += shocks.carbon_price(args.carbon, args.emissions_year, level=level, force=args.force)
        carbon = {"dollars_per_ton_co2": args.carbon, "emissions_year": args.emissions_year, "coverage": "upstream"}
    pce_bridge = None
    if has_commodities and not args.no_pce:
        if "year" not in sq.meta:
            raise ValueError("the table records no year, and the PCE bridge must be the table's year's; "
                             "pass --no-pce to run without it")
        pce_bridge = bridge.load_pce_bridge(level, year=sq.meta["year"], force=args.force)
    result = leontief.PriceModel(sq, pce_bridge=pce_bridge, formulation=args.formulation).run(run_shocks)
    notes += result.notes
    paths = _write_results(args.out, result, {"table": table, "carbon": carbon, "notes": notes})
    print()
    print(f"Shocks ({len(result.shocks)}; dollars in $ millions, rates as fractions):")
    for shock in result.shocks:
        print(f"  {format_shock_spec(shock)}")
    _print_summary(result.summary)
    if result.pce_prices is not None:
        _print_largest_pce(result.pce_prices)
    if notes:
        print()
        print("Notes:")
        for note in notes:
            print(f"  {note}")
    print()
    print("Wrote results:")
    for path in paths:
        print(f"  {path.suffix[1:]:<4} {path}")
    return 0


def _read_table(path: Path) -> tuple[square.SquareIOTable, list[str]]:
    """The table in the xlsx at `path`, with its CSV folder's parts when they are all there, and notes.

    The CSV folder is the one `build` writes next to the xlsx, of the same stem.
    A table read with it is checked like a built one (`check_identities`).
    """
    folder = path.with_suffix("")
    frame = square.read_square_frame(path)
    missing = [name for name in _TABLE_PARTS if not (folder / name).is_file()]
    if missing:
        sq = square.SquareIOTable.from_frame(frame, {"table": str(path)})
        print(f"Read the table {path}: {sq.n} industries, {len(sq.F.columns)} final-demand columns")
        return sq, [f"{path} was read without its CSV folder ({folder} has no {', '.join(missing)}), so the "
                    "table has no market shares: the run gives industry prices and final-demand burdens only, "
                    "with no commodity or PCE prices"]
    sq = square.SquareIOTable.from_frame(frame, {"table": str(path)}, csv_dir=folder)
    residuals = sq.check_identities()
    described = " ".join(str(sq.meta[k]) for k in ("year", "level") if k in sq.meta)
    print(f"Read the {described + ' ' if described else ''}table {path} with its CSV folder {folder}: "
          f"{sq.n} industries, {len(sq.F.columns)} final-demand columns")
    _print_residuals(residuals)
    return sq, []


def _write_results(out: Path, result: leontief.PriceResult, extra: dict) -> list[Path]:
    """Write RESULT_FILES into `out`; a part the run did not produce gets its header row only."""
    out.mkdir(parents=True, exist_ok=True)
    paths = [out / name for name in RESULT_FILES]
    for path in paths[:4]:
        frame = getattr(result, path.stem)
        if frame is None:
            frame = pd.DataFrame(columns=_RESULT_COLUMNS[path.stem])
        frame.to_csv(path, index=False)
    paths[4].write_text(json.dumps({**result.summary, **extra}, indent=2) + "\n")
    specs = [{"type": type(s).__name__, **dataclasses.asdict(s)} for s in result.shocks]
    paths[5].write_text(json.dumps(specs, indent=2) + "\n")
    return paths


def _print_summary(summary: dict) -> None:
    print()
    print(f"Price model summary, formulation {summary['formulation']} ($ millions):")
    for key, value in summary.items():
        if key == "formulation":
            continue
        if value is None:
            shown = "n/a (no PCE prices)" if summary["pce_burden"] is None else "n/a (no tax)"
        elif key == "identity_residual":
            shown = f"{value:.3e}"
        elif key == "pce_share_of_burden":
            shown = f"{value:.4f} (PCE burden / total tax)"
        else:
            shown = f"{value:,.3f}"
        print(f"  {key:<20} {shown}")


def _print_largest_pce(pce: pd.DataFrame) -> None:
    """The _N_PCE NIPA lines with the largest price increases: line, change, base spending, burden, category."""
    top = pce.sort_values("pct_change", ascending=False, kind="stable").head(_N_PCE)
    print()
    print(f"The {len(top)} PCE categories with the largest price increases, of {len(pce)} NIPA lines ($ millions):")
    print(f"  {'line':<6} {'change':>9} {'base spending':>15} {'burden':>13}  category")
    for row in top.itertuples(index=False):
        print(f"  {row.nipa_line:<6} {row.pct_change:>9.3%} {row.base_spending:>15,.1f} {row.burden:>13,.1f}"
              f"  {row.pce_category}")
