"""NASA POWER daily (MERRA-2 meteorology, 0.5 x 0.625 deg), community AG, UTC.

Live REST call (no login) with a disk cache; if the call fails (and POWER_MODE=auto) the local file
data/processed/power_daily_1981_2026.parquet is used, but only for areas whose centroid is inside the study area.
POWER cells are far larger than a field: the value is the cell that contains the area centroid.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path

import httpx
import pandas as pd

from ..areas import NAMED_AREAS, Area
from ..config import Settings
from ..variables import SourceVar
from .base import Fetched, NoData, ProviderError

log = logging.getLogger("climate-api.power")
TRANSPORT: httpx.BaseTransport | None = None  # tests inject a mock here
FIRST_DAY = date(1981, 1, 1)
CELL_LON, CELL_LAT = 0.625, 0.5
FILE = "power_daily_1981_2026.parquet"


@lru_cache(maxsize=2)
def _read(path: str, mtime_ns: int) -> pd.DataFrame:
    return pd.read_parquet(path)


class PowerProvider:
    name = "power"
    title = "NASA POWER daily agro-climatology (MERRA-2), community AG"
    native_resolution = "0.5° x 0.625° (~55 x 55 km)"
    reference = "NASA Langley Research Center POWER Project, https://power.larc.nasa.gov"

    def __init__(self, settings: Settings):
        self.s = settings

    # ---- public -------------------------------------------------------------------------------------------
    def fetch(self, var: SourceVar, area: Area, start: date, end: date) -> Fetched:
        mode, failure = self.s.power_mode, None
        if mode in ("live", "auto"):
            try:
                res = self._live(var, area, start, end)
                return self._with_area_note(res, area)
            except ProviderError as exc:
                if mode == "live":
                    raise
                failure = str(exc)
                log.warning("POWER live failed, trying local file: %s", exc)
        try:
            res = self._local(var, area, start, end)
        except (ProviderError, NoData) as exc:
            if failure:  # live was the real attempt: report both, as an error
                raise ProviderError(f"live: {failure}; local: {exc}") from None
            raise
        if failure:
            res.notes.append(f"live POWER call failed ({failure}); served from the local file")
        return self._with_area_note(res, area)

    # ---- live ---------------------------------------------------------------------------------------------
    def _live(self, var: SourceVar, area: Area, start: date, end: date) -> Fetched:
        s, e = max(start, FIRST_DAY), min(end, datetime.now(timezone.utc).date())
        if s > e:
            raise NoData(f"POWER daily data starts {FIRST_DAY}")
        lon, lat = round(area.lon, 3), round(area.lat, 3)
        key = f"{var.native}|{lon}|{lat}|{s}|{e}"
        payload, origin = self._cache_get(key), "cache"
        if payload is None:
            payload, origin = self._request(var.native, lon, lat, s, e), "live"
            self._cache_put(key, payload)
        fill = payload["header"].get("fill_value", -999.0)
        try:
            raw = payload["properties"]["parameter"][var.native]
            cell = payload["geometry"]["coordinates"][:2]
        except (KeyError, TypeError):
            raise ProviderError("unexpected POWER response shape") from None
        series = pd.Series(raw, dtype="float64").replace(fill, float("nan"))
        series.index = pd.to_datetime(series.index, format="%Y%m%d")
        series = series.sort_index() * var.factor
        if series.notna().sum() == 0:
            raise NoData("POWER returned only fill values for this period")
        return Fetched(series=series, origin=origin, n_cells=1,
                       method="value of the POWER cell containing the area centroid",
                       extra={"cell_center": [cell[0], cell[1]]})

    def _request(self, param: str, lon: float, lat: float, s: date, e: date) -> dict:
        params = {"parameters": param, "community": "AG", "longitude": lon, "latitude": lat,
                  "start": s.strftime("%Y%m%d"), "end": e.strftime("%Y%m%d"), "format": "JSON", "time-standard": "UTC"}
        last = "unknown error"
        for attempt in range(max(1, self.s.power_retries)):
            try:
                with httpx.Client(timeout=self.s.http_timeout, transport=TRANSPORT) as client:
                    r = client.get(self.s.power_url, params=params)
                if r.status_code in (429, 500, 502, 503, 504):
                    last = f"HTTP {r.status_code}"
                elif r.status_code != 200:
                    raise ProviderError(f"POWER HTTP {r.status_code}: {r.text[:200]}")
                else:
                    return r.json()
            except httpx.HTTPError as exc:
                last = f"{type(exc).__name__}: {exc}"
            except ValueError:
                raise ProviderError("POWER returned invalid JSON") from None
            if attempt + 1 < self.s.power_retries:
                time.sleep(2 ** attempt)
        raise ProviderError(f"POWER unreachable after {self.s.power_retries} tries ({last})")

    # ---- disk cache ---------------------------------------------------------------------------------------
    def _cache_file(self, key: str) -> Path:
        return self.s.cache_dir / "power" / (hashlib.sha1(key.encode()).hexdigest() + ".json")

    def _cache_get(self, key: str) -> dict | None:
        f = self._cache_file(key)
        try:
            if f.exists() and time.time() - f.stat().st_mtime < self.s.cache_ttl_hours * 3600:
                return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        return None

    def _cache_put(self, key: str, payload: dict) -> None:
        f = self._cache_file(key)
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(payload), encoding="utf-8")
        except OSError as exc:  # a read-only cache must never break a request
            log.warning("cannot write cache %s: %s", f, exc)

    # ---- local file ---------------------------------------------------------------------------------------
    def _local(self, var: SourceVar, area: Area, start: date, end: date) -> Fetched:
        w, s, e, n = NAMED_AREAS["study_area"]["bbox"]
        if not (w <= area.lon <= e and s <= area.lat <= n):
            raise NoData("local POWER file only covers the study area (area centroid is outside it)")
        path = self.s.data_dir / FILE
        try:
            df = _read(str(path), path.stat().st_mtime_ns)
        except FileNotFoundError:
            raise ProviderError(f"{FILE} not found in DATA_DIR") from None
        if var.native not in df.columns:
            raise ProviderError(f"{var.native} not in local POWER file")
        series = df.loc[pd.Timestamp(start):pd.Timestamp(end), var.native].astype("float64") * var.factor
        if series.notna().sum() == 0:
            raise NoData(f"local POWER file covers {df.index.min().date()}..{df.index.max().date()}")
        return Fetched(series=series, origin="local", n_cells=1,
                       method="value of the POWER cell containing the study-area centroid")

    @staticmethod
    def _with_area_note(res: Fetched, area: Area) -> Fetched:
        if (area.east - area.west) > CELL_LON or (area.north - area.south) > CELL_LAT:
            res.notes.append("area is larger than one POWER cell; the value describes only the cell at the centroid")
        return res
