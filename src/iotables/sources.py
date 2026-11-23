"""Where the data comes from: local directories and the URL manifest for the BEA
and EIA files the pipeline downloads (static URLs, no API key; verified 2026-11-22).
"""

from pathlib import Path

RAW_DIR = Path("data/raw")
OUTPUT_DIR = Path("data/output")

_BEA_IO = "https://apps.bea.gov/industry/xls/io-annual"
_BEA_UNDERLYING = "https://apps.bea.gov/industry/xls/underlying-estimates"

# Keyed by (table, redefinitions). Make and use come in both redefinition
# variants; the remaining files have a single version, so their second key is
# "any" (margins and the import matrix exist only "before"). The make/use files are the "2017_Detail"
# workbooks (sheets 2007, 2012, 2017); the older "..._DET.xlsx" names under
# io-annual (last modified 2021) hold only 2007 and 2012.
BEA_DETAIL_FILES: dict[tuple[str, str], str] = {
    ("make", "after"): f"{_BEA_IO}/IOMake_After_Redefinitions_2017_Detail.xlsx",
    ("use", "after"): f"{_BEA_IO}/IOUse_After_Redefinitions_PRO_2017_Detail.xlsx",
    ("make", "before"): f"{_BEA_IO}/IOMake_Before_Redefinitions_2017_Detail.xlsx",
    ("use", "before"): f"{_BEA_IO}/IOUse_Before_Redefinitions_PRO_2017_Detail.xlsx",
    ("ixi_tr", "any"): f"{_BEA_IO}/IxI_TR_2017_PRO_DET.xlsx",
    ("import_matrix", "before"): f"{_BEA_IO}/ImportMatrices_Before_Redefinitions_DET_2017.xlsx",
    ("pce_bridge", "any"): f"{_BEA_UNDERLYING}/PCEBridge_2017_DET.xlsx",
    ("margins", "before"): f"{_BEA_UNDERLYING}/Margins_Before_Redefinitions_2017_DET.xlsx",
}

EIA_CO2_URL = "https://www.eia.gov/totalenergy/data/browser/csv.php?tbl=T11.01"


def bea_detail_url(table: str, redefinitions: str = "after") -> str:
    """Return the BEA detail-level workbook URL for (table, redefinitions).

    Raises KeyError listing the valid keys when the pair is not in the manifest.
    """
    try:
        return BEA_DETAIL_FILES[(table, redefinitions)]
    except KeyError:
        valid = ", ".join(f"({t!r}, {r!r})" for t, r in BEA_DETAIL_FILES)
        raise KeyError(
            f"no BEA detail file for table={table!r}, redefinitions={redefinitions!r}; "
            f"valid keys: {valid}"
        ) from None
