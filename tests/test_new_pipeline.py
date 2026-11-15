"""Offline contract tests for the non-CNN pipeline."""
from pathlib import Path
from tempfile import TemporaryDirectory
import numpy as np
import pandas as pd
import pytest
from agrisim.timeseries.vegetation_indices import vegetation_indices,stats,read_hls_batch
from agrisim.timeseries.greenup import analyze_group
from agrisim.features.build_features import environmental_daily,candidate_sowing_dates
from agrisim.decision_engine.sowing_rules import recommend_sowing
from agrisim.decision_engine.ranking import rank_rotations
from agrisim.decision_engine.risk_assessment import risk_assessment
from agrisim.data_sources.download_fao_gaez import validate_source
from agrisim.data_sources.download_era5_land import request


def test_ndvi_evi2_physical_reflectance():
    g=np.array([[0.1,0.1]])
    r=np.array([[0.1,0.1]])
    n=np.array([[0.5,0.5]])
    nd,ev,sa=vegetation_indices(g,r,n,np.array([[True,False]]))
    assert nd[0,0]==pytest.approx(2/3)
    assert ev[0,0]==pytest.approx(2.5*0.4/(.5+.24+1))
    assert np.isnan(nd[0,1]) and np.isnan(ev[0,1])
    assert sa[0,0]>0


def test_vegetation_rejects_unapproved_hls_granule():
    with TemporaryDirectory() as t:
        f=Path(t)/'field01/hls';f.mkdir(parents=True)
        np.savez_compressed(f/'field_context.npz',
            bands=np.array(['B03','B04','B05']), dates=np.array(['2024-11-01']),
            granules=np.array(['FAKE.NOT.NASA']),reflectance=np.ones((1,3,9,9),dtype='float32'),
            clear=np.ones((1,9,9),bool),candidate_mask=np.ones((9,9),bool))
        with pytest.raises(ValueError,match='Only NASA'):
            read_hls_batch(Path(t))


def test_spectral_greenup_detects_interval_and_rejects_small_group():
    dates=pd.date_range('2024-10-01',periods=7,freq='12D')
    vals=[.11,.12,.14,.41,.47,.50,.52]
    ev=[.09,.10,.11,.34,.38,.40,.41]
    df=pd.DataFrame({'field_id':'demo','season':'2024-2025','source':'NASA_HLSL30_v2',
       'date_utc':dates.strftime('%Y-%m-%d'),'valid_pixels':9,'clear_fraction':1.0,
       'ndvi_median':vals,'evi2_median':ev})
    out=analyze_group(df)
    assert out['status']=='retrospective_spectral_greenup'
    assert out['first_high_date']=='2024-11-06'
    assert out['last_low_date']=='2024-10-25'
    assert analyze_group(df.iloc[:3])['status']=='insufficient_clear_dates'


def test_as_of_weather_no_future_leakage():
    with TemporaryDirectory() as d:
        d=Path(d)
        idx=pd.date_range('2020-01-01','2020-02-05')
        pd.DataFrame({'T2M':12.,'GWETTOP':0.4,'GWETROOT':0.5},index=idx).rename_axis('date').to_csv(d/'power.csv')
        rain=pd.DataFrame({'date':idx,'precip_mm':1.0})
        rain.loc[rain.date==pd.Timestamp('2020-01-15'),'precip_mm']=100
        rain.to_csv(d/'gpm.csv',index=False)
        env=environmental_daily(d/'power.csv',d/'gpm.csv')
        m=env.set_index('date')
        assert m.loc['2020-01-15','rain_prior_7d_mm']==pytest.approx(7.)
        assert m.loc['2020-01-16','rain_prior_7d_mm']==pytest.approx(106.)
        assert m.loc['2020-01-01','rain_prior_7d_mm']!=m.loc['2020-01-01','rain_prior_7d_mm'] # missing


def test_sowing_and_risk_missing_values():
    d=pd.DataFrame({'rain_prior_7d_mm':[1.,40.,np.nan,15.],
        'rain_prior_7d_max_mm':[1.,30.,np.nan,4.],
        'temp_prior_7d_c':[12.,12.,10.,12.],
        'power_wetness_prior_7d':[.1,.4,.3,.5],
        'power_wetness_historical_p20':[.2,.2,.2,.2]})
    r=recommend_sowing(d)
    assert r.sowing_screen.tolist()==['field_check_dry_seedbed','field_check_after_heavy_rain','insufficient_data','candidate_for_field_check']
    risk=risk_assessment(d)
    assert risk.risk_level.iloc[2]=='unknown' or risk.risk_factors_observed.iloc[2]>0
    assert risk.risk_method.nunique()==1


def test_rotation_missing_does_not_get_ranked():
    t=pd.DataFrame({'strategy_id':['A','B'],'rotation':['wheat','vetch'],
        'candidate_crop':['wheat','vetch'], 'soil_cover_score':[np.nan,4],
        'water_efficiency_score':[np.nan,3], 'feed_score':[np.nan,3],
        'bee_foraging_score':[np.nan,4], 'market_score':[np.nan,2]})
    result=rank_rotations(t)
    assert result.loc[result.strategy_id.eq('A'),'relative_priority_score'].isna().all()
    assert result.loc[result.strategy_id.eq('B'),'relative_priority_score'].notna().all()
    t.loc[0,'soil_cover_score']=-1
    with pytest.raises(ValueError,match='0 to 5'):rank_rotations(t)


def test_era5_cds_bbox_and_official_fao_only():
    p=request(2024,9)
    assert p['area']==[38.95,23.32,38.75,23.50]
    assert len(p['day'])==30
    with pytest.raises(ValueError,match='official FAO'):validate_source('https://evil.example.net/fake.tif')
    validate_source('https://gaez-v4-data.fao.org/example.tif')


def test_old_recommendation_command_uses_regional_engine(tmp_path, monkeypatch):
    from agrisim.pipelines import generate_recommendations

    monkeypatch.setattr(generate_recommendations, "OUTPUTS", tmp_path)
    pd.DataFrame([{
        "crop_id": "winter_wheat", "season": "2024-2025", "week_start": "2024-11-11",
        "verdict": "check_worthy", "verdict_long_record": "check_worthy",
        "explanation": "Recent rain supports a field check.",
    }]).to_csv(tmp_path / "sowing_weeks.csv", index=False)
    pd.DataFrame([{
        "date": "2024-11-11", "field_id": "evia_pilot", "overall_level": 0,
        "overall_label": "none", "hazards_unknown": "",
        "spatial_support": "regional_context_not_field_measurement",
    }]).to_csv(tmp_path / "risk_daily.csv", index=False)
    output = tmp_path / "decision.csv"
    generate_recommendations.main(["--skip-vegetation", "--output", str(output)])
    result = pd.read_csv(output)
    assert result.decision_priority.tolist() == ["candidate_for_field_check"]
    assert result.component_c_rotation_status.tolist() == ["conditional_phase_comparison"]
    assert output.with_suffix(".json").is_file()


def test_valid_hls_archive_to_greenup_csv_offline():
    from agrisim.timeseries.vegetation_indices import build as build_indices
    from agrisim.timeseries.greenup import run as build_events
    with TemporaryDirectory() as tmp:
        base=Path(tmp)
        folder=base/'batch/evia_pilot/hls';folder.mkdir(parents=True)
        dates=pd.date_range('2024-10-01',periods=8,freq='10D').strftime('%Y-%m-%d')
        n=len(dates)
        reflect=np.zeros((n,3,5,5),dtype='float32')
        reflect[:,0]=0.1;reflect[:,1]=0.12
        nir=[.14,.15,.16,.17,.41,.44,.46,.49]
        for i,v in enumerate(nir):reflect[i,2]=v
        granules=[f'HLS.L30.T34SGH.2024{i:03d}T090000.v2.0' for i in range(n)]
        np.savez_compressed(folder/'field_context.npz',reflectance=reflect,
            clear=np.ones((n,5,5),bool),candidate_mask=np.ones((5,5),bool),
            dates=np.array(dates,dtype="U10"),granules=np.array(granules,dtype="U64"),
            bands=np.array(['B03','B04','B05']),crs='EPSG:32634',
            transform=np.array([30,0,0,0,-30,0]))
        result=build_indices(hls_batch=base/'batch',out=base/'vegetation.csv')
        assert len(result)==8
        assert result['ndvi_median'].iloc[-1]>result['ndvi_median'].iloc[0]
        event=build_events(observations=base/'vegetation.csv',out=base/'greenup.csv')
        assert len(event)==1
        assert event.status.iloc[0]=='retrospective_spectral_greenup'
        assert Path(base/'greenup.csv').exists()
