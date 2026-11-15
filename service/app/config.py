"""Runtime settings, read from environment variables (see service/README.md)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path



def _find_data_dir() -> Path:
    """Local runs: walk up from this file and from the current folder until a data/processed with our files shows up."""
    for start in (Path(__file__).resolve().parent, Path.cwd().resolve()):
        for folder in (start, *start.parents):
            cand = folder / "data" / "processed"
            if (cand / "imerg_daily_2001_2025.parquet").exists() or (cand / "power_daily_1981_2026.parquet").exists():
                return cand
    return Path("data/processed")  # nothing found: /health will show the files as missing


@dataclass(frozen=True)
class Settings:
    data_dir: Path         # folder with the harmonized parquet files (data/processed)
    cache_dir: Path        # disk cache for live POWER calls
    power_mode: str        # auto = live, fall back to local file | live | local
    power_url: str
    power_retries: int
    http_timeout: float
    cache_ttl_hours: float
    max_days: int          # longest period a single request may ask for


def get_settings() -> Settings:
    env = os.environ.get
    mode = env("POWER_MODE", "auto").lower()
    if mode not in {"auto", "live", "local"}:
        raise ValueError(f"POWER_MODE must be auto, live or local, got {mode!r}")
    return Settings(
        data_dir=Path(env("DATA_DIR")) if env("DATA_DIR") else _find_data_dir(),
        cache_dir=Path(env("CACHE_DIR", str(Path.home() / ".agrisim_climate_cache"))),
        power_mode=mode,
        power_url=env("POWER_URL", "https://power.larc.nasa.gov/api/temporal/daily/point"),
        power_retries=int(env("POWER_RETRIES", "3")),
        http_timeout=float(env("HTTP_TIMEOUT", "60")),
        cache_ttl_hours=float(env("CACHE_TTL_HOURS", "24")),
        max_days=int(env("MAX_DAYS", str(366 * 50))),
    )