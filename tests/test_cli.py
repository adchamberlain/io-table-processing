# tests/test_cli.py
import numpy as np, pandas as pd, pytest
from iotables import cli, download, parse, sources, square
from conftest import write_bea_workbook, write_grid_workbook

def test_build_cli_writes_outputs(tmp_path, toy_workbooks):     # toy_workbooks: (make_path, use_path) written with write_bea_workbook
    make_p, use_p = toy_workbooks
    rc = cli.main(["build", "--make", str(make_p), "--use", str(use_p), "--year", "2017", "--out", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "us_io_2017_detail_after_bea.xlsx").exists() and (tmp_path / "us_io_2017_detail_after_bea" / "Z.csv").exists()

def _line_with(out, *parts):
    """The one output line containing every part."""
    lines = [line for line in out.splitlines() if all(p in line for p in parts)]
    assert len(lines) == 1, (parts, lines)
    return lines[0]

def _section(out, heading):
    """The lines under the one heading line containing `heading` (a section ends at a blank line)."""
    blocks = [b.splitlines() for b in out.split("\n\n") if b.strip()]
    matches = [b for b in blocks if heading in b[0]]
    assert len(matches) == 1, (heading, out)
    return matches[0][1:]

def test_build_cli_prints_residuals_largest_gaps_and_paths(tmp_path, toy_workbooks, capsys):
    make_p, use_p = toy_workbooks
    out_dir = tmp_path / "out"
    rc = cli.main(["build", "--make", str(make_p), "--use", str(use_p), "--year", "latest", "--redefinitions", "before",
                   "--scrap", "redistribute", "--out", str(out_dir)])
    out = capsys.readouterr().out
    assert rc == 0
    assert [line.split()[0] for line in _section(out, "Identity residuals")] == ["row_minus_col", "shares_minus_one", "y_minus_rowsum"]
    sq = square.build_square_table(parse.parse_make(make_p), parse.parse_use(use_p), scrap="redistribute")
    d = sq.meta["diagnostics"]
    for key, heading in (("y_minus_g", "|y - g|"), ("gos_minus_bea", "|GOS - BEA GOS|")):
        gaps = d[key]
        assert gaps.abs().max() > 0.5                            # redistribute moves output: real gaps to print
        lines = _section(out, heading)
        assert [line.split()[0] for line in lines] == list(gaps.abs().sort_values(ascending=False).index)
        for line in lines:
            code = line.split()[0]
            assert line.split()[1] == f"{gaps[code]:+,.3f}" and line.endswith(f"Industry {code}")
    assert out.index("Identity residuals") < out.index("|y - g|") < out.index("|GOS - BEA GOS|") < out.index("Wrote")
    stem = "us_io_2017_detail_before_redistribute"                  # "latest" resolves to the newest sheet
    assert [line.split(None, 1)[1] for line in _section(out, "Wrote")] == [str(out_dir / f"{stem}.xlsx"), str(out_dir / stem)]
    assert (out_dir / f"{stem}.xlsx").exists() and (out_dir / stem / "square.csv").exists()

def test_build_cli_downloads_bea_tables_without_make_and_use(tmp_path, toy_make, toy_use, monkeypatch):
    calls = []
    def fake_load(level, year, redefinitions, *, force=False):
        calls.append((level, year, redefinitions, force))
        for table in (toy_make, toy_use):
            table.meta.update(year=2017, level=level, redefinitions=redefinitions)
        return toy_make, toy_use
    monkeypatch.setattr(parse, "load_bea_tables", fake_load)
    assert cli.main(["build", "--redefinitions", "before", "--scrap", "keep", "--force", "--out", str(tmp_path)]) == 0
    assert cli.main(["build", "--year", "2017", "--out", str(tmp_path)]) == 0
    assert calls == [("detail", "latest", "before", True), ("detail", 2017, "after", False)]
    assert (tmp_path / "us_io_2017_detail_before_keep.xlsx").exists() and (tmp_path / "us_io_2017_detail_after_bea.xlsx").exists()


def _toy_requirements(make_p, use_p, scrap_codes=("S00402",)):
    """(I - A)^-1 with A = Z / y for the toy table in mode "bea" with `scrap_codes` (default: check's
    published-table convention), computed here with numpy, and its industry labels."""
    sq = square.build_square_table(parse.parse_make(make_p, 2017), parse.parse_use(use_p, 2017), scrap="bea",
                                   scrap_codes=scrap_codes)
    L = np.linalg.inv(np.eye(sq.n) - sq.Z.to_numpy() / sq.y.to_numpy())
    return pd.DataFrame(L, index=sq.industries, columns=sq.industries), sq.industry_labels

def _write_bea_ixi(path, L, labels, *, sheet="2017"):
    """L in the layout of BEA's IxI total requirements workbook: codes in reverse order and a T009 total row."""
    path.parent.mkdir(parents=True, exist_ok=True)
    order = list(L.index[::-1])
    totals = L.loc[:, order].sum(axis=0)
    write_bea_workbook(path, sheet=sheet, title="Industry-by-Industry Total Requirements Table, 2017",
                       col_codes=order, col_descs=[labels[c] for c in order],
                       rows=[(r, labels[r], [float(v) for v in L.loc[r, order]]) for r in order]
                       + [("T009", "Total Industry Output Requirements", [float(v) for v in totals])])

@pytest.fixture
def fake_ixi(tmp_path, monkeypatch):
    """download.fetch returns tmp_path/bea/IxI.xlsx (write it with _write_bea_ixi); the calls are recorded."""
    path, calls = tmp_path / "bea" / "IxI.xlsx", []
    def fake_fetch(url, dest_dir, *, filename=None, force=False):
        calls.append((url, dest_dir, force))
        return path
    monkeypatch.setattr(download, "fetch", fake_fetch)
    return path, calls

def test_check_cli_matches_bea_requirements(tmp_path, toy_workbooks, fake_ixi, capsys):
    make_p, use_p = toy_workbooks
    bea_p, calls = fake_ixi
    L, labels = _toy_requirements(make_p, use_p)
    _write_bea_ixi(bea_p, L, labels)
    rc = cli.main(["check", "--make", str(make_p), "--use", str(use_p), "--year", "2017", "--out", str(tmp_path / "out")])
    out = capsys.readouterr().out
    assert rc == 0
    assert calls == [(sources.bea_detail_url("ixi_tr", "any"), sources.RAW_DIR / "bea", False)]
    assert float(_line_with(out, "max_abs_diff").split()[-1]) < 1e-12
    assert float(_line_with(out, "mean_abs_diff").split()[-1]) < 1e-12
    assert out.startswith("Comparing with BEA's published table convention: scrap S00401 kept as a commodity, "
                          "used goods S00402 removed; pass --scrap/--scrap-codes to compare another configuration\n")
    _line_with(out, "scrap mode bea (scrap codes S00402)")
    assert "row_minus_col" in out and (tmp_path / "out" / "us_io_2017_detail_after_bea_scrap-S00402.xlsx").exists()   # check builds first

def test_check_cli_compares_other_scrap_codes_when_asked(tmp_path, toy_workbooks, fake_ixi, capsys):
    make_p, use_p = toy_workbooks
    bea_p, _ = fake_ixi
    published, labels = _toy_requirements(make_p, use_p)
    handbook, _ = _toy_requirements(make_p, use_p, scrap_codes=("S00401", "S00402"))
    assert np.abs(published - handbook).to_numpy().max() > 1e-3          # the toy tells the two conventions apart
    _write_bea_ixi(bea_p, handbook, labels)
    args = ["check", "--make", str(make_p), "--use", str(use_p), "--out", str(tmp_path / "out")]
    assert cli.main(args) == 1                                           # default: published convention
    capsys.readouterr()
    assert cli.main(args + ["--scrap-codes", "S00401"]) == 0             # S00402 is not in the toy table
    out = capsys.readouterr().out
    assert "published table convention" not in out and "scrap mode bea (scrap codes S00401)" in out
    assert (tmp_path / "out" / "us_io_2017_detail_after_bea_scrap-S00401.xlsx").exists()

def test_scrap_codes_default_to_both_for_build_and_to_used_goods_for_check(tmp_path, toy_workbooks, fake_ixi, monkeypatch):
    make_p, use_p = toy_workbooks
    bea_p, _ = fake_ixi
    _write_bea_ixi(bea_p, *_toy_requirements(make_p, use_p))
    real_build, builds = square.build_square_table, []
    def recording_build(make, use, **options):
        builds.append(options)
        return real_build(make, use, **options)
    monkeypatch.setattr(square, "build_square_table", recording_build)
    toy = ["--make", str(make_p), "--use", str(use_p), "--out", str(tmp_path / "out")]
    assert cli.main(["build", *toy]) == 0 and cli.main(["check", *toy]) == 0
    assert cli.main(["build", *toy, "--scrap", "redistribute", "--scrap-codes", "S00401"]) == 0
    assert builds == [{"scrap": "bea", "scrap_codes": ("S00401", "S00402")}, {"scrap": "bea", "scrap_codes": ("S00402",)},
                      {"scrap": "redistribute", "scrap_codes": ("S00401",)}]
    assert (tmp_path / "out" / "us_io_2017_detail_after_redistribute_scrap-S00401.xlsx").exists()

def test_cli_rejects_scrap_codes_missing_from_the_use_table(tmp_path, toy_workbooks, capsys):
    make_p, use_p = toy_workbooks
    rc = cli.main(["build", "--make", str(make_p), "--use", str(use_p), "--scrap-codes", "S00401,S0042", "--out", str(tmp_path / "out")])
    err = capsys.readouterr().err
    assert rc == 2 and "--scrap-codes: not commodities in the use table: ['S0042']" in err
    assert not (tmp_path / "out").exists()

def test_check_cli_fails_beyond_tolerance_and_prints_worst_cells(tmp_path, toy_workbooks, fake_ixi, capsys):
    make_p, use_p = toy_workbooks
    bea_p, calls = fake_ixi
    L, labels = _toy_requirements(make_p, use_p)
    off = L.copy()
    off.loc["B", "C"] += 0.01                                    # BEA's cell 0.01 above ours
    _write_bea_ixi(bea_p, off, labels)
    args = ["check", "--make", str(make_p), "--use", str(use_p), "--out", str(tmp_path / "out")]
    assert cli.main(args) == 1                                   # default --tol 1e-3
    out = capsys.readouterr().out
    assert float(_line_with(out, "max_abs_diff").split()[-1]) == pytest.approx(0.01, rel=1e-3)     # printed to 4 digits
    assert float(_line_with(out, "mean_abs_diff").split()[-1]) == pytest.approx(0.01 / 9, rel=1e-3)
    worst = _line_with(out, "Industry B / Industry C")
    assert worst.split()[:2] == ["B", "C"] and "-1.00e-02" in worst
    assert f"{L.loc['B', 'C']:.7f}" in worst and f"{off.loc['B', 'C']:.7f}" in worst
    assert cli.main(args + ["--tol", "0.02", "--force"]) == 0
    assert calls[-1][2] is True

def test_check_cli_rejects_bea_table_with_other_industries(tmp_path, toy_workbooks, fake_ixi, capsys):
    make_p, use_p = toy_workbooks
    bea_p, _ = fake_ixi
    L, labels = _toy_requirements(make_p, use_p)
    _write_bea_ixi(bea_p, L.loc[["A", "B"], ["A", "B"]], labels)
    rc = cli.main(["check", "--make", str(make_p), "--use", str(use_p), "--out", str(tmp_path / "out")])
    err = capsys.readouterr().err
    assert rc == 2 and "only in ours ['C']" in err and "Traceback" not in err

def test_check_cli_rejects_missing_year_sheet(tmp_path, toy_workbooks, fake_ixi, capsys):
    make_p, use_p = toy_workbooks
    bea_p, _ = fake_ixi
    L, labels = _toy_requirements(make_p, use_p)
    _write_bea_ixi(bea_p, L, labels, sheet="2012")
    rc = cli.main(["check", "--make", str(make_p), "--use", str(use_p), "--out", str(tmp_path / "out")])
    err = capsys.readouterr().err
    assert rc == 2 and "2017" in err and "[2012]" in err


@pytest.mark.parametrize("argv, message", [
    ([], "required"),
    (["build", "--make", "m.xlsx"], "--make and --use must be given together"),
    (["check", "--use", "u.xlsx"], "--make and --use must be given together"),
    (["build", "--scrap", "legacy"], "invalid choice"),
    (["build", "--year", "1999"], "invalid choice"),
    (["build", "--level", "summary"], "invalid choice"),
    (["build", "--redefinitions", "none"], "invalid choice"),
    (["build", "--bogus"], "unrecognized arguments"),
    (["check", "--tol", "-1"], "--tol"),
    (["check", "--tol", "nan"], "--tol"),
    (["build", "--scrap-codes", "S00401,,S00402"], "empty code"),
    (["check", "--scrap", "keep", "--scrap-codes", "S00401"], "--scrap-codes has no effect with --scrap keep"),
])
def test_cli_rejects_bad_arguments(argv, message, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(argv)
    assert e.value.code == 2 and message in capsys.readouterr().err

def test_cli_rejects_missing_input_file(tmp_path, toy_workbooks, capsys):
    make_p, _ = toy_workbooks
    with pytest.raises(SystemExit) as e:
        cli.main(["build", "--make", str(make_p), "--use", str(tmp_path / "nope.xlsx"), "--out", str(tmp_path / "out")])
    assert e.value.code == 2 and "nope.xlsx" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()

def test_cli_reports_errors_without_traceback(tmp_path, toy_workbooks, capsys):
    make_p, use_p = toy_workbooks
    rc = cli.main(["build", "--make", str(make_p), "--use", str(use_p), "--year", "2012", "--out", str(tmp_path / "out")])
    err = capsys.readouterr().err
    assert rc == 2 and "no sheet for year 2012" in err and err.startswith("iotables: error:") and "Traceback" not in err
    assert not (tmp_path / "out").exists()

def test_build_cli_rejects_make_and_use_for_different_years(tmp_path, toy_workbooks, toy_use_grid, capsys):
    make_p, _ = toy_workbooks
    use_2012 = tmp_path / "use_2012.xlsx"
    write_grid_workbook(use_2012, toy_use_grid, sheet="2012", row_label="Commodity Description")
    rc = cli.main(["build", "--make", str(make_p), "--use", str(use_2012), "--out", str(tmp_path / "out")])
    err = capsys.readouterr().err
    assert rc == 2 and "2017" in err and "2012" in err
    assert not (tmp_path / "out").exists()
