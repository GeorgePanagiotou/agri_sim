"""Satellite NDVI/EVI2 time series: conservative threshold and *actual* PELT options.

PELT uses `ruptures.Pelt` (not a hand-written threshold marketed as PELT).
Savitzky-Golay smoothing is applied on a regularized daily grid, *only* between
observed clear dates.  Interpolated dates are never counted as acquisitions or
presented as exact green-up dates.

Two methods are offered:
  heuristic : original no-dependency conservative split detector (default).
  pelt      : ruptures PELT segmentation on smoothed NDVI+EVI2, followed by
              the same independent green-up direction/quality checks.

Neither method can establish sowing or crop emergence without farm observations.
BFAST is not implemented here: rigorous additive seasonal/trend breakpoint
analysis requires substantially denser multi-year coverage than the Evia pilot.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import savgol_filter
from .vegetation_indices import DEFAULT_OUT, ROOT

OUTPUT = ROOT / 'data/processed/features/greenup_events.csv'
SERIES_OUTPUT = ROOT / 'data/processed/features/vegetation_smoothed.csv'
COLUMNS_REQUIRED = {'field_id','season','source','date_utc','valid_pixels',
                    'clear_fraction','ndvi_median','evi2_median'}


def quality_dates(group: pd.DataFrame) -> pd.DataFrame:
    """Remove invalid/low-coverage observations and collapse same-day duplicates.

    Never average cross-sensor same-day data; groups should be per sensor.
    For repeated acquisitions, retain the one with the highest valid fraction.
    """
    d = group.copy()
    d['date_utc'] = pd.to_datetime(d['date_utc'], errors='coerce')
    for col in ('valid_pixels','clear_fraction','ndvi_median','evi2_median'):
        d[col] = pd.to_numeric(d[col],errors='coerce')
    d = d[(d['valid_pixels']>=4)&(d['clear_fraction']>=0.6)&
          np.isfinite(d['ndvi_median'])&np.isfinite(d['evi2_median'])&
          d['date_utc'].notna()]
    return (d.sort_values(['date_utc','clear_fraction'],ascending=[True,False])
             .drop_duplicates('date_utc', keep='first').sort_values('date_utc')
             .reset_index(drop=True))


def smooth_group(d: pd.DataFrame, window_days: int = 15,
                 max_gap_days: int = 40) -> pd.DataFrame:
    """Savitzky-Golay on daily-interpolated *observed* data, returned at real dates.

    Interpolated points exist internally for filtering only. Gaps > max_gap_days
    split the series; smoothing never bridges them. A short run uses raw values.
    """
    if window_days < 3 or window_days % 2 != 1:
        raise ValueError('Savitzky-Golay window_days must be odd and >= 3')
    if max_gap_days < 1:
        raise ValueError('max_gap_days must be >= 1')
    d = d.sort_values('date_utc').copy().reset_index(drop=True)
    if d.empty:
        return d.assign(ndvi_smoothed=pd.Series(dtype=float),
                        evi2_smoothed=pd.Series(dtype=float),
                        smoothing_applied=pd.Series(dtype=bool))
    dates = pd.to_datetime(d['date_utc'])
    if dates.duplicated().any():
        raise ValueError('smooth_group expects unique acquisition dates')
    gaps = dates.diff().dt.days.fillna(0).to_numpy()
    block = np.cumsum(gaps > max_gap_days)
    d['ndvi_smoothed'] = d['ndvi_median'].to_numpy(float)
    d['evi2_smoothed'] = d['evi2_median'].to_numpy(float)
    d['smoothing_applied'] = False

    for _,part in d.groupby(block, sort=False):
        ix = part.index.to_numpy()
        if len(ix) < 3:
            continue
        start, end = dates.iloc[ix[0]], dates.iloc[ix[-1]]
        day_count = int((end-start).days)+1
        window = min(window_days, day_count if day_count%2 else day_count-1)
        if window < 5:
            continue
        t = (dates.iloc[ix]-start).dt.days.to_numpy()
        grid = np.arange(day_count)
        for old_col,new_col in [('ndvi_median','ndvi_smoothed'),
                                ('evi2_median','evi2_smoothed')]:
            raw = d.loc[ix,old_col].to_numpy(dtype=float)
            interpolation = np.interp(grid,t,raw)
            filtered = savgol_filter(interpolation,window_length=window,
                                     polyorder=min(2,window-1),mode='interp')
            d.loc[ix,new_col] = filtered[t]
        d.loc[ix,'smoothing_applied'] = True
    return d


def _candidate(d: pd.DataFrame, i: int, min_delta_ndvi: float,
               min_delta_evi2: float,max_gap_days: int):
    """Scientifically conservative checks on ORIGINAL observed indices.

    Smoothing and PELT nominate breakpoints; they do not create evidence.
    """
    lo, hi = d.iloc[:i], d.iloc[i:]
    if len(lo)<2 or len(hi)<2:
        return None
    gap = (hi.iloc[0].date_utc - lo.iloc[-1].date_utc).days
    if not 1 <= gap <= max_gap_days:
        return None
    nd = float(hi.ndvi_median.median()-lo.ndvi_median.median())
    ev = float(hi.evi2_median.median()-lo.evi2_median.median())
    if nd < min_delta_ndvi or ev < min_delta_evi2:
        return None
    if (lo.ndvi_median.iloc[-1]>lo.ndvi_median.median()+0.08 or
        lo.evi2_median.iloc[-1]>lo.evi2_median.median()+0.04):
        return None
    if not ((hi.ndvi_median.iloc[:2]>lo.ndvi_median.median()+0.08).all() and
            (hi.evi2_median.iloc[:2]>lo.evi2_median.median()+0.04).all()):
        return None
    if lo.ndvi_median.median()>0.36:
        return None
    return (nd+ev,i,nd,ev)


def pelt_breaks(d: pd.DataFrame, *,min_side: int=2,penalty: float=3.0,
                window_days: int=15,max_gap_days: int=40) -> list[int]:
    """PELT indices are *observed-date* segment boundaries (end-exclusive).

    `ruptures.Pelt` is a real penalized optimal partitioning implementation.
    Standardizing by fixed biologically relevant increments allows both indices
    to contribute comparably instead of letting one index dominate by units.
    Results depend on penalty, revisit cadence and data quality.
    """
    if penalty <= 0:
        raise ValueError('PELT penalty must be positive')
    if min_side < 2:
        raise ValueError('min_side must be >= 2')
    try:
        import ruptures as rpt
    except ImportError as exc:
        raise RuntimeError('PELT requires ruptures. Install it with `uv add ruptures`, '
                           'then run `uv run python -m agrisim.timeseries.greenup --method pelt`.') from exc
    sm = smooth_group(d,window_days,max_gap_days)
    if len(sm) < 2*min_side:
        return []
    # Scale by the minimum transition magnitudes used for validation.
    signal = np.column_stack([sm['ndvi_smoothed'].to_numpy(float)/0.15,
                              sm['evi2_smoothed'].to_numpy(float)/0.09])
    return [int(i) for i in rpt.Pelt(model='l2',min_size=min_side,jump=1)
            .fit(signal).predict(pen=penalty) if int(i)<len(sm)]


def analyze_group(group:pd.DataFrame,min_observations=6,min_side=2,
                  min_delta_ndvi=0.15,min_delta_evi2=0.09,max_gap_days=40,
                  *,method='heuristic',pelt_penalty=3.0,savgol_window_days=15):
    if method not in ('heuristic','pelt'):
        raise ValueError('method must be heuristic or pelt')
    if group.empty:
        raise ValueError('Empty field-season group')
    d=quality_dates(group)
    # Diagnostic counts are attached to every outcome, even when the detector
    # cannot run. Acquisitions are not synonymous with quality-filtered dates.
    intervals = d.date_utc.diff().dt.days.dropna()
    bounded_pairs = int(((intervals >= 1) & (intervals <= max_gap_days)).sum())
    # A potential transition requires >= min_side observations on BOTH sides
    # of a gap no longer than max_gap_days. Without one, no negative detection
    # claim can be made, regardless of the total observation count.
    candidate_gaps = [i for i in range(min_side, len(d)-min_side+1)
                      if 1 <= (d.iloc[i].date_utc-d.iloc[i-1].date_utc).days <= max_gap_days]
    common=dict(field_id=str(group.iloc[0].field_id),season=str(group.iloc[0].season),
                source=str(group.iloc[0].source),n_clear_dates=len(d),
                n_raw_acquisitions=len(group),
                n_quality_rejected_acquisitions=max(0,len(group)-len(d)),
                first_clear_date=(str(d.iloc[0].date_utc.date()) if len(d) else None),
                last_clear_date=(str(d.iloc[-1].date_utc.date()) if len(d) else None),
                largest_clear_gap_days=(int(intervals.max()) if len(intervals) else None),
                n_bounded_clear_pairs=bounded_pairs,
                n_candidate_transition_gaps=len(candidate_gaps),
                method=('pelt_savgol' if method=='pelt' else 'heuristic'),
                pelt_breaks='[]',savgol_window_days=(savgol_window_days if method=='pelt' else None))
    empty={'last_low_date':None,'first_high_date':None,
           'confirmed_high_date':None,'transition_interval_days':None,
           'ndvi_change':np.nan,'evi2_change':np.nan}
    if len(d)<max(min_observations,2*min_side):
        return {**common,'status':'insufficient_clear_dates',**empty}
    if not candidate_gaps:
        return {**common,'status':'insufficient_temporal_coverage',**empty}
    if method=='pelt':
        cuts=pelt_breaks(d,min_side=min_side,penalty=pelt_penalty,
                         window_days=savgol_window_days,max_gap_days=max_gap_days)
        common['pelt_breaks']=json.dumps(cuts)
    else:
        cuts=list(range(min_side,len(d)-min_side+1))
    candidates=[c for i in cuts if (c:=_candidate(d,i,min_delta_ndvi,
                                min_delta_evi2,max_gap_days)) is not None]
    if not candidates:
        return {**common,'status':'no_confirmed_greenup',**empty}
    _,i,nd,ev=max(candidates,key=lambda c:c[0])
    return {**common,'status':'retrospective_spectral_greenup',
            'last_low_date':str(d.iloc[i-1].date_utc.date()),
            'first_high_date':str(d.iloc[i].date_utc.date()),
            'confirmed_high_date':str(d.iloc[i+1].date_utc.date()),
            'transition_interval_days':int((d.iloc[i].date_utc-d.iloc[i-1].date_utc).days),
            'ndvi_change':round(nd,4),'evi2_change':round(ev,4)}


def run(observations=DEFAULT_OUT,out=OUTPUT,*,method='heuristic',
        pelt_penalty=3.0,savgol_window_days=15,series_out=None):
    df=pd.read_csv(observations)
    missing=COLUMNS_REQUIRED-set(df.columns)
    if missing:
        raise ValueError(f'Missing observation fields: {sorted(missing)}')
    if df.empty:
        raise ValueError('No vegetation observations')
    groups=list(df.groupby(['field_id','season','source'],sort=True))
    events=[analyze_group(g,method=method,pelt_penalty=pelt_penalty,
                          savgol_window_days=savgol_window_days)
            for _,g in groups]
    result=pd.DataFrame(events)
    out=Path(out);out.parent.mkdir(parents=True,exist_ok=True)
    result.to_csv(out,index=False)
    if series_out is not None:
        smoothed=[]
        for _,g in groups:
            d=quality_dates(g)
            if not d.empty:
                smoothed.append(smooth_group(d,savgol_window_days))
        series=pd.concat(smoothed,ignore_index=True) if smoothed else pd.DataFrame()
        series_out=Path(series_out);series_out.parent.mkdir(parents=True,exist_ok=True)
        series.to_csv(series_out,index=False)
    print(f'{method} assessments: {len(result)} field-seasons -> {out}')
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--observations',type=Path,default=DEFAULT_OUT)
    ap.add_argument('--out',type=Path,default=OUTPUT)
    ap.add_argument('--method',choices=('heuristic','pelt'),default='heuristic')
    ap.add_argument('--pelt-penalty',type=float,default=3.0)
    ap.add_argument('--savgol-window-days',type=int,default=15)
    ap.add_argument('--series-out',type=Path,default=None)
    a=ap.parse_args()
    run(a.observations,a.out,method=a.method,pelt_penalty=a.pelt_penalty,
        savgol_window_days=a.savgol_window_days,series_out=a.series_out)
if __name__=='__main__':
    main()
