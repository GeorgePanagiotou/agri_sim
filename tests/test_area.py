"""Offline tests for study-area selection (configs/areas/*.yaml) and the prepare_area plan."""
import pytest

from agrisim import area as ar
from agrisim.pipelines import prepare_area as pa


def test_utm_zone_from_centre():
    assert ar.utm_epsg(23.41, 38.85) == 32634     # North Evia
    assert ar.utm_epsg(24.85, 35.05) == 32635     # Crete (Messara) is one zone east
    assert ar.utm_epsg(-58.4, -34.6) == 32721     # southern hemisphere
    with pytest.raises(ValueError):
        ar.utm_epsg(10, 85)


def test_evia_keeps_original_paths_and_grid():
    a = ar.load("evia")
    assert a.crs == "EPSG:32634"
    assert a.data_root == ar.REPO / "data" and a.outputs == ar.REPO / "outputs"
    assert a.study_area == (23.32, 23.50, 38.75, 38.95) and a.pilot == (23.43232, 38.75920)
    assert a.fire["start"] == "2021-08-03"


def test_create_and_load_new_area(tmp_path, monkeypatch):
    monkeypatch.setattr(ar, "AREAS_DIR", tmp_path)
    ar.create("testplain", (24.75, 24.95, 35.00, 35.10), label="Test plain")
    a = ar.load("testplain")
    assert a.crs == "EPSG:32635"
    assert a.data_root == ar.REPO / "data" / "areas" / "testplain"
    assert a.pilot == (24.85, 35.05) and a.fire is None
    with pytest.raises(FileExistsError):
        ar.create("testplain", (24.75, 24.95, 35.00, 35.10))


@pytest.mark.parametrize("box", [(24.95, 24.75, 35.0, 35.1), (20.0, 22.0, 35.0, 35.1), (24.7, 24.9, 35.2, 35.1)])
def test_bad_boxes_rejected(tmp_path, monkeypatch, box):
    monkeypatch.setattr(ar, "AREAS_DIR", tmp_path)
    with pytest.raises(ValueError):
        ar.create("bad", box)


def test_bad_names_rejected():
    for name in ("Evia", "1abc", "a b", "../x"):
        with pytest.raises(ValueError):
            ar.load(name)


def test_env_variable_selects_area(tmp_path, monkeypatch):
    monkeypatch.setattr(ar, "AREAS_DIR", tmp_path)
    ar.create("envtest", (24.75, 24.95, 35.00, 35.10))
    monkeypatch.setenv(ar.ENV, "envtest")
    assert ar.load().name == "envtest"


def test_prepare_area_plan_is_complete_and_ordered():
    s = pa.steps(ar.load("evia"), 1997, 2025, 2025)
    assert list(s) == pa.STEP_ORDER
    assert s["harmonization"]["cmd"] is None
    assert all(spec["cmd"] for k, spec in s.items() if k != "harmonization")
    assert pa.last_month_end(pa.date(2026, 11, 14)) == pa.date(2026, 10, 31)
