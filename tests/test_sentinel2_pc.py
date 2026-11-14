"""Offline tests for the Planetary Computer Sentinel-2 L2A downloader (no network)."""
from types import SimpleNamespace

import numpy as np
from shapely.geometry import box, mapping

from agrisim.data_sources import download_sentinel2_pc as s2


def test_harmonize_applies_offset_only_from_baseline_04():
    dn = np.array([0, 500, 1000, 3000], dtype="uint16")
    old = s2.harmonize(dn, 3.01)
    new = s2.harmonize(dn, 5.11)
    assert np.allclose(old, [0, 0.05, 0.1, 0.3])
    assert np.allclose(new, [0, 0, 0, 0.2])          # (DN - 1000) / 10000, clipped at 0; DN 0 = no data


def item(id_, day, cloud, geom):
    return SimpleNamespace(id=id_, geometry=mapping(geom),
                           properties={"datetime": f"{day}T09:20:00Z", "eo:cloud_cover": cloud})


def test_select_items_one_per_date_full_cover_then_least_cloud():
    _, _, window = s2.window_geometry(23.43232, 38.75920, 990)
    big = box(23.0, 38.5, 24.0, 39.0)
    edge = box(23.0, 38.5, 23.4325, 39.0)            # cuts through the window
    items = [item("a", "2024-11-01", 30, big), item("b", "2024-11-01", 5, big),
             item("c", "2024-11-06", 1, edge), item("d", "2024-11-11", 20, big)]
    chosen = s2.select_items(items, window)
    assert [i.id for i in chosen] == ["b", "d"]
