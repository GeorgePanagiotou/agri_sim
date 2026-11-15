"""GPM IMERG Final daily (GPM_3IMERGDF v07, 0.1 deg) over the study area, 2001 onwards, through NASA GES DISC
OPeNDAP: each request returns only the cells around the study area (~600 bytes), not the global file.
Earthdata login from ~/_netrc (earthaccess).

Outputs
- data/raw/imerg_daily/<year>.parquet   per-year cache (resume: years already done are skipped)
- data/processed/imerg_daily_2001_2025.parquet  date, lat, lon, precip_mm (cells touching the area + 1 ring)
- data/processed/imerg_daily_area_mean.parquet  date, precip_mm (mean over the cells inside the study area)

    ..\\.venv\\Scripts\\python.exe data_prep\\download_imerg_daily.py [first_year] [last_year]
"""
import re
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor

import earthaccess

import earthdata  # login: Settings (env) or ~/.netrc
import pandas as pd

from config import PROC, RAW, STUDY_AREA

warnings.filterwarnings("ignore")
FIRST = int(sys.argv[1]) if len(sys.argv) > 1 else 2001
LAST = int(sys.argv[2]) if len(sys.argv) > 2 else 2025
W, E, S, N = STUDY_AREA
PAD = 0.1
# IMERG grid: lon -179.95..179.95, lat -89.95..89.95, step 0.1; variable order precipitation[time][lon][lat]
LON0, LON1 = int(round((W - PAD + 179.95) / 0.1)), int(round((E + PAD + 179.95) / 0.1))
LAT0, LAT1 = int(round((S - PAD + 89.95) / 0.1)), int(round((N + PAD + 89.95) / 0.1))
CE = f"precipitation[0:1:0][{LON0}:1:{LON1}][{LAT0}:1:{LAT1}]"
CACHE = RAW / "imerg_daily"
CACHE.mkdir(parents=True, exist_ok=True)
earthdata.login()
session = earthaccess.get_requests_https_session()


def opendap_urls(granule) -> list[str]:
    """Earthdata cloud OPeNDAP first, then the older GES DISC OPeNDAP (being retired; slow / 503 since 2026-11)."""
    urls = [f"{u['URL']}.ascii?{CE}" for u in granule["umm"].get("RelatedUrls", [])
            if u.get("Subtype") == "OPENDAP DATA" and u["URL"].startswith("https://opendap.earthdata.nasa.gov/")][:1]
    link = next((u for u in granule.data_links() if u.endswith(".nc4")), None)
    if link and "/data/" in link:
        path = link.split("/data/", 1)[1]  # GPM_L3/GPM_3IMERGDF.07/YYYY/MM/<file>.nc4
        urls.append(f"https://gpm1.gesdisc.eosdis.nasa.gov/opendap/{path}.ascii?{CE}")
    return urls


def read(granule):
    day = pd.Timestamp(granule["umm"]["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"][:10])
    urls = opendap_urls(granule)
    err = ValueError("no OPeNDAP link")
    for attempt in range(6):
        url = urls[min(attempt // 3, len(urls) - 1)] if urls else None   # 3 tries per server
        if url is None:
            break
        try:
            r = session.get(url, timeout=60)
            r.raise_for_status()
            lines = r.text.splitlines()
            lats = [float(v) for v in next(l for l in lines if l.startswith("precipitation.lat")).split(",")[1:]]
            rows = []
            for line in lines:
                m = re.match(r"precipitation\.precipitation\[.*\]\[precipitation\.lon=([-\d.]+)\],(.*)", line)
                if m:
                    lon = float(m.group(1))
                    rows += [(day, lat, lon, float(v)) for lat, v in zip(lats, m.group(2).split(","))]
            if rows:
                return pd.DataFrame(rows, columns=["date", "lat", "lon", "precip_mm"])
        except Exception as exc:  # 503 = throttling: back off and retry
            err = exc
            time.sleep(2 ** (attempt % 3) + 1)
    print("FAILED", day.date(), type(err).__name__, str(err)[:120], flush=True)
    return None


for year in range(FIRST, LAST + 1):
    target = CACHE / f"{year}.parquet"
    have = pd.read_parquet(target) if target.exists() else None
    res = earthaccess.search_data(short_name="GPM_3IMERGDF", version="07", temporal=(f"{year}-01-01", f"{year}-12-31"),
                                  bounding_box=(W, S, E, N))
    done = set(have.date.dt.strftime("%Y-%m-%d")) if have is not None else set()
    todo = [g for g in res if g["umm"]["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"][:10] not in done]
    if not todo:
        print(year, "complete, skipping", flush=True)
        continue
    with ThreadPoolExecutor(max_workers=6) as pool:
        parts = [d for d in pool.map(read, todo) if d is not None]
    df = pd.concat(([have] if have is not None else []) + parts).sort_values(["date", "lat", "lon"])
    df.to_parquet(target, index=False)
    print(f"{year}: {df.date.nunique()} of {len(res)} days", flush=True)

allp = pd.concat([pd.read_parquet(p) for p in sorted(CACHE.glob("*.parquet"))]).sort_values(["date", "lat", "lon"])
allp["precip_mm"] = allp.precip_mm.where(allp.precip_mm >= 0)  # fill values are negative
allp.to_parquet(PROC / "imerg_daily_2001_2025.parquet", index=False)
inside = allp[allp.lat.between(S - 0.05, N + 0.05) & allp.lon.between(W - 0.05, E + 0.05)]
area = inside.groupby("date").precip_mm.mean().to_frame()
area.to_parquet(PROC / "imerg_daily_area_mean.parquet")
print("cells:", allp.groupby(["lat", "lon"]).ngroups, "| inside:", inside.groupby(["lat", "lon"]).ngroups,
      "| days:", len(area), area.index.min().date(), "..", area.index.max().date())
