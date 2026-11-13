"""Offline smoke tests; no service calls or credentials required."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agrisim import config
from agrisim.data_sources.download_appeears import REGISTRY, params_for, split_params
from agrisim.data_sources.download_power import PARAMETERS, extract
from agrisim.data_sources.download_sentinel2 import BAND_ORDER, payload
from agrisim.data_sources.download_evia_hls import BANDS
from agrisim.data_sources.hls_fields import Site


def test_reproducible_project_paths():
    assert config.REPO == ROOT
    assert config.RAW == ROOT / "data/raw"
    assert config.PROC == ROOT / "data/processed"


def test_source_manifest_matches_selected_scripts():
    manifest = json.loads((ROOT / "configs/sources.json").read_text(encoding="utf-8"))
    for dataset in manifest["selected_datasets"]:
        assert (ROOT / "src/agrisim" / dataset["script"].replace("data_prep/", "data_sources/")).is_file()
    assert all("soilgrids" not in x["script"].lower() for x in manifest["selected_datasets"])
    assert all("grace" not in x["script"].lower() for x in manifest["selected_datasets"])


def test_hls_channels_and_pilot_validation():
    assert BANDS == ("B03", "B04", "B05", "Fmask")
    site = Site("evia_pilot", config.SOWING_LON, config.SOWING_LAT, 33)
    assert site.directory(config.RAW) == config.RAW / "evia_sowing/hls"
    with pytest.raises(ValueError):
        Site("bad", 23.4, 38.7, 4)


def test_power_json_parser_preserves_missing():
    data = {
        "header": {"fill_value": -999},
        "properties": {"parameter": {
            "T2M": {"20241001": 12.5, "20241002": -999},
            "GWETTOP": {"20241001": 0.42, "20241002": 0.51},
        }},
    }
    out = extract(data, "daily")
    assert out.index.name == "date"
    assert out.loc[pd.Timestamp("2024-10-01"), "T2M"] == 12.5
    assert pd.isna(out.loc[pd.Timestamp("2024-10-02"), "T2M"])
    assert "GWETTOP" in PARAMETERS["daily"]


def test_appeears_product_allow_list():
    assert set(REGISTRY) == {"modis_ndvi", "modis_et", "modis_lst", "smap_surface", "smap_l4", "ecostress_et"}
    result = params_for("modis_ndvi", "2023-09-01", "2023-09-30")
    assert set(x["product"] for x in result["layers"]) == {"MOD13Q1.061"}
    assert result["geo"]["features"][0]["geometry"]["type"] == "Polygon"
    with pytest.raises(ValueError):
        params_for("soilgrids", "2023-09-01", "2023-09-30")


def test_appeears_split_preserves_date_coverage():
    result = params_for("smap_l4", "2024-01-01", "2024-01-10")
    a, b = split_params(result)
    assert a["dates"][0]["startDate"] == "01-01-2024"
    assert b["dates"][0]["endDate"] == "01-10-2024"
    assert a["dates"][0]["endDate"] == "01-05-2024"
    assert b["dates"][0]["startDate"] == "01-06-2024"


def test_esa_sentinel_bands_and_bounds():
    a = payload(23.43232, 38.75920, "2024-12-08", "2024-12-08", 990, 10, 30)
    assert a["input"]["data"][0]["type"] == "sentinel-2-l2a"
    assert a["output"]["width"] == 99
    assert a["input"]["bounds"]["properties"]["crs"].endswith("32634")
    assert BAND_ORDER == ["B03_green", "B04_red", "B08_nir", "SCL", "dataMask"]
    with pytest.raises(ValueError):
        payload(23.4, 38.7, "2024-12-09", "2024-12-08", 990, 10, 30)
    with pytest.raises(ValueError):
        payload(23.4, 38.7, "2024-12-08", "2024-12-08", 995, 10, 30)


def test_example_field_windows_valid():
    path = ROOT / "data/reference/evia_hls_fields.csv"
    frame = pd.read_csv(path)
    assert len(frame) == 2
    assert frame.field_id.eq("evia_pilot").all()
    assert frame.start_date.lt(frame.end_date).all()
