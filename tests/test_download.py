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

def test_source_list_has_the_bea_files():
    assert sources.bea_detail_url("make").endswith("IOMake_Before_Redefinitions_2017_Detail.xlsx")
    assert sources.bea_detail_url("use").endswith("IOUse_Before_Redefinitions_PRO_2017_Detail.xlsx")
    assert sources.bea_detail_url("import_matrix").endswith("ImportMatrices_Before_Redefinitions_DET_2017.xlsx")
    assert sources.bea_detail_url("pce_bridge").endswith("PCEBridge_2017_DET.xlsx")
    with pytest.raises(KeyError):
        sources.bea_detail_url("sideways")

def test_fetch_http_error_leaves_nothing_behind(tmp_path, monkeypatch):
    monkeypatch.setattr(download.requests, "get", lambda url, **kw: FakeResponse([b"nope"], status=404))
    with pytest.raises(download.requests.HTTPError):
        download.fetch("https://example.test/x.xlsx", tmp_path)
    assert list(tmp_path.iterdir()) == []

def test_fetch_uses_given_session_and_filename(tmp_path):
    seen = []
    class FakeSession:
        def get(self, url, **kw):
            seen.append((url, kw))
            return FakeResponse([b"csv"])
    p = download.fetch("https://example.test/csv.php?tbl=T11.01", tmp_path,
                       filename="eia_co2.csv", session=FakeSession())
    assert p == tmp_path / "eia_co2.csv" and p.read_bytes() == b"csv"
    assert (tmp_path / "eia_co2.csv.provenance.json").exists()
    assert seen[0][1]["stream"] is True and seen[0][1]["timeout"] == 120

def test_sha256_of(tmp_path):
    f = tmp_path / "f.bin"
    f.write_bytes(b"abcdef")
    assert download.sha256_of(f) == hashlib.sha256(b"abcdef").hexdigest()
