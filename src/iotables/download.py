"""Stage 1: fetch BEA make and use tables (and related files) to data/raw/.

Responsibilities
- Download with caching: skip files already present unless forced.
- Stream to a temporary `.part` file and rename only on success, so an
  interrupted download never leaves a plausible-looking partial file.
- Record provenance (URL, SHA-256, byte count, UTC download time) in a
  `<filename>.provenance.json` sidecar next to each file.

The URL manifest lives in sources.py.
"""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

_CHUNK = 1 << 16
_TIMEOUT_SECONDS = 120


def sha256_of(path: Path) -> str:
    """Hex SHA-256 digest of the file at `path`, read in chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(
    url: str,
    dest_dir: Path,
    *,
    filename: str | None = None,
    force: bool = False,
    session: requests.Session | None = None,
) -> Path:
    """Download `url` into `dest_dir` and return the cached file's path.

    `filename` defaults to the last segment of the URL path. When the file and
    its provenance sidecar both exist and `force` is False, no request is made.
    """
    if filename is None:
        filename = Path(urlparse(url).path).name
        if not filename:
            raise ValueError(f"cannot derive a filename from {url!r}; pass filename=")

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    part = dest_dir / (filename + ".part")
    sidecar = dest_dir / (filename + ".provenance.json")

    if dest.exists() and sidecar.exists() and not force:
        return dest

    get = session.get if session is not None else requests.get
    try:
        with get(url, stream=True, timeout=_TIMEOUT_SECONDS) as response:
            response.raise_for_status()
            with open(part, "wb") as f:
                for chunk in response.iter_content(chunk_size=_CHUNK):
                    f.write(chunk)
        # Drop the old sidecar first so a crash between the rename and the new
        # sidecar leaves "file without provenance" (re-downloaded next time),
        # never a new file paired with a stale hash.
        sidecar.unlink(missing_ok=True)
        os.replace(part, dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise

    provenance = {
        "url": url,
        "sha256": sha256_of(dest),
        "bytes": dest.stat().st_size,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
    }
    sidecar.write_text(json.dumps(provenance, indent=2) + "\n")
    return dest
