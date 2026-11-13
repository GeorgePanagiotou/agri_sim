"""Acquire only official NASA SRTMGL1 v003 elevation tiles intersecting North Evia.

    python data_prep/download_srtm.py --limit 10

SRTM is a static elevation model, approximately 30 m (one arc second).
Login to Earthdata once before downloading. Saves the original NASA granules.
"""
import argparse
import json
from datetime import datetime, timezone

import earthaccess

try:
    from .config import RAW, STUDY_AREA
except ImportError:
    from .config import RAW, STUDY_AREA

SHORT_NAME = "SRTMGL1"
VERSION = "003"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=12, help="Safety limit on downloaded SRTM tiles")
    args = ap.parse_args(argv)
    w, e, s, n = STUDY_AREA
    granules = earthaccess.search_data(
        short_name=SHORT_NAME, version=VERSION,
        bounding_box=(w, s, e, n),
    )
    if not granules:
        raise SystemExit("No NASA SRTMGL1 tiles found over the configured study area")
    if len(granules) > args.limit:
        raise SystemExit(f"Search returned {len(granules)} tiles; increase --limit if intended")
    out = RAW / "srtm"
    out.mkdir(parents=True, exist_ok=True)
    metadata = {
        "dataset": "NASA SRTMGL1.003",
        "doi": "10.5067/MEaSUREs/SRTM/SRTMGL1.003",
        "bounding_box_wsen": [w, s, e, n],
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
        "granules": [g["umm"].get("GranuleUR") for g in granules],
    }
    # Metadata save is safe without authentication; login required for data bytes.
    (out / "source_manifest.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    auth = earthaccess.login(strategy="netrc")
    if not auth or not auth.authenticated:
        raise SystemExit("NASA Earthdata login required to download SRTM tiles")
    files = earthaccess.download(granules, str(out))
    print(f"NASA SRTM: {len(files)} local files in {out}")


if __name__ == "__main__":
    main()
