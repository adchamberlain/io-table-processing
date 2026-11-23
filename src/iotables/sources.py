"""Where the data comes from: local directories and the URLs of the BEA and EIA
files the module downloads (static URLs, no API key).
"""

from pathlib import Path

RAW_DIR = Path("data/raw")

_BEA_IO = "https://apps.bea.gov/industry/xls/io-annual"
_BEA_UNDERLYING = "https://apps.bea.gov/industry/xls/underlying-estimates"

# BEA's 2017 benchmark detail workbooks (each also holds the 2007 and 2012
# benchmarks). Make, use and the import matrix are before redefinitions, the
# basis on which BEA publishes the import matrix.
BEA_DETAIL_FILES: dict[str, str] = {
    "make": f"{_BEA_IO}/IOMake_Before_Redefinitions_2017_Detail.xlsx",
    "use": f"{_BEA_IO}/IOUse_Before_Redefinitions_PRO_2017_Detail.xlsx",
    "import_matrix": f"{_BEA_IO}/ImportMatrices_Before_Redefinitions_DET_2017.xlsx",
    "pce_bridge": f"{_BEA_UNDERLYING}/PCEBridge_2017_DET.xlsx",
}

EIA_CO2_URL = "https://www.eia.gov/totalenergy/data/browser/csv.php?tbl=T11.01"


def bea_detail_url(table: str) -> str:
    """The URL of a BEA detail workbook: "make", "use", "import_matrix" or "pce_bridge" (KeyError otherwise)."""
    try:
        return BEA_DETAIL_FILES[table]
    except KeyError:
        raise KeyError(f"no BEA detail file {table!r}; have {sorted(BEA_DETAIL_FILES)}") from None
