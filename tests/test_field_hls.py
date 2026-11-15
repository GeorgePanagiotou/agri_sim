"""Offline tests for field-sized HLS coverage and acquisition wiring."""
from datetime import date
import csv
import json
from pathlib import Path

import numpy as np
import pytest
from affine import Affine
from rasterio.warp import transform

from agrisim.data_sources.field_hls import (
    archive_covers_field, candidate_archives, field_hls_plan,
    recent_season_periods,
)
from agrisim.data_sources import download_evia_hls as dl


def polygon(w=23.17, s=38.89, e=23.171, n=38.891):
    return {"type": "Polygon", "coordinates": [[
        [w, s], [e, s], [e, n], [w, n], [w, s]
    ]]}


def test_window_covers_single_field_without_changing_pilot():
    p = field_hls_plan(polygon(), 2)
    assert p.site.name.startswith("field_2_")
    assert p.site.size <= 129
    assert p.site.size % 2 == 1
    assert 0 < p.area_hectares < 10
    assert field_hls_plan(polygon(), 2) == p
    assert p.site.name != "evia_pilot"


def test_editing_polygon_gets_new_cache_identifier():
    old = field_hls_plan(polygon(), 2)
    changed = field_hls_plan(polygon(e=23.1711), 2)
    assert old.site.name != changed.site.name


def test_oversized_boundary_is_rejected_instead_of_partially_sampled():
    with pytest.raises(ValueError, match="multi-window mosaic"):
        field_hls_plan(polygon(w=23.1, s=38.85, e=23.2, n=38.95), 2)


def test_periods_stop_on_as_of_and_never_overlap():
    periods = recent_season_periods(date(2026, 11, 15))
    assert periods == [
        ("2023-09-01", "2024-05-31"),
        ("2024-09-01", "2025-05-31"),
        ("2025-09-01", "2026-05-31"),
        ("2026-09-01", "2026-11-15"),
    ]
    assert recent_season_periods(date(2026, 7, 9), count=1) == [
        ("2025-09-01", "2026-05-31")
    ]


def test_archive_lookup_prefers_exact_field_not_unrelated_pilot(tmp_path):
    base = tmp_path / "evia_sowing" / "hls_batches"
    for relative in (
        "20261114T120000Z/evia_pilot/hls/field_context.npz",
        "20261113T120000Z/field_2_abc/hls/field_context.npz",
        "20261115T120000Z.partial/field_2_abc/hls/field_context.npz",
    ):
        loc = base / relative
        loc.parent.mkdir(parents=True)
        loc.write_bytes(b"placeholder")
    paths = list(candidate_archives(tmp_path, "field_2_abc"))
    assert len(paths) == 2
    assert paths[0].parent.parent.name == "field_2_abc"
    assert paths[1].parent.parent.name == "evia_pilot"


def test_complete_polygon_coverage_against_actual_archive_grid(tmp_path):
    p = field_hls_plan(polygon(), 2)
    zone = int((p.site.lon + 180) // 6) + 1
    crs = f"EPSG:{32600 + zone}"
    xx, yy = transform("EPSG:4326", crs, [p.site.lon], [p.site.lat])
    pix = p.site.size
    # Synthetic dataset with the planned centre and its requested native grid.
    tr = Affine(30, 0, xx[0] - pix * 15, 0, -30, yy[0] + pix * 15)
    path = tmp_path / "field_context.npz"
    np.savez_compressed(path, candidate_mask=np.zeros((pix, pix), bool),
                        crs=crs, transform=np.array(tuple(tr)[:6]))
    assert archive_covers_field(path, polygon())
    assert not archive_covers_field(path, polygon(w=23.20, e=23.201))


def test_collect_wrapper_passes_boundary_and_one_row_per_season(monkeypatch):
    calls = []

    def fake_collect(fields_csv, **kwargs):
        with open(fields_csv, newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        parcels = json.loads(Path(kwargs["parcels"]).read_text(encoding="utf-8"))
        calls.append((rows, parcels, kwargs))
        return Path("mock-batch")

    monkeypatch.setattr(dl, "collect_fields", fake_collect)
    output = dl.collect_saved_boundary(polygon(), 2, as_of="2025-12-06", seasons=4,
                                       max_dates=12, workers=1, plan_only=True)
    assert output == Path("mock-batch")
    rows, parcels, kwargs = calls[0]
    assert len(rows) == 4
    assert rows[-1]["end_date"] == "2025-12-06"
    assert rows[0]["field_id"] == parcels["features"][0]["properties"]["field_id"]
    assert kwargs["max_dates"] == 12 and kwargs["workers"] == 1
    assert kwargs["plan_only"]
