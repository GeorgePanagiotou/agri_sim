"""GPM IMERG Late Run daily (GPM_3IMERGDL v07) for the days after IMERG Final ends, same 0.1 deg cells as
download_imerg_daily.py, through NASA GES DISC OPeNDAP (~600 bytes per day). Earthdata login from ~/_netrc.

IMERG Final arrives ~3.5 months late; the Late Run (~14 h latency) fills the gap up to yesterday. The products
differ in calibration: every file keeps its product name, and downstream code must not mix them silently.

Outputs
- data/raw/imerg_late/<YYYY>_Q<n>.parquet   date, lat, lon, precip_mm per calendar quarter (re-run refreshes the
  quarter that is still running)

    ..\\.venv\\Scripts\\python.exe data_prep\\download_imerg_late.py [start YYYY-MM-DD] [end YYYY-MM-DD]
Default: the day after the last IMERG Final day in data/raw/imerg_daily/ .. yesterday.
"""
import re
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor

import earthaccess
import pandas as pd

from config import RAW, STUDY_AREA

warnings.filterwarnings("ignore")
W, E, S, N = STUDY_AREA
PAD = 0.1
LON0, LON1 = int(round((W - PAD + 179.95) / 0.1)), int(round((E + PAD + 179.95) / 0.1))
LAT0, LAT1 = int(round((S - PAD + 89.95) / 0.1)), int(round((N + PAD + 89.95) / 0.1))
CE = f"precipitation[0:1:0][{LON0}:1:{LON1}][{LAT0}:1:{LAT1}]"
FINAL = RAW / "imerg_daily"
OUT = RAW / "imerg_late"


def default_start() -> pd.Timestamp:
    files = sorted(FINAL.glob("[12][0-9][0-9][0-9].parquet"))
    if not files:
        raise SystemExit("No IMERG Final cache; run download_imerg_daily.py first (or pass a start date)")
    last = pd.to_datetime(pd.read_parquet(files[-1], columns=["date"]).date).max()
    return last.normalize() + pd.Timedelta(days=1)


def read(session, granule):
    day = pd.Timestamp(granule["umm"]["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"][:10])
    link = next(u for u in granule.data_links() if u.endswith(".nc4"))
    url = f"https://gpm1.gesdisc.eosdis.nasa.gov/opendap/{link.split('/data/', 1)[1]}.ascii?{CE}"
    for attempt in range(6):
        try:
            r = session.get(url, timeout=60)
            r.raise_for_status()
            lines = r.text.splitlines()
            lats = [float(v) for v in next(l for l in lines if l.startswith("precipitation.lat")).split(",")[1:]]
            rows = []
            for line in lines:
                m = re.match(r"precipitation\.precipitation\[.*\]\[precipitation\.lon=([-\d.]+)\],(.*)", line)
                if m:
                    rows += [(day, lat, float(m.group(1)), float(v)) for lat, v in zip(lats, m.group(2).split(","))]
            if rows:
                return pd.DataFrame(rows, columns=["date", "lat", "lon", "precip_mm"])
            raise ValueError("no rows parsed")
        except Exception as err:  # noqa: BLE001
            if attempt == 5:
                print(f"  {day.date()}: failed ({type(err).__name__})", flush=True)
                return None
            time.sleep(2 ** attempt)


def main():
    start = pd.Timestamp(sys.argv[1]) if len(sys.argv) > 1 else default_start()
    end = pd.Timestamp(sys.argv[2]) if len(sys.argv) > 2 else pd.Timestamp.today().normalize() - pd.Timedelta(days=1)
    if start > end:
        print("Nothing to do: IMERG Final already covers", start.date())
        return
    earthaccess.login(strategy="netrc")
    session = earthaccess.get_requests_https_session()
    granules = earthaccess.search_data(short_name="GPM_3IMERGDL", version="07",
                                       temporal=(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")))
    print(f"IMERG Late: {len(granules)} days in CMR for {start.date()} .. {end.date()}", flush=True)
    with ThreadPoolExecutor(6) as pool:
        frames = [f for f in pool.map(lambda g: read(session, g), granules) if f is not None]
    if not frames:
        raise SystemExit("No IMERG Late data read")
    data = pd.concat(frames).drop_duplicates(["date", "lat", "lon"]).sort_values(["date", "lat", "lon"])
    data.loc[data.precip_mm < 0, "precip_mm"] = float("nan")
    OUT.mkdir(parents=True, exist_ok=True)
    for (year, q), part in data.groupby([data.date.dt.year, data.date.dt.quarter]):
        target = OUT / f"{year}_Q{q}.parquet"
        if target.exists():  # merge with what is there (a running quarter grows)
            old = pd.read_parquet(target)
            old["date"] = pd.to_datetime(old["date"])
            part = pd.concat([old, part]).drop_duplicates(["date", "lat", "lon"], keep="last")
        part.sort_values(["date", "lat", "lon"]).to_parquet(target, index=False)
        print(f"  {target.name}: {part.date.nunique()} days, {len(part[['lat', 'lon']].drop_duplicates())} cells")


if __name__ == "__main__":
    main()
