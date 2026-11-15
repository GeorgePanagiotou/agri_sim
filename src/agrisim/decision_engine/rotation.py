"""Conditional Evia rotation phases and qualitative strategy scores."""
from pathlib import Path
import pandas as pd
import xarray as xr
from pyproj import Transformer
from agrisim.config import REF, PROC, RAW, SOWING_LAT, SOWING_LON
from agrisim.decision_engine.ranking import rank_rotations, COLUMNS
from agrisim.features.build_multisource_environment import _read_gaez_crop, EXPECTED_SCENARIO, CROPS


def apply_rotation(out, preferences=None):
    phases = pd.read_csv(REF/'rotations.csv').sort_values(['strategy_id','year'])
    scores = rank_rotations(pd.read_csv(REF/'rotations_template.csv') if preferences is None else preferences)
    scores = scores.set_index('strategy_id', verify_integrity=True)
    options = {}
    for strategy, group in phases.groupby('strategy_id'):
        previous = group.iloc[-1].crop_id
        for row in group.itertuples():
            if row.crop_id != 'sainfoin' or previous != 'sainfoin':
                options.setdefault(row.crop_id, []).append((strategy, f'{strategy} year {row.year} after {previous}'))
            if pd.notna(row.catch_crop_id):
                options.setdefault(row.catch_crop_id, []).append((strategy, f'{strategy} year {row.year} catch crop after {row.crop_id}'))
            previous = row.crop_id

    indices = {}
    for crop, code in CROPS.items():
        path = RAW/'fao_gaez'/f'{crop}_{EXPECTED_SCENARIO}_suLr_{code}.tif'
        if path.exists():
            indices['winter_wheat' if crop == 'wheat' else crop] = _read_gaez_crop(path,SOWING_LON,SOWING_LAT)['suitability_index']
    classes = {}
    path = PROC/'landsat_field_years.nc'
    if path.exists():
        with xr.open_dataset(path) as ds:
            x,y = Transformer.from_crs(4326,ds.attrs['crs'],always_xy=True).transform(SOWING_LON,SOWING_LAT)
            classes = ds.year_class.sel(x=x,y=y,method='nearest').to_series().to_dict()
    records = []
    for row in out.itertuples():
        matches = options.get(row.crop_id, [])
        ids = sorted({s for s,_ in matches})
        year = row.week_start.year - int(row.week_start.month < 10)
        cover = {1:'crop',2:'fallow/low cover',3:'summer crop'}.get(classes.get(year))
        gaps = ['confirmed field crop history and rotation phase']
        if not cover:
            gaps.append('prior Landsat class')
        if row.crop_id not in indices:
            gaps.append('crop-specific GAEZ layer')
        for s in ids:
            missing = [c for c in COLUMNS if s not in scores.index or pd.isna(scores.at[s,c])]
            if missing:
                gaps.append(f"{s}: {', '.join(missing)}")
        ordered = scores.reindex(ids).relative_priority_score
        ranked = ordered.sort_values(ascending=False).to_dict() if ids and ordered.notna().all() else {}
        description = '; '.join(label for _,label in matches)
        records.append(dict(rotation_options=description,rotation_strategy_ids=','.join(ids),
                            rotation_prior_season_end_year=year,rotation_prior_landsat_class=cover,
                            rotation_gaez_index=indices.get(row.crop_id),rotation_missing_inputs='; '.join(gaps),
                            rotation_preference_scores=str(ranked) if ranked else None))
    result = out.assign(**pd.DataFrame(records,index=out.index).to_dict('series'))
    result['component_c_rotation_status']='conditional_phase_comparison'
    result['component_e_fusion_status']=result.component_e_fusion_status.map({'partial_A_B_D':'A_B_C_D_conditional','partial_B_D_only':'B_C_D_conditional'})
    result['crop_rotation_recommendation']=result.rotation_options.replace('',pd.NA)
    result['decision_explanation'] += ' Conditional draft rotation phases: '+result.rotation_options+'. Verify field history.'
    mask=result.decision_priority.eq('candidate_for_field_check') & result.rotation_options.ne('')
    result.loc[mask,'recommended_action'] += ' Confirm the preceding crop for these rotation phases: '+result.loc[mask,'rotation_options']+'.'
    return result
