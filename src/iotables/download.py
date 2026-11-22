"""Stage 1: fetch BEA make and use tables (and related files) to data/raw/.

Responsibilities
- Know the current BEA file locations (static xlsx URLs and/or the BEA API).
- Download with caching: skip files already present unless forced.
- Record provenance (URL, download date, file hash) next to each file.

Not yet implemented. Known-good static URLs as of 2026-11-22 are listed in
DEVLOG.txt (2017 benchmark, 402-industry detail level).
"""
