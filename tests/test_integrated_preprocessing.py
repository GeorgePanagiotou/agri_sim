"""Offline regression tests for reproducible preprocessing CLI functions."""
from pathlib import Path
import json

import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin

from agrisim.preprocessing.sentinel2_aligned import extract_one, reference_mask
from agrisim.preprocessing.srtm_terrain import terrain_layers
from agrisim.features.ecostress import timestamp_from_name, extract as extract_ecostress
from agrisim.pipelines.prepare_multisource import discover, run


def fake_hls_batch(root: Path) -> Path:
    batch = root / 'data/processed/evia_sowing/hls_batches/20261114T003254Z-test'
    path = batch / 'evia_pilot/hls/field_context.npz'
    path.parent.mkdir(parents=True)
    mask = np.zeros((33, 33), dtype=np.uint8)
    mask[15:18, 15:18] = 1
    np.savez(path, candidate_mask=mask, transform=np.array([30, 0, 710850, 0, -30, 4293360], dtype=float),
             crs=rasterio.crs.CRS.from_epsg(32634).to_wkt())
    return batch


def create_sentinel(tif: Path, *, cloudy: bool = False) -> None:
    tif.parent.mkdir(parents=True, exist_ok=True)
    data = np.zeros((5, 99, 99), dtype='float32')
    data[0] = 0.2
    data[1] = 0.1
    data[2] = 0.5
    data[3] = 9 if cloudy else 4
    data[4] = 1
    with rasterio.open(tif, 'w', driver='GTiff', width=99, height=99, count=5,
                       dtype='float32', crs='EPSG:32634',
                       transform=from_origin(710850, 4293360, 10, 10)) as ds:
        ds.write(data)
    tif.with_suffix('.json').write_text(json.dumps({
        'dataset': 'sentinel-2-l2a', 'field_id': 'evia_pilot',
        'start_utc': '2024-09-04', 'end_utc': '2024-09-04',
        'is_temporal_mosaic': False,
        'band_order': ['B03_green', 'B04_red', 'B08_nir', 'SCL', 'dataMask'],
    }))


def test_sentinel2_reuses_same_nine_hls_pixels(tmp_path):
    batch = fake_hls_batch(tmp_path)
    tif = tmp_path / 's2_l2a_2024_09_04.tif'
    create_sentinel(tif)
    from agrisim.preprocessing.sentinel2_aligned import extract_all
    out = extract_all(tmp_path, batch)
    assert len(out) == 1
    assert out.iloc[0].footprint_pixels == 81
    assert out.iloc[0].valid_pixels == 81
    assert out.iloc[0].ndvi_median == pytest.approx(2/3)
    assert out.iloc[0].evi2_median == pytest.approx(2.5 * .4 / (.5 + 2.4*.1 + 1))


def test_sentinel2_cloud_exclusion_and_mosaic_rejection(tmp_path):
    batch = fake_hls_batch(tmp_path)
    mask, transform, crs = reference_mask(batch)
    tif = tmp_path / 's2_l2a_2024_09_04.tif'
    create_sentinel(tif, cloudy=True)
    out = extract_one(tif, mask, transform, crs)
    assert out['valid_pixels'] == 0
    assert np.isnan(out['ndvi_median'])
    meta = json.loads(tif.with_suffix('.json').read_text())
    meta['is_temporal_mosaic'] = True
    tif.with_suffix('.json').write_text(json.dumps(meta))
    with pytest.raises(ValueError, match='mosaics'):
        extract_one(tif, mask, transform, crs)


def test_terrain_slope_and_downslope_aspect():
    # Height increases east, so the downhill bearing is west (270 degrees).
    elevation = np.tile(np.arange(33, dtype='float32') * 3, (33, 1))
    slope, aspect = terrain_layers(elevation, 30.0, 30.0)
    assert np.median(slope) == pytest.approx(np.degrees(np.arctan(.1)), abs=.001)
    assert np.median(aspect) == pytest.approx(270.0)


def test_ecostress_overpass_timestamp_and_native_units(tmp_path):
    batch = fake_hls_batch(tmp_path)
    assert timestamp_from_name('ECO_L3T_JET.002_ETdaily_doy2024278090958_aid0001_34N.tif').date().isoformat() == '2024-10-04'
    task = tmp_path / 'data/raw/appeears/agrisim_ecostress_et_20240901_20241031'
    task.mkdir(parents=True)
    (task / 'nasa_request.json').write_text(json.dumps({'key': 'ecostress_et'}))
    tif = task / 'ECO_L3T_JET.002_ETdaily_doy2024278090958_aid0001_34N.tif'
    with rasterio.open(tif, 'w', driver='GTiff', width=33, height=33, count=1,
                       dtype='float32', crs='EPSG:32634',
                       transform=from_origin(710850, 4293360, 30, 30), nodata=np.nan) as ds:
        ds.write(np.full((1,33,33), 97., dtype='float32'))
        ds.update_tags(units='W/m²', scale_factor='1', add_offset='0')
    result = extract_ecostress(task.parent, batch)
    assert len(result) == 1
    assert result.iloc[0]['date_utc'] == '2024-10-04'
    assert result.iloc[0]['reported_units'] == 'W/m²'
    assert result.iloc[0]['et_raw_median'] == pytest.approx(97.)
    assert not result.iloc[0]['cloud_qa_available']


def test_automatic_plan_requires_no_network(tmp_path):
    batch = fake_hls_batch(tmp_path)
    data = tmp_path / 'data'
    (data / 'raw/srtm').mkdir(parents=True)
    (data / 'raw/srtm/N38E023.SRTMGL1.hgt.zip').touch()
    (data / 'raw/fao_gaez').mkdir(parents=True)
    (data / 'raw/imerg_daily').mkdir(parents=True)
    (data / 'raw/imerg_daily/2020.parquet').touch()
    (data / 'processed/evia_sowing/smap').mkdir(parents=True)
    (data / 'processed/evia_sowing/smap/smap_daily.csv').touch()
    create_sentinel(data / 'raw/sentinel2/s2_l2a_2024_09_04.tif')
    summary = run(plan=True, repo=tmp_path)
    assert summary['s2_tifs'] == 1
    assert summary['hls_batch'] == str(batch)
    assert not (data / 'processed/features/environment_multisource_daily.parquet').exists()
