"""Download NASA GPM IMERG Final v07 daily precipitation for North Evia.

Uses NASA Earthdata catalog + GES DISC OPeNDAP ASCII subset (9 nearby 0.1 degree
cells). No global granules downloaded. Files are cached per year and resumed.

    python data_prep/download_imerg_daily.py --first-year 2023 --last-year 2024

Authenticate with `earthaccess.login(strategy='interactive', persist=True)` once.
NASA IMERG Final has a publication lag; recent dates may not be available.
"""
import argparse
import re
import time
from concurrent.futures import ThreadPoolExecutor

import earthaccess
import pandas as pd

try:
    from .config import PROC, RAW, STUDY_AREA
except ImportError:
    from .config import PROC, RAW, STUDY_AREA


def geographic_indices(study_area, pad=0.1):
    west, east, south, north = study_area
    lon0, lon1 = int(round((west - pad + 179.95) / 0.1)), int(round((east + pad + 179.95) / 0.1))
    lat0, lat1 = int(round((south - pad + 89.95) / 0.1)), int(round((north + pad + 89.95) / 0.1))
    return lon0, lon1, lat0, lat1


def opendap_url(granule):
    links = [u for u in granule.data_links() if u.endswith(".nc4")]
    if not links:
        raise ValueError("NASA IMERG granule does not provide an .nc4 link")
    if "/data/" not in links[0]:
        raise ValueError("Unexpected NASA GES DISC granule URL")
    path = links[0].split("/data/", 1)[1]
    a, b, c, d = geographic_indices(STUDY_AREA)
    subset = f"precipitation[0:1:0][{a}:1:{b}][{c}:1:{d}]"
    return f"https://gpm1.gesdisc.eosdis.nasa.gov/opendap/{path}.ascii?{subset}"


def parse_ascii(text, day):
    """Parse the rectangular subset; avoid negative NASA fill values."""
    lines = text.splitlines()
    latitude_row = next((l for l in lines if l.startswith("precipitation.lat")), None)
    if latitude_row is None:
        raise ValueError("No latitude coordinates in GPM OPeNDAP response")
    lats = [float(v) for v in latitude_row.split(",")[1:]]
    rows = []
    pattern = re.compile(r"precipitation\.precipitation\[.*\]\[precipitation\.lon=([-\d.]+)\],(.*)")
    for line in lines:
        m = pattern.match(line)
        if m:
            lon = float(m.group(1))
            values = [float(v) for v in m.group(2).split(",")]
            if len(values) != len(lats):
                raise ValueError("NASA precipitation data shape differs from latitude grid")
            for lat, mm in zip(lats, values):
                rows.append((pd.Timestamp(day), lat, lon, mm if mm >= 0 else float("nan")))
    if not rows:
        raise ValueError("No precipitation cells in NASA OPeNDAP response")
    return pd.DataFrame(rows, columns=["date", "lat", "lon", "precip_mm"])


def read(granule, session):
    day = granule["umm"]["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"][:10]
    url = opendap_url(granule)
    last_error = None
    for attempt in range(5):
        try:
            r = session.get(url, timeout=(15, 90))
            r.raise_for_status()
            return parse_ascii(r.text, day)
        except Exception as err:
            last_error = err
            if attempt < 4:
                time.sleep(2 ** attempt + 1)
    print(f"WARNING: NASA IMERG {day} failed: {type(last_error).__name__}", flush=True)
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--first-year", type=int, default=2023)
    ap.add_argument("--last-year", type=int, default=2024)
    ap.add_argument("--workers", type=int, choices=range(1, 9), default=4)
    args = ap.parse_args(argv)
    if args.first_year < 1998 or args.last_year < args.first_year:
        ap.error("Provide an ascending year range starting in 1998 or later")
    cache = RAW / "imerg_daily"
    cache.mkdir(parents=True, exist_ok=True)
    PROC.mkdir(parents=True, exist_ok=True)
    auth = earthaccess.login(strategy="netrc")
    if not auth or not auth.authenticated:
        raise SystemExit("NASA Earthdata login is required. See README.md")
    session = earthaccess.get_requests_https_session()
    selected = []
    for year in range(args.first_year, args.last_year + 1):
        output = cache / f"{year}.parquet"
        previous = pd.read_parquet(output) if output.exists() else None
        granules = earthaccess.search_data(
            short_name="GPM_3IMERGDF", version="07",
            temporal=(f"{year}-01-01", f"{year}-12-31"),
            bounding_box=(STUDY_AREA[0], STUDY_AREA[2], STUDY_AREA[1], STUDY_AREA[3]),
        )
        granules = [g for g in granules if g["umm"]["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"][:4] == str(year)]
        done = set(previous.date.dt.strftime("%Y-%m-%d")) if previous is not None else set()
        missing = [g for g in granules if g["umm"]["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"][:10] not in done]
        if missing:
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                fetched = [df for df in pool.map(lambda g: read(g, session), missing) if df is not None]
            parts = ([previous] if previous is not None else []) + fetched
            if parts:
                year_df = pd.concat(parts, ignore_index=True).drop_duplicates(["date", "lat", "lon"]).sort_values(["date", "lat", "lon"])
                year_df.to_parquet(output, index=False)
        if output.exists():
            selected.append(pd.read_parquet(output))
            print(f"{year}: {pd.read_parquet(output).date.nunique()} daily observations cached ({len(granules)} cataloged)")
        else:
            print(f"{year}: no downloaded observations; verify Earthdata access and availability")
    if not selected:
        raise SystemExit("No GPM data available; no files published")
    allp = pd.concat(selected, ignore_index=True).sort_values(["date", "lat", "lon"])
    allp.to_parquet(PROC / f"imerg_daily_{args.first_year}_{args.last_year}.parquet", index=False)
    w, e, s, n = STUDY_AREA
    inside = allp[allp.lat.between(s - 0.05, n + 0.05) & allp.lon.between(w - 0.05, e + 0.05)]
    if inside.empty:
        raise RuntimeError("No IMERG cells overlap the study area")
    inside.groupby("date").precip_mm.mean().to_frame().to_parquet(PROC / f"imerg_area_mean_{args.first_year}_{args.last_year}.parquet")
    print(f"Saved {allp.date.nunique()} NASA GPM daily estimates; values are km-scale, not field measurements")


if __name__ == "__main__":
    main()
