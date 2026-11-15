"""Runtime settings, read from environment variables (see service/README.md)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _find_repo_root() -> Path:
    """Local runs: walk up from this file and from the current folder to the folder with configs/areas."""
    for start in (Path(__file__).resolve().parent, Path.cwd().resolve()):
        for folder in (start, *start.parents):
            if (folder / "configs" / "areas").is_dir():
                return folder
    return Path.cwd()  # nothing found: /health shows no areas


@dataclass(frozen=True)
class Settings:
    repo_root: Path        # folder with configs/areas/*.yaml and the data roots they name (data/, data/areas/...)
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
        repo_root=Path(env("REPO_ROOT")) if env("REPO_ROOT") else _find_repo_root(),
        cache_dir=Path(env("CACHE_DIR", str(Path.home() / ".agrisim_climate_cache"))),
        power_mode=mode,
        power_url=env("POWER_URL", "https://power.larc.nasa.gov/api/temporal/daily/point"),
        power_retries=int(env("POWER_RETRIES", "3")),
        http_timeout=float(env("HTTP_TIMEOUT", "60")),
        cache_ttl_hours=float(env("CACHE_TTL_HOURS", "24")),
        max_days=int(env("MAX_DAYS", str(366 * 50))),
    )
