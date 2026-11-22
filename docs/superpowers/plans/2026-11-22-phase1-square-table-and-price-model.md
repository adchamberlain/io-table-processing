# Phase 1: Square I-O Table Pipeline and Price Pass-Through Model — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A pip-installable package `iotables` that downloads BEA's 2017 benchmark make and use tables, builds a balanced square industry-by-industry table, and runs a general tax/cost pass-through price model down to PCE categories, validated against the 2002 tables, the WP6 price impacts, and BEA's own 2017 requirements table.

**Architecture:** Four pure stages with plain pandas/dataclass objects between them: `download` (cached fetch with provenance) → `parse` (BEA xlsx → code-indexed `MakeTable`/`UseTable`) → `square` (`SquareIOTable` via the fixed-product-sales-structure transformation, three scrap modes) → `leontief` (`PriceModel` consuming `shocks` and a `PCEBridge`). A thin argparse CLI wraps them. Tests are the spec's validation targets.

**Tech Stack:** Python ≥ 3.10, pandas, numpy, openpyxl, requests; pytest. Nothing else.

**Spec:** `docs/superpowers/specs/2026-11-22-io-pipeline-design.md` (read it first; section numbers below refer to it).

## Global Constraints

- Runtime dependencies are exactly pandas>=2.0, numpy>=1.24, openpyxl>=3.1, requests>=2.28 (spec §3). No xlrd, no pyarrow, no typer. CLI uses argparse.
- Alignment of industries and commodities is by BEA code string, never by position or name (§2 anti-goals). Codes are coerced to stripped `str`; integer-valued floats become their integer string (`1110.0` → `"1110"`).
- No silent fallbacks: a structural surprise raises `ValueError` naming the codes involved (§2).
- Units: millions of dollars everywhere. Rates are fractions (0.05 = 5%).
- Downloads are cached under `data/raw/<source>/` with a `<file>.provenance.json` sidecar `{url, sha256, bytes, downloaded_at}` (§5, §6). Nothing from a downloaded file is ever executed.
- Phase 1 scope is `--level detail` (2017 benchmark workbooks with sheets 2007/2012/2017). No BEA API code in this plan (§6.1 Phase 2).
- Every task ends with a passing `pytest` run and a local commit (no push).
- Tests needing the network are marked `@pytest.mark.network` and skip cleanly when offline; the default `pytest` run includes them.

## Review Focus

Failure modes the spec implies but no happy-path test exercises; each has a test pinned to its owning task:

1. BEA shifts the header row, ships codes as ints, or adds a trailing note row → parser must still find "Code"/descriptions by content (Task 2, `test_read_bea_grid_tolerates_layout_shifts`).
2. Make and use industry sets differ or arrive in different order → reorder by code; mismatch raises naming the codes (Task 4, `test_build_reorders_by_code`, `test_build_rejects_industry_mismatch`).
3. A commodity with zero output but nonzero use would divide by zero in market shares → zero column when use is zero, `ValueError` otherwise (Task 4, `test_zero_output_commodity`).
4. A shock names a code that is not in the table, or a rate on a zero-output industry → `KeyError`/`ValueError` with the code in the message (Task 10, `test_unknown_code_raises`).
5. PCE bridge rows whose commodity is not in the table (scrap, used goods) or whose purchasers' value is zero → price change 0, listed in `PriceResult.notes` (Task 12, `test_bridge_missing_commodity_noted`).

---

## Part A — Pipeline

### Task 1: Package install, URL manifest, cached download with provenance

**Files:**
- Modify: `pyproject.toml` (add `[tool.pytest.ini_options] markers = ["network: needs internet; downloads to data/raw"]`)
- Create: `src/iotables/sources.py`
- Rewrite: `src/iotables/download.py`
- Test: `tests/test_download.py`

**Interfaces:**
- Produces (`sources.py`):
  - `RAW_DIR = Path("data/raw")`, `OUTPUT_DIR = Path("data/output")`
  - `BEA_DETAIL_FILES: dict[tuple[str, str], str]` keyed by `(table, redefinitions)` with `table ∈ {"make","use"}` and `redefinitions ∈ {"after","before"}`, plus keys `("ixi_tr", "any")`, `("pce_bridge", "any")`, `("margins", "before")`, values = the exact URLs in spec §6.1 / §6.2.
  - `EIA_CO2_URL = "https://www.eia.gov/totalenergy/data/browser/csv.php?tbl=T11.01"`
  - `def bea_detail_url(table: str, redefinitions: str = "after") -> str` (KeyError with a helpful message for unknown keys).
- Produces (`download.py`):
  - `def fetch(url: str, dest_dir: Path, *, filename: str | None = None, force: bool = False, session: requests.Session | None = None) -> Path` — returns the cached file path; skips the request when the file and its sidecar exist and `force` is False; streams to `<dest>.part` then renames; writes `<filename>.provenance.json`.
  - `def sha256_of(path: Path) -> str`

- [ ] **Step 1: Install the package in editable mode and commit the scaffold**

Run: `pip install -e ".[dev]" && pytest -q` (from the repository root)
Expected: `1 passed`.

```bash
git add -A
git commit -m "chore: scaffold iotables package, add design doc and dev log"
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_download.py
import json, hashlib
from pathlib import Path
import pytest
from iotables import download, sources

class FakeResponse:
    def __init__(self, chunks, status=200):
        self.chunks, self.status_code = chunks, status
    def raise_for_status(self):
        if self.status_code != 200: raise download.requests.HTTPError(self.status_code)
    def iter_content(self, chunk_size=1 << 16):
        yield from self.chunks
    def __enter__(self): return self
    def __exit__(self, *a): return False

def test_fetch_writes_file_and_provenance(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(download.requests, "get", lambda url, **kw: calls.append(url) or FakeResponse([b"abc", b"def"]))
    p = download.fetch("https://example.test/x.xlsx", tmp_path)
    assert p == tmp_path / "x.xlsx" and p.read_bytes() == b"abcdef"
    prov = json.loads((tmp_path / "x.xlsx.provenance.json").read_text())
    assert prov["url"] == "https://example.test/x.xlsx"
    assert prov["sha256"] == hashlib.sha256(b"abcdef").hexdigest() and prov["bytes"] == 6
    assert "downloaded_at" in prov

def test_fetch_uses_cache_unless_forced(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(download.requests, "get", lambda url, **kw: calls.append(url) or FakeResponse([b"x"]))
    download.fetch("https://example.test/x.xlsx", tmp_path)
    download.fetch("https://example.test/x.xlsx", tmp_path)
    assert len(calls) == 1
    download.fetch("https://example.test/x.xlsx", tmp_path, force=True)
    assert len(calls) == 2

def test_fetch_leaves_no_partial_file_on_error(tmp_path, monkeypatch):
    def boom(url, **kw):
        class R(FakeResponse):
            def iter_content(self, chunk_size=1 << 16):
                yield b"abc"; raise IOError("connection dropped")
        return R([])
    monkeypatch.setattr(download.requests, "get", boom)
    with pytest.raises(IOError):
        download.fetch("https://example.test/x.xlsx", tmp_path)
    assert not (tmp_path / "x.xlsx").exists() and not list(tmp_path.glob("*.part"))

def test_manifest_has_all_phase1_files():
    assert sources.bea_detail_url("make", "after").endswith("IOMake_After_Redefinitions_2017_Detail.xlsx")
    assert sources.bea_detail_url("use", "before").endswith("IOUse_Before_Redefinitions_PRO_2017_Detail.xlsx")
    assert sources.bea_detail_url("pce_bridge", "any").endswith("PCEBridge_2017_DET.xlsx")
    assert sources.bea_detail_url("ixi_tr", "any").endswith("IxI_TR_2017_PRO_DET.xlsx")
    with pytest.raises(KeyError):
        sources.bea_detail_url("make", "sideways")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_download.py -v`
Expected: FAIL with `ImportError`/`AttributeError` (no `sources`, no `fetch`).

- [ ] **Step 4: Implement `sources.py` and `download.fetch`**

`fetch`: `filename` defaults to the URL's last path segment; use `requests.get(url, stream=True, timeout=120)` (or `session.get`); write chunks to `dest / (filename + ".part")`, `os.replace` to the final name only after the stream completes; on any exception delete the `.part`; sidecar written last with `datetime.now(timezone.utc).isoformat()`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_download.py -v` → all PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/iotables/sources.py src/iotables/download.py tests/test_download.py
git commit -m "feat: URL manifest and cached download with provenance sidecar"
```

### Task 2: Generic BEA worksheet reader

**Files:**
- Rewrite: `src/iotables/parse.py` (grid reader only in this task)
- Test: `tests/test_parse.py`, `tests/conftest.py` (workbook builder helper)

**Interfaces:**
- Produces:
  - `def normalize_code(x) -> str | None` — `None`/blank → `None`; `111200` → `"111200"`; `1110.0` → `"1110"`; `" TRADE "` → `"TRADE"`.
  - `@dataclass class BeaGrid: values: pd.DataFrame; row_labels: pd.Series; col_labels: pd.Series; title: str` — `values` index = row codes, columns = col codes, dtype float, NaN→0.0; labels indexed by code.
  - `def read_bea_grid(path: Path, sheet: str) -> BeaGrid`
  - `def list_year_sheets(path: Path) -> list[int]` — sheet names that parse as 4-digit years, ascending.
  - `UNCODED_TOTALS = {"Total Final Uses (GDP)": "T004", "Total Commodity Output": "T007", "Total Industry Output": "T008"}` — codes synthesized for header cells whose code cell is empty but whose description matches.
- Header rule: the "Code" row is the first row whose column-A value, stripped and lower-cased, equals `"code"`; descriptions are the row immediately above it; column codes come from the "Code" row from column C onward (apply `UNCODED_TOTALS` when the code is empty; stop at the first column where both code and description are empty). Data rows start below the "Code" row and stop at the first row where both column A and column B are empty. `title` = cell A1.

- [ ] **Step 1: Add a synthetic-workbook helper to `tests/conftest.py`**

```python
# tests/conftest.py
import openpyxl, pytest
from pathlib import Path

def write_bea_workbook(path: Path, *, sheet="2017", title="Make Table, After Redefinitions, 2017",
                       row_label="Industry Description", col_codes=None, col_descs=None, rows=None,
                       header_row=5, int_codes=False, trailing_note=True):
    """rows: list of (code, desc, [values...]). Writes BEA's layout: title rows, blank, desc row, 'Code' row, data."""
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = sheet
    ws.cell(1, 1, title); ws.cell(2, 1, "[Millions of Dollars]"); ws.cell(3, 1, "Bureau of Economic Analysis")
    ws.cell(header_row, 1, "Industry / Commodity")
    for j, d in enumerate(col_descs): ws.cell(header_row, 3 + j, d)
    ws.cell(header_row + 1, 1, "Code"); ws.cell(header_row + 1, 2, row_label)
    for j, c in enumerate(col_codes):
        if c is not None: ws.cell(header_row + 1, 3 + j, int(c) if int_codes and str(c).isdigit() else c)
    r = header_row + 2
    for code, desc, vals in rows:
        ws.cell(r, 1, int(code) if int_codes and str(code).isdigit() else code); ws.cell(r, 2, desc)
        for j, v in enumerate(vals):
            if v is not None: ws.cell(r, 3 + j, v)
        r += 1
    if trailing_note: ws.cell(r + 1, 1, "Note. Detail may not add to total due to rounding.")
    wb.save(path)
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_parse.py
import pytest
from iotables import parse
from conftest import write_bea_workbook

def test_normalize_code():
    assert parse.normalize_code(111200) == "111200"
    assert parse.normalize_code(1110.0) == "1110"
    assert parse.normalize_code(" TRADE ") == "TRADE"
    assert parse.normalize_code(None) is None and parse.normalize_code("  ") is None

def test_read_bea_grid_basic(tmp_path):
    p = tmp_path / "make.xlsx"
    write_bea_workbook(p, col_codes=["A", "B", "T008"], col_descs=["Alpha", "Beta", "Total Industry Output"],
                       rows=[("A", "Alpha ind", [300, 25, 325]), ("B", "Beta ind", [None, 360, 360]), ("T007", "Total Commodity Output", [300, 385, None])])
    g = parse.read_bea_grid(p, "2017")
    assert list(g.values.index) == ["A", "B", "T007"] and list(g.values.columns) == ["A", "B", "T008"]
    assert g.values.loc["B", "A"] == 0.0 and g.values.loc["A", "T008"] == 325.0
    assert g.row_labels["A"] == "Alpha ind" and g.col_labels["T008"] == "Total Industry Output"
    assert g.title.startswith("Make Table")

@pytest.mark.parametrize("header_row,int_codes", [(5, False), (7, True), (4, True)])
def test_read_bea_grid_tolerates_layout_shifts(tmp_path, header_row, int_codes):
    p = tmp_path / "use.xlsx"
    write_bea_workbook(p, header_row=header_row, int_codes=int_codes, row_label="Commodity Description",
                       col_codes=["111200", "T001", "F01000", None, None], 
                       col_descs=["Veg", "Total Intermediate", "PCE", "Total Final Uses (GDP)", "Total Commodity Output"],
                       rows=[("111200", "Veg", [1, 1, 5, 5, 6]), ("V00100", "Compensation", [2, 2, None, None, None])])
    g = parse.read_bea_grid(p, "2017")
    assert list(g.values.columns) == ["111200", "T001", "F01000", "T004", "T007"]
    assert list(g.values.index) == ["111200", "V00100"]
    assert g.values.loc["111200", "T007"] == 6.0

def test_list_year_sheets(tmp_path):
    p = tmp_path / "x.xlsx"
    write_bea_workbook(p, sheet="2012", col_codes=["A"], col_descs=["a"], rows=[("A", "a", [1])])
    import openpyxl; wb = openpyxl.load_workbook(p); wb.create_sheet("NAICS Codes"); wb.create_sheet("2017"); wb.save(p)
    assert parse.list_year_sheets(p) == [2012, 2017]
```

- [ ] **Step 3: Run tests to verify they fail** — `pytest tests/test_parse.py -v` → FAIL (missing names).

- [ ] **Step 4: Implement `normalize_code`, `BeaGrid`, `read_bea_grid`, `list_year_sheets` in `src/iotables/parse.py`**

Use `openpyxl.load_workbook(path, read_only=True, data_only=True)` and iterate rows once into a list; apply the header rule from the Interfaces block; `pd.to_numeric(errors="coerce").fillna(0.0)` for values.

- [ ] **Step 5: Run tests to verify they pass** — `pytest tests/test_parse.py -v` → PASS.

- [ ] **Step 6: Commit** — `git add tests/conftest.py tests/test_parse.py src/iotables/parse.py && git commit -m "feat: content-driven BEA worksheet reader"`

### Task 3: MakeTable, UseTable, and `load_bea_tables`

**Files:**
- Modify: `src/iotables/parse.py`
- Test: `tests/test_parse.py` (append), `tests/conftest.py` (toy fixtures)

**Interfaces:**
- Produces:
  - `@dataclass class MakeTable: values: pd.DataFrame  # industries x commodities; industry_labels: pd.Series; commodity_labels: pd.Series; industry_output: pd.Series | None  # T008 column; commodity_output: pd.Series | None  # T007 row; meta: dict`
    - `@classmethod def from_grid(cls, grid: BeaGrid, meta: dict | None = None) -> "MakeTable"` — drops rows/cols whose code starts with `"T0"` into the output series; everything else is data.
    - properties `industries: list[str]`, `commodities: list[str]`.
  - `@dataclass class UseTable: intermediate: pd.DataFrame  # commodities x industries; final_demand: pd.DataFrame  # commodities x F-codes; value_added: pd.DataFrame  # index ["V00100","V00200","V00300"] x industries; commodity_labels; industry_labels; final_demand_labels; industry_output: pd.Series | None  # T008 row over industries; commodity_output: pd.Series | None  # T007 column over commodities; meta: dict`
    - `from_grid` rule: value-added rows = index codes in `{"V00100","V00200","V00300"}` (all three required, else `ValueError`); rows with codes starting `"T0"` → totals; remaining rows = commodities. Columns: codes starting `"F"` → final demand; starting `"T0"` → totals; the rest = industries.
    - properties `industries`, `commodities`.
  - `def parse_make(path: Path, year: int | str = "latest") -> MakeTable`, `def parse_use(path: Path, year: int | str = "latest") -> UseTable` — `"latest"` = `max(list_year_sheets(path))`; `meta` gets `{"path", "sheet", "year", "title"}`.
  - `def load_bea_tables(level: str = "detail", year: int | str = "latest", redefinitions: str = "after", data_dir: Path = RAW_DIR, force: bool = False) -> tuple[MakeTable, UseTable]` — `level != "detail"` raises `NotImplementedError("summary level arrives in Phase 2")`; downloads into `data_dir / "bea"`; adds `redefinitions` and the provenance dict to `meta`.
- Toy fixtures in `tests/conftest.py` (BEA manual tables 12.5 and 12.7, spec §9), as pytest fixtures `toy_make() -> MakeTable` and `toy_use() -> UseTable` built from `BeaGrid` objects:
  - make values: index `["A","B","C"]`, columns `["A","B","C","S00401","T008"]`, rows A `[300,25,0,3,328]`, B `[30,360,20,2,412]`, C `[0,15,250,0,265]`, plus row `T007` `[330,400,270,5,None→0]`.
  - use values: index `["A","B","C","S00401","V00100","V00200","V00300","T008"]`, columns `["A","B","C","F01000","T007"]`: A `[50,120,120,40,330]`, B `[180,30,60,130,400]`, C `[50,150,50,20,270]`, S00401 `[1,3,1,0,5]`, V00100 `[0,0,0,0,0]`, V00200 `[0,0,0,0,0]`, V00300 `[47,109,34,0,0]`, T008 `[328,412,265,0,0]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_make_from_grid(toy_make):
    assert toy_make.industries == ["A", "B", "C"] and toy_make.commodities == ["A", "B", "C", "S00401"]
    assert list(toy_make.industry_output) == [328, 412, 265]
    assert list(toy_make.commodity_output) == [330, 400, 270, 5]

def test_use_from_grid(toy_use):
    assert toy_use.industries == ["A", "B", "C"] and toy_use.commodities == ["A", "B", "C", "S00401"]
    assert list(toy_use.final_demand.columns) == ["F01000"]
    assert list(toy_use.value_added.index) == ["V00100", "V00200", "V00300"]
    assert toy_use.value_added.loc["V00300", "B"] == 109 and list(toy_use.industry_output) == [328, 412, 265]
    assert toy_use.commodity_output["S00401"] == 5

def test_use_requires_all_value_added_rows(toy_use_grid):
    g = parse.BeaGrid(values=toy_use_grid.values.drop(index="V00200"), row_labels=toy_use_grid.row_labels.drop("V00200"),
                      col_labels=toy_use_grid.col_labels, title=toy_use_grid.title)
    with pytest.raises(ValueError, match="V00200"):
        parse.UseTable.from_grid(g)

def test_parse_make_latest_sheet(tmp_path):
    p = tmp_path / "make.xlsx"
    write_bea_workbook(p, sheet="2012", col_codes=["A", "T008"], col_descs=["a", "Total Industry Output"], rows=[("A", "a", [1, 1])])
    import openpyxl; wb = openpyxl.load_workbook(p); ws = wb.copy_worksheet(wb["2012"]); ws.title = "2017"; ws["C7"] = 2; wb.save(p)
    m = parse.parse_make(p)                       # year="latest"
    assert m.meta["year"] == 2017 and m.values.loc["A", "A"] == 2.0
    assert parse.parse_make(p, 2012).values.loc["A", "A"] == 1.0

@pytest.mark.network
def test_load_bea_tables_detail_2017_shapes():
    make, use = parse.load_bea_tables("detail", 2017, "after")
    assert make.values.shape == (402, 405) and use.intermediate.shape == (405, 402)
    assert use.final_demand.shape[1] == 20 and list(use.final_demand.columns)[:2] == ["F01000", "F02E00"]
    assert make.industries == use.industries
    assert (use.industry_output - make.industry_output).abs().max() <= 1.0
    assert use.meta["redefinitions"] == "after" and "sha256" in use.meta["provenance"]
```

- [ ] **Step 2: Run to verify failure** — `pytest tests/test_parse.py -v -k "grid or latest"` → FAIL.
- [ ] **Step 3: Implement `MakeTable`, `UseTable`, `parse_make`, `parse_use`, `load_bea_tables`** per the Interfaces block. `load_bea_tables` calls `download.fetch(bea_detail_url("make", redefinitions), data_dir / "bea")` etc.
- [ ] **Step 4: Run all parse tests including the network one** — `pytest tests/test_parse.py -v` → PASS (network test downloads ~15 MB into `data/raw/bea/` once).
- [ ] **Step 5: Commit** — `git commit -am "feat: MakeTable/UseTable parsing and load_bea_tables"` (add new files explicitly).

### Task 4: `SquareIOTable`, market shares, build in `keep` mode, identities

**Files:**
- Rewrite: `src/iotables/square.py`
- Create: `src/iotables/validate.py`
- Test: `tests/test_square.py`, `tests/test_validate.py`

**Interfaces:**
- Produces (`square.py`):
  - `SCRAP_CODES = ("S00401", "S00402")`, `DROP_CODES = ("S00300", "S00900")`
  - `@dataclass class SquareIOTable: Z: pd.DataFrame; F: pd.DataFrame; V: pd.DataFrame; y: pd.Series; N: pd.DataFrame; market_shares: pd.DataFrame; industry_labels: pd.Series; final_demand_labels: pd.Series; commodity_labels: pd.Series; meta: dict`
    - properties `industries: list[str]`, `n: int`; method `check_identities(self, tol: float = 1e-6) -> dict[str, float]` (delegates to `validate`).
  - `def market_shares(make_values: pd.DataFrame) -> pd.DataFrame` — `M / M.sum(axis=0)`, columns with zero total become all-zero (no NaN).
  - `def build_square_table(make: MakeTable, use: UseTable, *, scrap: str = "bea", drop: Sequence[str] = DROP_CODES, scrap_codes: Sequence[str] = SCRAP_CODES) -> SquareIOTable` — this task implements `scrap="keep"` only; other modes raise `NotImplementedError` until Tasks 5–6. Algorithm (spec §7): validate industry sets (reorder use to make's order; mismatch → `ValueError` listing the symmetric difference); use commodities missing from make get a zero make column if their use row is all zero, else `ValueError` naming them; `g = use.industry_output if not None else make.values.sum(axis=1)`; drop `drop` rows/columns present; `q = M.sum(0)`; `market_shares`; `N = market_shares` (keep mode); `Z = N @ U`, `F = N @ D`, `y = Z.sum(1) + F.sum(1)`; `V` = V00100/V00200 from use, `V00300 = y − Z.sum(0) − V00100 − V00200`; `meta["diagnostics"] = {"y_minus_g": Series, "gos_minus_bea": Series, "dropped": {code: {"intermediate": $, "final_demand": $}}, "scrap_mode": str}`; carries `meta["source"] = {"make": make.meta, "use": use.meta}`.
- Produces (`validate.py`):
  - `def check_identities(sq: SquareIOTable, tol: float = 1e-6) -> dict[str, float]` — returns `{"row_minus_col": max|rowtot − coltot|, "shares_minus_one": max|colsum(market_shares) − 1| over q>0 columns, "y_minus_rowsum": ...}`; raises `ValueError` if any exceeds `tol`.
  - `def compare_tables(a: pd.DataFrame, b: pd.DataFrame, rtol: float = 1e-6, atol: float = 1e-6) -> pd.DataFrame` — aligns on the intersection of index/columns, raises `ValueError` if either side has labels the other lacks, returns a long DataFrame `[row, col, a, b, diff]` of violations (empty when equal).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_square.py
import numpy as np, pandas as pd, pytest
from iotables import square, parse

def test_market_shares_columns_sum_to_one(toy_make):
    ms = square.market_shares(toy_make.values)
    assert np.allclose(ms.sum(axis=0), 1.0)
    assert ms.loc["A", "A"] == pytest.approx(300 / 330)

def test_market_shares_zero_output_column_is_zero():
    m = pd.DataFrame([[1.0, 0.0], [1.0, 0.0]], index=["i", "j"], columns=["a", "b"])
    ms = square.market_shares(m)
    assert (ms["b"] == 0).all() and not ms.isna().any().any()

def test_build_keep_mode_identities(toy_make, toy_use):
    sq = square.build_square_table(toy_make, toy_use, scrap="keep")
    assert sq.Z.shape == (3, 3) and list(sq.F.columns) == ["F01000"] and list(sq.V.index) == ["V00100", "V00200", "V00300"]
    res = sq.check_identities()
    assert res["row_minus_col"] < 1e-9
    assert sq.y.sum() == pytest.approx(328 + 412 + 265)       # scrap kept as a commodity: totals preserved
    assert sq.meta["diagnostics"]["scrap_mode"] == "keep"

def test_build_reorders_by_code(toy_make, toy_use):
    use2 = parse.UseTable(**{**toy_use.__dict__, "intermediate": toy_use.intermediate[["C", "A", "B"]],
                             "value_added": toy_use.value_added[["C", "A", "B"]]})
    a = square.build_square_table(toy_make, toy_use, scrap="keep"); b = square.build_square_table(toy_make, use2, scrap="keep")
    pd.testing.assert_frame_equal(a.Z, b.Z)

def test_build_rejects_industry_mismatch(toy_make, toy_use):
    bad = parse.UseTable(**{**toy_use.__dict__, "intermediate": toy_use.intermediate.rename(columns={"C": "Q"}),
                            "value_added": toy_use.value_added.rename(columns={"C": "Q"})})
    with pytest.raises(ValueError, match="Q"):
        square.build_square_table(toy_make, bad, scrap="keep")

def test_zero_output_commodity(toy_make, toy_use):
    # commodity "Z" used by nobody and made by nobody -> fine; used by somebody -> error
    use_zero = add_use_row(toy_use, "Z", [0, 0, 0], fd=[0]); use_pos = add_use_row(toy_use, "Z", [1, 0, 0], fd=[0])
    square.build_square_table(toy_make, use_zero, scrap="keep")
    with pytest.raises(ValueError, match="Z"):
        square.build_square_table(toy_make, use_pos, scrap="keep")
```
(`add_use_row` is a small helper in `conftest.py` returning a new `UseTable` with one extra commodity row.)

```python
# tests/test_validate.py
def test_compare_tables_reports_violations():
    a = pd.DataFrame([[1.0, 2.0]], index=["r"], columns=["x", "y"]); b = a.copy(); b.loc["r", "y"] = 2.5
    out = validate.compare_tables(a, b)
    assert len(out) == 1 and out.iloc[0]["col"] == "y"
    with pytest.raises(ValueError):
        validate.compare_tables(a, b.rename(columns={"y": "z"}))
```

- [ ] **Step 2: Run to verify failure** — `pytest tests/test_square.py tests/test_validate.py -v` → FAIL.
- [ ] **Step 3: Implement `square.py` (keep mode) and `validate.py`** per Interfaces.
- [ ] **Step 4: Run to verify pass** — same command → PASS.
- [ ] **Step 5: Commit** — `git add ... && git commit -m "feat: SquareIOTable, market shares, keep-mode build, identity checks"`

### Task 5: `bea` scrap mode (nonscrap ratio) — must reproduce the BEA manual example

**Files:**
- Modify: `src/iotables/square.py`
- Test: `tests/test_square.py` (append)

**Interfaces:**
- `build_square_table(..., scrap="bea")`: scrap production `s_i = M[scrap_codes ∩ columns].sum(axis=1)`; `r_i = (g_i − s_i) / g_i`; drop scrap rows from U and D and scrap columns from M; `market_shares` from the reduced M; `N = market_shares.div(r, axis=0)`; `meta["diagnostics"]["nonscrap_ratio"] = r`, `["scrap_purchases_dropped"] = {code: {"intermediate": $, "final_demand": $}}`. Default mode becomes `"bea"` (already the signature default).

- [ ] **Step 1: Write the failing tests (numbers from BEA manual tables 12.9, 12.10, 12.14, 12.15; spec §9)**

```python
def test_bea_mode_matches_manual_example(toy_make, toy_use):
    sq = square.build_square_table(toy_make, toy_use, scrap="bea")
    r = sq.meta["diagnostics"]["nonscrap_ratio"]
    assert list(r.round(3)) == [0.991, 0.995, 1.000]
    W = sq.N
    expected_W = pd.DataFrame([[.917, .063, .000], [.091, .904, .074], [.000, .038, .926]], index=list("ABC"), columns=list("ABC"))
    assert np.allclose(W.values, expected_W.values, atol=5e-4)
    assert np.allclose(sq.y.values, [328, 412, 265])                      # industry output preserved exactly
    assert "S00401" not in sq.market_shares.columns and sq.check_identities()["row_minus_col"] < 1e-9
    # total requirements: commodity-by-commodity (I - BW)^-1 and industry-by-commodity W(I - BW)^-1
    B = toy_use.intermediate.drop(index="S00401").div(toy_use.industry_output, axis=1)
    cxc = np.linalg.inv(np.eye(3) - B.values @ W.values)
    assert np.allclose(cxc, [[2.487, 1.500, 1.778], [1.736, 2.300, 1.579], [1.292, 1.322, 2.323]], atol=2e-3)
    ixc = W.values @ cxc
    assert np.allclose(ixc, [[2.391, 1.521, 1.731], [1.893, 2.316, 1.763], [1.261, 1.310, 2.210]], atol=2e-3)
    # our square table's own coefficients equal W B, so (I - A)^-1 W reproduces the same industry-by-commodity table
    A = sq.Z.div(sq.y, axis=1)
    assert np.allclose(np.linalg.inv(np.eye(3) - A.values) @ W.values, ixc, atol=1e-9)

def test_bea_mode_records_dropped_scrap(toy_make, toy_use):
    sq = square.build_square_table(toy_make, toy_use, scrap="bea")
    assert sq.meta["diagnostics"]["scrap_purchases_dropped"]["S00401"]["intermediate"] == 5
```

- [ ] **Step 2: Run to verify failure** → `NotImplementedError`.
- [ ] **Step 3: Implement bea mode.**
- [ ] **Step 4: Run `pytest tests/test_square.py -v`** → PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat: BEA nonscrap-ratio scrap treatment (default), verified against BEA manual example"`

### Task 6: `redistribute` scrap mode and the drop of S00300/S00900

**Files:**
- Modify: `src/iotables/square.py`
- Test: `tests/test_square.py` (append)

**Interfaces:**
- `def redistribute_rows(block: pd.DataFrame, rows: Sequence[str]) -> tuple[pd.DataFrame, dict[str, float]]` — for each column: `s = block.loc[rows, col].sum()`; `others = block.drop(index=rows)[col]`; if `others.sum() != 0`: `others += s * others / others.sum()`; else record `unallocated[col] = s`; returns the block without `rows` and the unallocated dict.
- `build_square_table(..., scrap="redistribute")`: apply `redistribute_rows` to U and to D separately with the scrap codes present (after the `drop` rows are removed); drop scrap columns from M; `N = market_shares`; `meta["diagnostics"]["redistributed"] = {"intermediate": $total, "final_demand": $total, "unallocated": {...}}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_redistribute_rows_preserves_column_totals(toy_use):
    U2, un = square.redistribute_rows(toy_use.intermediate, ["S00401"])
    assert "S00401" not in U2.index and un == {}
    assert np.allclose(U2.sum(axis=0).values, toy_use.intermediate.sum(axis=0).values)   # 281, 303, 231
    assert U2.loc["A", "A"] == pytest.approx(50 + 1 * 50 / 280)

def test_redistribute_rows_reports_unallocated():
    blk = pd.DataFrame({"j": [0.0, 0.0, 4.0]}, index=["a", "b", "S00401"])
    out, un = square.redistribute_rows(blk, ["S00401"])
    assert un == {"j": 4.0} and (out["j"] == 0).all()

def test_redistribute_mode(toy_make, toy_use):
    sq = square.build_square_table(toy_make, toy_use, scrap="redistribute")
    assert sq.check_identities()["row_minus_col"] < 1e-9 and (sq.Z.values >= 0).all()
    assert not np.allclose(sq.y.values, [328, 412, 265])          # y is the row total, not BEA's g
    d = sq.meta["diagnostics"]
    assert d["redistributed"]["intermediate"] == pytest.approx(5.0) and d["y_minus_g"].abs().max() > 0

def test_drop_codes_removed_and_recorded(toy_make, toy_use):
    use3 = add_use_row(toy_use, "S00300", [2, 0, 0], fd=[-2]); make3 = add_make_column(toy_make, "S00300", [0, 0, 0])
    sq = square.build_square_table(make3, use3, scrap="bea")
    assert sq.meta["diagnostics"]["dropped"]["S00300"] == {"intermediate": 2.0, "final_demand": -2.0}
    assert "S00300" not in sq.market_shares.columns
```

- [ ] **Step 2: Run to verify failure.** - [ ] **Step 3: Implement.** - [ ] **Step 4: `pytest tests/test_square.py -v` → PASS.**
- [ ] **Step 5: Commit** — `git commit -am "feat: legacy proportional redistribution of scrap/used goods; drop noncomparable imports and ROW adjustment"`

### Task 7: Output layout and writers

**Files:**
- Modify: `src/iotables/square.py`
- Test: `tests/test_square.py` (append)

**Interfaces:**
- `SquareIOTable.to_frame(self) -> pd.DataFrame` — index: industry codes + `["V00100","V00200","V00300","T008"]`; columns: `["Description"] + industry codes + final-demand codes + ["T008"]`; industry rows carry `Z | F | y`; V rows carry V under industry columns, `0.0` under final-demand columns, row sum under `T008`; the `T008` row carries column totals (`y` under industries, column sums under final demand, grand total under `T008`). Descriptions from the label series; `"Total industry output"` for `T008`.
- `SquareIOTable.to_excel(self, path: Path, title: str | None = None) -> Path` — one sheet `"square"`: A1 title (default `f"{year} {level}-level U.S. Input-Output Table"` from meta, falling back to `"U.S. Input-Output Table"`), A2 `f"{n} industries"`, A3 `"($ Millions)"`, row 5 = codes (A5 `"Code"`), row 6 = descriptions (A6 `"Industry"`, B6 `"Description"`), data from row 7, then a blank row and `"Source: Bureau of Economic Analysis; built with iotables <version> on <date>"`.
- `SquareIOTable.to_csv(self, directory: Path) -> dict[str, Path]` — writes `square.csv` (`to_frame()`), `Z.csv`, `F.csv`, `V.csv`, `y.csv`, `market_shares.csv`, `labels.csv`, `meta.json` (diagnostics Series serialized as dicts); returns the paths.
- `def read_square_frame(path: Path) -> pd.DataFrame` — reads back a `to_excel` file into the `to_frame()` layout (used by the CLI `run` command in Task 14).

- [ ] **Step 1: Write the failing tests**

```python
def test_to_frame_layout(toy_make, toy_use):
    sq = square.build_square_table(toy_make, toy_use, scrap="bea"); f = sq.to_frame()
    assert list(f.index) == ["A", "B", "C", "V00100", "V00200", "V00300", "T008"]
    assert list(f.columns) == ["Description", "A", "B", "C", "F01000", "T008"]
    assert f.loc["A", "T008"] == pytest.approx(sq.y["A"]) and f.loc["T008", "A"] == pytest.approx(sq.y["A"])
    assert f.loc["T008", "T008"] == pytest.approx(sq.y.sum() + sq.F.values.sum())
    assert f.loc["V00300", "F01000"] == 0.0

def test_excel_roundtrip(tmp_path, toy_make, toy_use):
    sq = square.build_square_table(toy_make, toy_use, scrap="bea"); p = sq.to_excel(tmp_path / "t.xlsx")
    back = square.read_square_frame(p)
    pd.testing.assert_frame_equal(back.drop(columns="Description").astype(float), sq.to_frame().drop(columns="Description").astype(float), atol=1e-9)

def test_to_csv_writes_all_parts(tmp_path, toy_make, toy_use):
    paths = square.build_square_table(toy_make, toy_use).to_csv(tmp_path)
    assert set(paths) == {"square", "Z", "F", "V", "y", "market_shares", "labels", "meta"} and all(p.exists() for p in paths.values())
```

- [ ] **Step 2–4: fail → implement → pass.**
- [ ] **Step 5: Commit** — `git commit -am "feat: legacy-layout frame, Excel and CSV writers"`

### Task 8: 2002 regression fixtures and tests (the 2002 summary and detailed tables)

**Files:**
- Create: `scripts/extract_2002_fixtures.py` (one-time; documented at top; run with a scratch venv that has `xlrd`, never from the package)
- Create: `tests/fixtures/2002/summary_make.csv`, `summary_make_labels.csv`, `summary_use.csv`, `summary_use_labels.csv`, `summary_target.csv`, `detail_make.csv.gz`, `detail_use.csv.gz`, `detail_target.csv.gz`, `README.md`
- Test: `tests/test_regression_2002.py`
- Modify: `tests/conftest.py` (`grid_from_csv(values_path, labels_path) -> BeaGrid`)

**Interfaces:**
- Fixture CSV format: a `BeaGrid.values` frame with codes as index and column headers (first column header `code`), optional labels CSV with columns `code,description`. Gzipped CSVs read with `pd.read_csv(path, compression="gzip", index_col=0, dtype={"code": str})`.
- Extraction rules (spec §7.3, §9, verified 2026-11-22):
  - Summary inputs: `.../Carbon Tax Model/Data FIles/2002summary_makeuse.xls`. MAKE sheet: industry rows are the 133 rows with codes in column B (`1110` … `S007`); the `N/A`/"ROW of World" row is all zeros → dropped (assert); keep the `T007` row and the `T008` column. USE sheet: 134 commodity rows (`1110` … `S007`, `S004`) + `V001,V002,V003,T008` rows; columns 133 industries + `T001` + `F010…F09I` + `T004,T007`. Normalize `S004 → S00400`, `V001/V002/V003 → V00100/V00200/V00300`; floats `1110.0 → "1110"`.
  - Summary target: `.../U.S. Input-Output Tables/2002 Summary Input-Output Table.xlsx`, sheet `2002 Summary-Level`, codes in row 4 / column A, data rows 6–141, total row 142; emit a frame in `to_frame()` layout with codes `V001→V00100` etc. and the last column `T008`.
  - Detailed inputs: the `Data` sheets of `.../Supporting Files/2002 Detailed Make.xlsx` (Industry, IndustryDescription, Commodity, Commodity Description, Value) and `2002 Detailed Use.xlsx` (Commodity, Commodity Description, Industry, Industry Description, Value); pivot to wide; make: add zero columns for use commodities absent from make (expect exactly `S00101`); use: `V00100…V00300` already coded; no T-rows (industry output comes from make row sums in the build).
  - Detailed target: `2002 Detailed Input-Output Table.xlsx`, sheet `2002 Detailed Level`, same layout rule as the summary target; its last column (`Total`) becomes `T008`.
  - `README.md` in the fixture folder records the source paths, the script, and the date.

- [ ] **Step 1: Write the failing regression tests**

```python
# tests/test_regression_2002.py
import gzip, pytest, pandas as pd
from pathlib import Path
from iotables import parse, square, validate
FIX = Path(__file__).parent / "fixtures" / "2002"

def _target(name):
    p = FIX / name
    if not p.exists(): pytest.skip(f"fixture {name} missing")
    return pd.read_csv(p, index_col=0, dtype={"code": str}, compression="gzip" if name.endswith(".gz") else None)

def test_rebuild_2002_summary_table_matches_legacy():
    make = parse.MakeTable.from_grid(grid_from_csv(FIX / "summary_make.csv", FIX / "summary_make_labels.csv"))
    use = parse.UseTable.from_grid(grid_from_csv(FIX / "summary_use.csv", FIX / "summary_use_labels.csv"))
    sq = square.build_square_table(make, use, scrap="keep", drop=())
    ours = sq.to_frame().drop(columns="Description"); theirs = _target("summary_target.csv")
    bad = validate.compare_tables(ours, theirs, rtol=1e-6, atol=1e-3)
    assert bad.empty, bad.head(20)
    assert sq.n == 133

def test_rebuild_2002_detailed_table_matches_legacy():
    make = parse.MakeTable.from_grid(grid_from_csv(FIX / "detail_make.csv.gz", None))
    use = parse.UseTable.from_grid(grid_from_csv(FIX / "detail_use.csv.gz", None))
    sq = square.build_square_table(make, use, scrap="redistribute")
    ours = sq.to_frame().drop(columns="Description"); theirs = _target("detail_target.csv.gz")
    bad = validate.compare_tables(ours, theirs, rtol=1e-6, atol=1e-3)
    assert bad.empty, bad.head(20)
    assert sq.n == 426 and sq.meta["diagnostics"]["redistributed"]["final_demand"] != 0
```

- [ ] **Step 2: Run to verify they skip/fail** — `pytest tests/test_regression_2002.py -v` → SKIP (no fixtures).
- [ ] **Step 3: Write and run `scripts/extract_2002_fixtures.py`** with a scratch virtual environment that has xlrd — it reads the original 2002 workbooks (held privately) and writes the fixtures. Verify: `summary_make.csv` has 133 rows × 135 columns (134 commodities + T008) plus the `T007` row; `detail_use.csv.gz` has 431 rows × 439 columns.
- [ ] **Step 4: Run the regression tests** — `pytest tests/test_regression_2002.py -v` → PASS. If the summary test fails only in `V00300`/`T008`, check that `g` came from the use `T008` row; if the detailed test fails in a handful of cells, print `bad` and inspect whether the legacy sheet had a manual override before changing anything (do not loosen tolerances).
- [ ] **Step 5: Commit** — `git add scripts tests/fixtures/2002 tests/test_regression_2002.py tests/conftest.py && git commit -m "test: rebuild the 2002 summary and detailed tables cell for cell"`

### Task 9: CLI `build` and `check`, BEA industry-by-industry requirements comparison

**Files:**
- Rewrite: `src/iotables/cli.py`
- Modify: `src/iotables/__init__.py` (export `load_bea_tables, build_square_table, SquareIOTable`)
- Test: `tests/test_cli.py`, `tests/test_bea_ixi.py`

**Interfaces:**
- `def main(argv: list[str] | None = None) -> int`; subcommands:
  - `build [--level detail] [--year latest|2017|2012|2007] [--redefinitions after|before] [--scrap bea|redistribute|keep] [--out data/output] [--make PATH --use PATH] [--force]` → writes `<out>/us_io_<year>_<level>_<redefinitions>_<scrap>.xlsx` and a CSV folder of the same stem; prints the identity residuals and the ten largest `|y − g|` and `|GOS − BEA GOS|` entries with codes and descriptions; exit 0.
  - `check [same build options] [--tol 1e-3]` → builds, then downloads `ixi_tr` and compares `(I − A)^-1` (with `A = Z / y`) against BEA's table (parsed with `read_bea_grid`, sheet = year); prints `max_abs_diff`, `mean_abs_diff`, and the five worst cells; exit 0 if `max_abs_diff <= tol` else 1.
- `def ixi_total_requirements(sq: SquareIOTable) -> pd.DataFrame` in `validate.py` — `inv(I − Z ŷ⁻¹)` with industry labels.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli.py
def test_build_cli_writes_outputs(tmp_path, toy_workbooks):     # toy_workbooks: (make_path, use_path) written with write_bea_workbook
    make_p, use_p = toy_workbooks
    rc = cli.main(["build", "--make", str(make_p), "--use", str(use_p), "--year", "2017", "--out", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "us_io_2017_detail_after_bea.xlsx").exists() and (tmp_path / "us_io_2017_detail_after_bea" / "Z.csv").exists()

# tests/test_bea_ixi.py
@pytest.mark.network
@pytest.mark.parametrize("redefinitions", ["after", "before"])
def test_bea_mode_reproduces_bea_industry_by_industry_requirements(redefinitions, record_property):
    make, use = parse.load_bea_tables("detail", 2017, redefinitions)
    sq = square.build_square_table(make, use, scrap="bea")
    ours = validate.ixi_total_requirements(sq)
    bea = parse.read_bea_grid(download.fetch(sources.bea_detail_url("ixi_tr", "any"), sources.RAW_DIR / "bea"), "2017").values
    bea = bea.loc[ours.index, ours.columns]
    diff = (ours - bea).abs()
    record_property(f"max_abs_diff_{redefinitions}", float(diff.values.max()))
    print(f"{redefinitions}: max {diff.values.max():.2e} mean {diff.values.mean():.2e}")
    if redefinitions == "after":          # the documented default must match; 'before' is reported only
        assert diff.values.max() < 1e-3
```
If the `after` run fails the 1e-3 bound, do not loosen it: print the worst cells, try `before`, and if that one matches, switch the documented default in the spec and DEVLOG and make the assertion follow the matching one. If neither matches, stop and investigate with superpowers:systematic-debugging (candidates: BEA computing W at a different aggregation, treatment of S00402/S00900, government industries).

- [ ] **Step 2: Run to verify failure.** - [ ] **Step 3: Implement `cli.py` (`build`, `check`) and `validate.ixi_total_requirements`.**
- [ ] **Step 4: Run** — `pytest tests/test_cli.py tests/test_bea_ixi.py -v -s` → PASS; copy the printed max/mean diffs into the private working log.
- [ ] **Step 5: Commit** — `git commit -am "feat: iotables build/check CLI; verify against BEA 2017 industry-by-industry requirements"`

## Part B — Price model

### Task 10: Shock types and conversion to `(tau, T)`

**Files:**
- Create: `src/iotables/shocks.py`
- Test: `tests/test_shocks.py`, `tests/conftest.py` (`two_by_two` fixture)

**Interfaces:**
- `two_by_two() -> SquareIOTable` fixture: industries `["1","2"]`, `Z = [[10,20],[30,40]]`, `F` one column `F01000 = [70,30]`, `y = [100,100]`, `V` rows `V00100=[30,20], V00200=[0,0], V00300=[30,20]`; commodities `["a","b"]` with make `M = [[90,10],[0,100]]` so `market_shares = [[1, 10/110],[0, 100/110]]`, `N = market_shares`; labels `{"1":"One","2":"Two"}`, `{"a":"Alpha","b":"Beta"}`, `{"F01000":"PCE"}`; `meta={"year":2017,"level":"toy","commodity_output": pd.Series({"a": 90.0, "b": 110.0})}`. (`toy_use_grid` / `toy_make_grid` fixtures expose the underlying `BeaGrid`s; `toy_use`/`toy_make` wrap them.)
- Produces (`shocks.py`):
  - `@dataclass(frozen=True) class IndustryTax: code: str; dollars: float | None = None; rate: float | None = None` (exactly one of the two, validated in `__post_init__`)
  - `@dataclass(frozen=True) class CommodityTax: code: str; dollars: float | None = None; rate: float | None = None`
  - `@dataclass(frozen=True) class FlowTax: seller: str; buyer: str; rate: float`
  - `@dataclass(frozen=True) class ValueAddedTax: component: str; rate: float; industries: tuple[str, ...] | None = None`
  - `Shock = IndustryTax | CommodityTax | FlowTax | ValueAddedTax`
  - `def industry_dollars(shocks: Sequence[Shock], sq: SquareIOTable) -> pd.Series` — dollars per industry from Industry/Commodity/ValueAdded taxes (rate × base), index = all industries, zeros elsewhere; `CommodityTax` dollars split by `sq.market_shares[code]`; `CommodityTax(rate=r)` means `r × q_c` where `q_c = (sq.market_shares[c] * sq.y).sum()` is not available — instead store commodity output in `sq.meta["commodity_output"]` during build (Task 4 amendment: `meta["commodity_output"] = q`) and use it here.
  - `def to_tau_T(shocks: Sequence[Shock], sq: SquareIOTable) -> tuple[pd.Series, pd.DataFrame]` — `tau = industry_dollars / y` (industries with `y == 0` and nonzero dollars → `ValueError`); `T` n×n zeros with `T.loc[seller, buyer] += rate` for each `FlowTax`.
  - Unknown codes → `KeyError(f"unknown industry code {code!r}")` / `"unknown commodity code"` / `"unknown value-added component"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_industry_tax_rate_and_dollars_equivalent(two_by_two):
    tau1, T1 = shocks.to_tau_T([shocks.IndustryTax("1", rate=0.1)], two_by_two)
    tau2, T2 = shocks.to_tau_T([shocks.IndustryTax("1", dollars=10)], two_by_two)
    assert list(tau1) == [0.1, 0.0] and list(tau2) == [0.1, 0.0] and (T1.values == 0).all()

def test_commodity_tax_allocated_by_market_share(two_by_two):
    tau, _ = shocks.to_tau_T([shocks.CommodityTax("b", dollars=11)], two_by_two)
    assert tau["1"] == pytest.approx(0.01) and tau["2"] == pytest.approx(0.10)
    tau_r, _ = shocks.to_tau_T([shocks.CommodityTax("b", rate=0.1)], two_by_two)   # q_b = 110 -> $11
    assert tau_r["2"] == pytest.approx(0.10)

def test_flow_tax_fills_T(two_by_two):
    tau, T = shocks.to_tau_T([shocks.FlowTax("1", "2", 0.5)], two_by_two)
    assert (tau == 0).all() and T.loc["1", "2"] == 0.5 and T.values.sum() == 0.5

def test_value_added_tax(two_by_two):
    tau, _ = shocks.to_tau_T([shocks.ValueAddedTax("V00100", 0.1)], two_by_two)
    assert list(tau.round(6)) == [0.03, 0.02]
    tau2, _ = shocks.to_tau_T([shocks.ValueAddedTax("V00100", 0.1, industries=("2",))], two_by_two)
    assert list(tau2.round(6)) == [0.0, 0.02]

def test_shocks_compose_additively(two_by_two):
    tau, _ = shocks.to_tau_T([shocks.IndustryTax("1", rate=0.1), shocks.IndustryTax("1", dollars=5)], two_by_two)
    assert tau["1"] == pytest.approx(0.15)

def test_unknown_code_raises(two_by_two):
    with pytest.raises(KeyError, match="9"):
        shocks.to_tau_T([shocks.IndustryTax("9", rate=0.1)], two_by_two)
    with pytest.raises(ValueError):
        shocks.IndustryTax("1")                                   # neither dollars nor rate
    with pytest.raises(ValueError):
        shocks.IndustryTax("1", dollars=1, rate=0.1)
```

- [ ] **Step 2–4: fail → implement (including the `meta["commodity_output"]` amendment in `square.build_square_table` and in the `two_by_two` fixture) → pass.**
- [ ] **Step 5: Commit** — `git add src/iotables/shocks.py tests/test_shocks.py tests/conftest.py src/iotables/square.py && git commit -m "feat: shock types (industry, commodity, flow, value-added) and conversion to tau/T"`

### Task 11: `PriceModel`: baseline, output-tax solve, WP6 formulation, burden identity

**Files:**
- Rewrite: `src/iotables/leontief.py`
- Test: `tests/test_leontief.py`

**Interfaces:**
- `@dataclass class PriceResult: industry_prices: pd.DataFrame  # columns code, description, price_change; commodity_prices: pd.DataFrame | None; pce_prices: pd.DataFrame | None; burden_by_final_demand: pd.DataFrame  # columns code, description, base_spending, burden; summary: dict; shocks: list; notes: list[str]`
- `class PriceModel:`
  - `def __init__(self, sq: SquareIOTable, pce_bridge: "PCEBridge | None" = None, formulation: str = "output_tax", margin_codes: dict[str, list[str]] | None = None)` — `formulation ∈ {"output_tax", "wp6"}`; computes `self.A = Z / y` (column shares) and `self.v = (y − Z.sum(0)) / y`; raises `ValueError` if `baseline_prices()` deviates from 1 by more than 1e-9.
  - `def baseline_prices(self) -> pd.Series` — `solve(I − A.T, v)`.
  - `def run(self, shocks: Sequence[Shock]) -> PriceResult`:
    - `output_tax`: `tau, T = to_tau_T(shocks, sq)`; `A_hat = A * (1 + T)`; `p_hat = solve(I − A_hat.T, v + tau)`; `dp = p_hat − 1`.
    - `wp6`: only `IndustryTax`/`CommodityTax`/`ValueAddedTax` allowed (`FlowTax` → `ValueError`); `t_i = industry_dollars_i / Z.sum(axis=1)_i` where an `IndustryTax(rate=r)` is taken as `t_i = r` directly; `A_hat = diag(1 + t) @ A` (row i scaled); `p_hat = solve(I − A_hat.T, v)`.
    - `burden_by_final_demand`: `dp @ F` per column; `base_spending = F.sum(0)`.
    - `summary = {"formulation", "total_tax", "final_demand_burden", "identity_residual", "pce_burden" (None here)}` with `total_tax = (tau * y).sum() + (T * Z).mul(p_hat, axis=0).values.sum()` for `output_tax` (flow taxes valued at post-shock seller prices) and `(t * Z.sum(1)).sum()` for `wp6`; `identity_residual = final_demand_burden − total_tax` (asserted `< 1e-9 × total_tax` for `output_tax` in tests; not an identity under `wp6`).
    - `commodity_prices` and `pce_prices` are filled in Task 12 (None until then).

- [ ] **Step 1: Write the failing tests (hand-computed, spec §8.3–8.4)**

```python
def test_baseline_is_ones(two_by_two):
    assert np.allclose(leontief.PriceModel(two_by_two).baseline_prices().values, 1.0)

def test_output_tax_on_industry(two_by_two):
    r = leontief.PriceModel(two_by_two).run([shocks.IndustryTax("1", rate=0.1)])
    assert np.allclose(r.industry_prices["price_change"].values, [0.125, 0.0416667], atol=1e-6)
    assert r.burden_by_final_demand.loc[0, "burden"] == pytest.approx(10.0)       # 0.125*70 + 0.0416667*30
    assert r.summary["total_tax"] == pytest.approx(10.0) and abs(r.summary["identity_residual"]) < 1e-9

def test_flow_tax(two_by_two):
    r = leontief.PriceModel(two_by_two).run([shocks.FlowTax("1", "2", 0.5)])
    assert np.allclose(r.industry_prices["price_change"].values, [0.0666667, 0.2], atol=1e-6)
    assert r.summary["total_tax"] == pytest.approx(10.6666667, abs=1e-6)         # 0.5*20*1.0666667
    assert abs(r.summary["identity_residual"]) < 1e-9

def test_wp6_formulation(two_by_two):
    m = leontief.PriceModel(two_by_two, formulation="wp6")
    r = m.run([shocks.IndustryTax("1", dollars=3)])                                # t_1 = 3/30 = 0.1
    assert np.allclose(r.industry_prices["price_change"].values, [0.0256410, 0.0427350], atol=1e-6)
    r2 = m.run([shocks.IndustryTax("1", rate=0.1)])
    assert np.allclose(r2.industry_prices["price_change"].values, r.industry_prices["price_change"].values)
    with pytest.raises(ValueError):
        m.run([shocks.FlowTax("1", "2", 0.1)])

def test_wp6_replicates_2009_price_impacts():
    """Distributional Model.xlsx, Pi sheet column E, with Policy Inputs L10/L11 as rates (spec §9)."""
    sq = build_2002_summary()                                   # helper in conftest using the Task 8 fixtures (keep mode)
    r = leontief.PriceModel(sq, formulation="wp6").run([shocks.IndustryTax("2110", rate=0.3954367423979727),
                                                         shocks.IndustryTax("2121", rate=1.8694564238089508)])
    p = r.industry_prices.set_index("code")["price_change"] + 1
    for code, expected in {"1110": 1.0249967298379448, "2110": 1.0202324094628146, "2121": 1.1472503329037465,
                           "2211": 1.1650275425430783, "2212": 1.185103762352647, "S007": 1.0104328673003136}.items():
        assert p[code] == pytest.approx(expected, abs=1e-6)
```

- [ ] **Step 2–4: fail → implement → pass** (`pytest tests/test_leontief.py -v`).
- [ ] **Step 5: Commit** — `git add src/iotables/leontief.py tests/test_leontief.py tests/conftest.py && git commit -m "feat: Leontief price model with output-tax and WP6 formulations; replicates 2009 results"`

### Task 12: PCE bridge and consumer-price stage

**Files:**
- Create: `src/iotables/bridge.py`
- Modify: `src/iotables/leontief.py`
- Test: `tests/test_bridge.py`, `tests/test_leontief.py` (append)

**Interfaces:**
- Produces (`bridge.py`):
  - `MARGIN_CODES = {"detail": {"transport": ["481000","482000","483000","484000","486000"], "wholesale": ["423100","423400","423600","423800","423A00","424200","424400","424700","424A00","425000"], "retail": ["441000","444000","445000","446000","447000","448000","452000","454000","4B0000"]}}`
  - `@dataclass class PCEBridge: rows: pd.DataFrame  # columns nipa_line (str), pce_category, commodity (str), commodity_desc, producers_value, transport, wholesale, retail, purchasers_value (float); year: int; meta: dict`
    - `def categories(self) -> pd.DataFrame` — one row per `nipa_line` with `pce_category` and summed `purchasers_value`.
  - `def parse_pce_bridge(path: Path, year: int | str = "latest") -> PCEBridge` — the year sheet has a two-row header (row 5 group labels, row 6: `NIPA Line, PCE Category, Commodity Code, Commodity Description, <producers>, <transport>, Wholesale, Retail, <purchasers>, Year`); locate by the row whose first cell is `"NIPA Line"`; coerce codes with `normalize_code`; stop at the first blank row.
  - `def load_pce_bridge(level: str = "detail", year: int | str = "latest", data_dir: Path = RAW_DIR, force: bool = False) -> PCEBridge`
- Modifies (`leontief.py`):
  - `PriceModel.commodity_price_changes(self, dp: pd.Series) -> pd.Series` — `market_shares.T @ dp` over commodities with output > 0.
  - `PriceModel.margin_price_changes(self, dp_c: pd.Series) -> dict[str, float]` — output-weighted (`meta["commodity_output"]`) mean of `dp_c` over each list in `margin_codes` (`self.margin_codes` defaults to `MARGIN_CODES.get(sq.meta.get("level"), None)`); codes absent from the table are ignored; an empty list → `ValueError`.
  - `PriceModel.pce_price_changes(self, dp_c: pd.Series, margins: dict[str, float]) -> tuple[pd.DataFrame, list[str]]` — per NIPA line: `dP_k = Σ(PV·dp_c + TC·m_t + WM·m_w + RM·m_r) / Σ PurchV` with `dp_c = 0` for commodities not in the table (each such code noted once); lines with `Σ PurchV == 0` get `dP = 0` and a note. Returns frame `[nipa_line, pce_category, price_change, base_spending, burden]` sorted by `nipa_line` as int when possible.
  - `run()` now fills `commodity_prices` (`[code, description, price_change]`) always, and `pce_prices` + `summary["pce_burden"]` + `summary["pce_share_of_burden"]` when a bridge is present; `notes` collects the bridge notes.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_bridge.py
def test_parse_pce_bridge_synthetic(tmp_path):   # write a tiny workbook in the BEA bridge layout with 3 rows, 2 NIPA lines
    b = bridge.parse_pce_bridge(write_pce_bridge_workbook(tmp_path / "b.xlsx"), 2017)
    assert list(b.rows.columns) == ["nipa_line", "pce_category", "commodity", "commodity_desc", "producers_value", "transport", "wholesale", "retail", "purchasers_value"]
    assert b.rows["nipa_line"].tolist() == ["7", "7", "13"] and b.categories().shape[0] == 2

@pytest.mark.network
def test_parse_pce_bridge_2017_detail():
    b = bridge.load_pce_bridge("detail", 2017)
    assert b.rows["nipa_line"].nunique() == 212 and b.rows["commodity"].nunique() == 259
    assert (b.rows["purchasers_value"] - b.rows[["producers_value", "transport", "wholesale", "retail"]].sum(axis=1)).abs().max() <= 1.0

# tests/test_leontief.py (append)
def synthetic_bridge():
    rows = pd.DataFrame([["1", "Thing", "a", "Alpha", 80, 5, 5, 10, 100],
                         ["2", "Other", "b", "Beta", 50, 0, 0, 0, 50],
                         ["3", "Missing", "zzz", "Gone", 10, 0, 0, 0, 10]],
                        columns=["nipa_line", "pce_category", "commodity", "commodity_desc", "producers_value", "transport", "wholesale", "retail", "purchasers_value"])
    return bridge.PCEBridge(rows=rows, year=2017, meta={})

def test_commodity_and_pce_prices(two_by_two):
    m = leontief.PriceModel(two_by_two, pce_bridge=synthetic_bridge(), margin_codes={"transport": ["b"], "wholesale": ["b"], "retail": ["b"]})
    r = m.run([shocks.IndustryTax("1", rate=0.1)])
    c = r.commodity_prices.set_index("code")["price_change"]
    assert c["a"] == pytest.approx(0.125) and c["b"] == pytest.approx(0.0492424, abs=1e-6)
    p = r.pce_prices.set_index("nipa_line")
    assert p.loc["1", "price_change"] == pytest.approx(0.10984848, abs=1e-6)       # (80*.125 + 20*.0492424)/100
    assert p.loc["2", "price_change"] == pytest.approx(0.0492424, abs=1e-6)
    assert p.loc["3", "price_change"] == 0.0
    assert r.summary["pce_burden"] == pytest.approx(13.44697, abs=1e-4)
    assert any("zzz" in n for n in r.notes)

def test_bridge_missing_commodity_noted(two_by_two):
    b = synthetic_bridge(); b.rows.loc[b.rows.nipa_line == "2", "purchasers_value"] = 0
    r = leontief.PriceModel(two_by_two, pce_bridge=b, margin_codes={"transport": ["b"], "wholesale": ["b"], "retail": ["b"]}).run([shocks.IndustryTax("1", rate=0.1)])
    assert r.pce_prices.set_index("nipa_line").loc["2", "price_change"] == 0.0 and any("purchasers" in n for n in r.notes)
```

- [ ] **Step 2–4: fail → implement → pass** (`pytest tests/test_bridge.py tests/test_leontief.py -v`).
- [ ] **Step 5: Commit** — `git add src/iotables/bridge.py src/iotables/leontief.py tests/test_bridge.py tests/test_leontief.py tests/conftest.py && git commit -m "feat: PCE bridge stage: commodity prices, margin-aware consumer price changes and burdens"`

### Task 13: Carbon-pricing preset from EIA emissions

**Files:**
- Modify: `src/iotables/shocks.py`
- Create: `tests/fixtures/eia_t11_01_sample.csv` (header + the 2024 annual rows for CKTCEUS, NNTCEUS, PMTCEUS, TETCEUS, one monthly row, and one `"Not Available"` row)
- Test: `tests/test_shocks.py` (append)

**Interfaces:**
- `EIA_SERIES = {"coal": "CKTCEUS", "natural_gas": "NNTCEUS", "petroleum": "PMTCEUS", "total": "TETCEUS"}`
- `CARBON_INDUSTRIES = {"detail": {"coal": "212100", "natural_gas": "211000", "petroleum": "211000"}}`
- `def eia_co2_by_fuel(year: int, data_dir: Path = RAW_DIR, force: bool = False, path: Path | None = None) -> dict[str, float]` — million metric tons CO2 for the annual row (`YYYYMM == f"{year}13"`); `path` bypasses download (tests); missing year → `ValueError`.
- `def carbon_price(dollars_per_ton_co2: float, emissions_year: int, coverage: str = "upstream", level: str = "detail", data_dir: Path = RAW_DIR, path: Path | None = None) -> list[IndustryTax]` — dollars (millions) = MMT × $/ton; fuels mapping to the same industry are merged; returns one `IndustryTax(code, dollars=…)` per industry sorted by code; `coverage != "upstream"` → `NotImplementedError`.

- [ ] **Step 1: Write the failing tests**

```python
def test_eia_co2_by_fuel_from_fixture():
    d = shocks.eia_co2_by_fuel(2024, path=FIX / "eia_t11_01_sample.csv")
    assert d == {"coal": 751.237, "natural_gas": 1790.121, "petroleum": 2240.92, "total": 4789.102}
    with pytest.raises(ValueError):
        shocks.eia_co2_by_fuel(1901, path=FIX / "eia_t11_01_sample.csv")

def test_carbon_price_upstream_detail():
    s = shocks.carbon_price(50, 2024, path=FIX / "eia_t11_01_sample.csv")
    assert s == [shocks.IndustryTax("211000", dollars=pytest.approx((1790.121 + 2240.92) * 50)),
                 shocks.IndustryTax("212100", dollars=pytest.approx(751.237 * 50))]

@pytest.mark.network
def test_eia_download_has_recent_year():
    assert shocks.eia_co2_by_fuel(2023)["coal"] == pytest.approx(776.47, abs=1.0)
```
(For the equality on dataclasses with `pytest.approx`, compare fields explicitly if `==` proves awkward.)

- [ ] **Step 2–4: fail → implement → pass.**
- [ ] **Step 5: Commit** — `git add src/iotables/shocks.py tests/fixtures/eia_t11_01_sample.csv tests/test_shocks.py && git commit -m "feat: carbon-price preset from EIA CO2 by fuel"`

### Task 14: CLI `run`, end-to-end on 2017, README, DEVLOG

**Files:**
- Modify: `src/iotables/cli.py`, `src/iotables/__init__.py` (export `PriceModel, PriceResult, load_pce_bridge, shocks`), `README.md` (plus the private working log, not in the repository)
- Test: `tests/test_cli.py` (append), `tests/test_end_to_end.py`

**Interfaces:**
- `run [build options] [--table PATH.xlsx] (--shock SPEC)... [--carbon DOLLARS_PER_TON --emissions-year YYYY] [--formulation output_tax|wp6] [--no-pce] [--out DIR]`
  - `--table` reads a previously built Excel file via `square.read_square_frame` and `SquareIOTable.from_frame(frame, meta)` (add `from_frame` to `square.py`: splits the legacy layout back into Z, F, V, y; `market_shares` is not recoverable from the frame, so `--table` runs disable commodity/PCE output with a printed note unless the sibling CSV folder with `market_shares.csv` exists, in which case it is loaded).
  - `SPEC` grammar: `industry:CODE:dollars=X | industry:CODE:rate=R | commodity:CODE:dollars=X | commodity:CODE:rate=R | flow:SELLER:BUYER:rate=R | va:COMPONENT:rate=R[:industries=A,B]`; `def parse_shock_spec(spec: str) -> Shock` in `cli.py` (bad spec → `SystemExit(2)` with the grammar in the message).
  - Writes `<out>/industry_prices.csv`, `commodity_prices.csv`, `pce_prices.csv`, `burden_by_final_demand.csv`, `summary.json`, `shocks.json`; prints the summary and the 20 PCE categories with the largest price increases.

- [ ] **Step 1: Write the failing tests**

```python
def test_parse_shock_spec():
    assert cli.parse_shock_spec("industry:211000:dollars=50000") == shocks.IndustryTax("211000", dollars=50000.0)
    assert cli.parse_shock_spec("flow:221100:331110:rate=0.1") == shocks.FlowTax("221100", "331110", 0.1)
    assert cli.parse_shock_spec("va:V00100:rate=0.01:industries=1,2") == shocks.ValueAddedTax("V00100", 0.01, ("1", "2"))
    with pytest.raises(SystemExit):
        cli.parse_shock_spec("industry:211000")

def test_run_cli_on_toy(tmp_path, toy_workbooks):
    make_p, use_p = toy_workbooks
    rc = cli.main(["run", "--make", str(make_p), "--use", str(use_p), "--year", "2017", "--no-pce",
                   "--shock", "industry:A:rate=0.1", "--out", str(tmp_path)])
    assert rc == 0 and (tmp_path / "industry_prices.csv").exists() and json.loads((tmp_path / "summary.json").read_text())["total_tax"] > 0

# tests/test_end_to_end.py
@pytest.mark.network
def test_carbon_50_on_2017_detail(tmp_path):
    rc = cli.main(["run", "--year", "2017", "--carbon", "50", "--emissions-year", "2024", "--out", str(tmp_path)])
    assert rc == 0
    s = json.loads((tmp_path / "summary.json").read_text())
    assert abs(s["identity_residual"]) < 1e-6 * s["total_tax"]
    assert 0.3 < s["pce_share_of_burden"] < 0.9
    pce = pd.read_csv(tmp_path / "pce_prices.csv")
    top = pce.sort_values("price_change", ascending=False).head(5)["pce_category"].str.lower().str.cat(sep=" ")
    assert "gas" in top or "electric" in top or "fuel" in top         # energy categories must lead
```

- [ ] **Step 2–4: fail → implement → pass** (`pytest -v`, full suite; the end-to-end test takes a minute on first download).
- [ ] **Step 5: Write `README.md`** (spec §10): purpose, one-paragraph method with the formulas from spec §7.4 and §8.3, install, `iotables build` / `check` / `run` with the carbon example and an excise-tax example, how validation was done (2002 tables, WP6, BEA IxI with the measured max diff), citations to the methodology paper and WP6, and the Phase 2 note. Append a dated entry to `the private working log` summarizing what was built, test counts, the IxI match figures, and the carbon-run headline numbers.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat: iotables run CLI, end-to-end carbon example, README"`

---

## Self-review notes (done while writing)

- Spec coverage: §5 objects → Tasks 3, 4, 11, 12; §6.1 download/parse → Tasks 1–3; §6.2 bridge → Task 12; §6.3 EIA → Task 13; §7.1–7.6 → Tasks 4–7; §8.1–8.5 → Tasks 10–12; §9 toy/2002/WP6/IxI/identities/parsing robustness → Tasks 5, 8, 11, 9, 4, 2; §10 README → Task 14; §11 builder calls are left open as the spec says. Phase 2 (§6.1 API) intentionally absent.
- Type consistency: `SquareIOTable.market_shares` is used for commodity prices (Tasks 10, 12) and `N` only for building `Z`; `meta["commodity_output"]` is introduced in Task 10 as an amendment to Task 4 and used in Tasks 10 and 12; `read_square_frame`/`from_frame` live in `square.py` (Tasks 7, 14).
- Proportion: code blocks are test assertions and signatures; the only algorithmic prose is the redistribution loop, the header rule, and the solve order.
