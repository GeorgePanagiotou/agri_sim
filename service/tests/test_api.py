"""Offline API tests: a tiny fake repo (two areas, IMERG Final + Late + factors, POWER) and a mocked POWER API.
Run from service/:  python -m pytest -q"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import main
from app.providers import power

CELLS = [(38.85, 23.35), (38.85, 23.45), (38.95, 23.45)]


def imerg(days: pd.DatetimeIndex, value: float) -> pd.DataFrame:
    return pd.DataFrame([(d, lat, lon, value) for d in days for lat, lon in CELLS],
                        columns=["date", "lat", "lon", "precip_mm"])


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch) -> Path:
    areas = tmp_path / "configs" / "areas"
    areas.mkdir(parents=True)
    (areas / "demo.yaml").write_text(
        "label: Demo area\nstudy_area: [23.30, 23.50, 38.80, 39.00]\naoi: [23.0, 23.8, 38.6, 39.2]\n"
        "pilot: [23.40, 38.90]\ndata_root: data\n", encoding="utf-8")
    (areas / "other.yaml").write_text(
        "label: Other\nstudy_area: [24.75, 24.95, 35.0, 35.1]\n", encoding="utf-8")   # no data prepared
    (areas / "Bad Name.yaml").write_text("study_area: [0, 1, 0, 1]\n", encoding="utf-8")  # ignored
    proc = tmp_path / "data" / "processed"
    proc.mkdir(parents=True)
    imerg(pd.date_range("2025-09-01", "2025-09-30"), 2.0).to_parquet(proc / "imerg_daily_2001_2025.parquet")
    # Late overlaps Final on 25-30 Sep (Final must win there), then fills Oct
    imerg(pd.date_range("2025-09-25", "2025-10-31"), 10.0).to_parquet(proc / "imerg_late_daily.parquet")
    pd.DataFrame({"month": range(1, 13), "factor": [0.5] * 12}).to_csv(proc / "imerg_late_to_final.csv", index=False)
    idx = pd.date_range("2025-09-01", "2025-10-31", name="date")
    pd.DataFrame({"T2M": 20.0, "PRECTOTCORR": 1.0}, index=idx).to_parquet(proc / "power_daily_1981_2026.parquet")
    monkeypatch.setenv("REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("POWER_RETRIES", "1")
    return tmp_path


@pytest.fixture()
def client(repo):
    return TestClient(main.app)


def test_areas_come_from_the_registry(client):
    names = client.get("/v1/areas").json()
    assert {"demo", "demo_aoi", "demo_pilot", "other", "other_pilot"} <= set(names)
    assert "other_aoi" not in names and not any("bad" in n.lower() for n in names)
    assert names["demo"]["bbox"] == [23.30, 38.80, 23.50, 39.00]          # west, south, east, north
    assert names["demo"]["local_files"]["imerg_late_daily.parquet"] is True
    assert names["other"]["local_files"]["imerg_daily_2001_2025.parquet"] is False
    assert "study_area" not in names                                       # legacy aliases only with an evia area


def test_new_area_appears_without_restart(client, repo):
    (repo / "configs" / "areas" / "fresh.yaml").write_text("study_area: [10, 10.2, 45, 45.1]\n", encoding="utf-8")
    assert "fresh" in client.get("/v1/areas").json()


def test_imerg_final_then_scaled_late(client):
    r = client.get("/v1/series/precipitation", params={"area": "demo", "start": "2025-09-28", "end": "2025-10-02",
                                                       "sources": "imerg"}).json()
    values = {row["time"]: row["value"] for row in r["data"]}
    assert values["2025-09-28"] == 2.0 and values["2025-09-30"] == 2.0     # Final wins on overlap days
    assert values["2025-10-01"] == 5.0                                     # Late 10 mm x factor 0.5
    src = r["sources"]["imerg"]
    assert src["final_until"] == "2025-09-30" and src["late_days"] == 2
    assert any("Late Run" in n and "scaled" in n for n in src["notes"])


def test_monthly_sum_needs_complete_month(client):
    r = client.get("/v1/series/precipitation", params={"area": "demo", "start": "2025-09-15", "end": "2025-10-31",
                                                       "sources": "imerg", "aggregate": "monthly"}).json()
    values = {row["time"]: row["value"] for row in r["data"]}
    assert values["2025-09"] is None                                       # only half of September requested
    assert values["2025-10"] == pytest.approx(31 * 5.0)


def test_bbox_inside_a_prepared_area_uses_its_files(client):
    r = client.get("/v1/series/precipitation", params={"bbox": "23.42,38.84,23.46,38.86", "start": "2025-09-01",
                                                       "end": "2025-09-02", "sources": "imerg"}).json()
    assert r["area"]["local_data_from"] == "demo"
    assert r["sources"]["imerg"]["n_cells"] == 1


def test_location_outside_every_area_has_no_imerg(client):
    r = client.get("/v1/series/precipitation", params={"lon": 0.5, "lat": 0.5, "start": "2025-09-01",
                                                       "end": "2025-09-02", "sources": "imerg"})
    assert r.status_code == 404
    assert r.json()["detail"]["sources"]["imerg"]["status"] == "no_data"


def test_unprepared_area_reports_missing_files(client):
    r = client.get("/v1/series/precipitation", params={"area": "other", "start": "2025-09-01",
                                                       "end": "2025-09-02", "sources": "imerg"})
    assert r.status_code == 502 and "not found" in r.json()["detail"]["sources"]["imerg"]["detail"]


def test_power_live_with_mock(client, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["parameters"] == "T2M"
        return httpx.Response(200, json={"header": {"fill_value": -999.0}, "geometry": {"coordinates": [23.4, 38.9, 0]},
                                         "properties": {"parameter": {"T2M": {"20250901": 21.5, "20250902": -999.0}}}})
    monkeypatch.setattr(power, "TRANSPORT", httpx.MockTransport(handler))
    monkeypatch.setenv("POWER_MODE", "live")
    r = client.get("/v1/series/temperature_mean", params={"area": "demo", "start": "2025-09-01", "end": "2025-09-02"}).json()
    assert [row["value"] for row in r["data"]] == [21.5, None]             # fill value -> null, never 0
    assert r["sources"]["power"]["origin"] == "live"


def test_power_falls_back_to_the_area_file(client, monkeypatch):
    monkeypatch.setattr(power, "TRANSPORT", httpx.MockTransport(lambda req: httpx.Response(503)))
    monkeypatch.setenv("POWER_MODE", "auto")
    r = client.get("/v1/series/temperature_mean", params={"area": "demo_pilot", "start": "2025-09-01",
                                                          "end": "2025-09-02"}).json()
    assert [row["value"] for row in r["data"]] == [20.0, 20.0]
    assert r["sources"]["power"]["origin"] == "local"
    assert any("live POWER call failed" in n for n in r["sources"]["power"]["notes"])


def test_health_lists_areas(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["areas"]["demo"]["power_daily_*.parquet"] is True
