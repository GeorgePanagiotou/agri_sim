"""Offline regression tests for vegetation coverage reporting and as-of cutoffs."""

from __future__ import annotations

import pandas as pd
import pytest

from agrisim.timeseries.greenup import analyze_group
from agrisim.decision_engine import vegetation_history as history


SOURCE = "NASA_HLSL30_v2"
SUPPORT = "user_drawn_or_uploaded_boundary"


def observations(dates, *, year_season, ndvi=None, evi2=None, releases=None, clear=None):
    n = len(dates)
    ndvi = [0.12] * n if ndvi is None else ndvi
    evi2 = [0.08] * n if evi2 is None else evi2
    releases = [str(pd.Timestamp(d) + pd.Timedelta(days=1)) for d in dates] if releases is None else releases
    clear = [0.95] * n if clear is None else clear
    return pd.DataFrame({
        'field_id': ['1'] * n, 'season': [year_season] * n,
        'source': [SOURCE] * n, 'spatial_support': [SUPPORT] * n,
        'date_utc': dates, 'available_utc': releases,
        'valid_pixels': [25] * n, 'clear_fraction': clear,
        'ndvi_median': ndvi, 'evi2_median': evi2,
    })


def _heuristic_instead_of_pelt(monkeypatch):
    # Greenup_history always uses PELT in production. Cover availability and
    # grouping without requiring the optional `ruptures` package in tests.
    detector = analyze_group
    monkeypatch.setattr(history, 'analyze_group', lambda group, **kw: detector(group, method='heuristic'))


def test_one_clear_date_remains_insufficient():
    group = observations(['2026-11-06'], year_season='2026-2027')
    result = analyze_group(group)
    assert result['status'] == 'insufficient_clear_dates'
    assert result['n_raw_acquisitions'] == 1
    assert result['n_clear_dates'] == 1
    assert result['n_candidate_transition_gaps'] == 0
    assert result['first_clear_date'] == '2026-11-06'


def test_six_sparse_clear_dates_are_not_a_negative_greenup_result():
    dates = ['2025-09-01', '2025-10-20', '2025-12-10',
             '2026-02-01', '2026-03-25', '2026-05-15']
    group = observations(dates, year_season='2025-2026')
    result = analyze_group(group)
    assert result['n_clear_dates'] == 6
    assert result['n_candidate_transition_gaps'] == 0
    assert result['status'] == 'insufficient_temporal_coverage'
    assert result['last_low_date'] is None


def test_six_well_spaced_stable_dates_keep_previous_no_detection_result():
    dates = pd.date_range('2025-10-01', periods=6, freq='10D').strftime('%Y-%m-%d').tolist()
    result = analyze_group(observations(dates, year_season='2025-2026'))
    assert result['status'] == 'no_confirmed_greenup'
    assert result['n_candidate_transition_gaps'] > 0


def test_clear_spectral_increase_still_detected_with_original_rules():
    dates = pd.date_range('2025-10-01', periods=6, freq='10D').strftime('%Y-%m-%d').tolist()
    group = observations(dates, year_season='2025-2026',
                         ndvi=[.10, .11, .12, .40, .42, .44],
                         evi2=[.05, .06, .07, .22, .24, .26])
    result = analyze_group(group)
    assert result['status'] == 'retrospective_spectral_greenup'
    assert result['last_low_date'] == dates[2]
    assert result['first_high_date'] == dates[3]
    assert result['confirmed_high_date'] == dates[4]


def test_quality_rejected_acquisitions_counted():
    dates = pd.date_range('2025-10-01', periods=7, freq='10D').strftime('%Y-%m-%d').tolist()
    group = observations(dates, year_season='2025-2026', clear=[.95, .20, .95, .95, .95, .95, .95])
    result = analyze_group(group)
    assert result['n_raw_acquisitions'] == 7
    assert result['n_clear_dates'] == 6
    assert result['n_quality_rejected_acquisitions'] == 1


def test_history_excludes_future_acquisitions_and_late_publications(monkeypatch):
    _heuristic_instead_of_pelt(monkeypatch)
    earlier_dates = pd.date_range('2025-10-01', periods=6, freq='10D').strftime('%Y-%m-%d').tolist()
    earlier = observations(earlier_dates, year_season='2025-2026')
    current = observations(['2026-11-01','2026-11-06','2026-11-07','2026-11-08'],
                           year_season='2026-2027',
                           releases=[None, '2026-11-07T01:00:00Z',
                                     '2026-11-09T01:00:00Z', '2026-11-09T01:00:00Z'])
    frame = pd.concat([earlier, current], ignore_index=True)
    candidates = pd.DataFrame({'season':['2026-2027','2026-2027'],
                               'week_start':pd.to_datetime(['2026-11-08','2026-11-15'])})
    result = history.greenup_history(candidates, frame, field_id='1', support=SUPPORT)
    early, later = result.iloc[0], result.iloc[1]
    assert early['vegetation_observations_available'] == 7  # 6 prior + 1 current
    assert early['greenup_current_acquisitions'] == 1
    assert early['greenup_current_clear_dates'] == 1
    assert early['greenup_current_clear_dates_needed'] == 5
    assert early['vegetation_acquisitions_missing_publication_dates'] == 1
    assert early['greenup_prior_seasons_assessed'] == 1
    assert later['greenup_current_acquisitions'] == 3
    # Recomputing the later cutoff cannot change the earlier snapshot.
    assert result.iloc[0]['greenup_current_status'] == 'insufficient_clear_dates'


def test_history_marks_sparse_previous_season_as_unassessable(monkeypatch):
    _heuristic_instead_of_pelt(monkeypatch)
    dates = ['2025-09-01', '2025-10-20', '2025-12-10',
             '2026-02-01', '2026-03-25', '2026-05-15']
    prior = observations(dates, year_season='2025-2026')
    next_year = observations(['2026-11-06'], year_season='2026-2027')
    candidate = pd.DataFrame({'season':['2026-2027'], 'week_start':[pd.Timestamp('2026-11-08')]})
    row = history.greenup_history(candidate, pd.concat([prior,next_year],ignore_index=True),
                                  field_id='1',support=SUPPORT).iloc[0]
    assert row['greenup_prior_seasons_with_visible_scenes'] == 1
    assert row['greenup_prior_seasons_insufficient_coverage'] == 1
    assert row['greenup_prior_seasons_assessed'] == 0


def test_apply_greenup_preserves_action_and_adds_coverage_explanation(monkeypatch):
    _heuristic_instead_of_pelt(monkeypatch)
    obs = observations(['2026-11-06'],year_season='2026-2027')
    decisions = pd.DataFrame({
        'season':['2026-2027'], 'week_start':[pd.Timestamp('2026-11-08')],
        'component_a_vegetation_status':['not_integrated'],
        'decision_priority':['field_check_required'],
        'recommended_action':['Inspect field'], 'decision_explanation':['Original explanation.'],
    })
    row = history.apply_greenup(decisions, obs, field_id='1', support=SUPPORT).iloc[0]
    assert row['recommended_action'] == 'Inspect field'
    assert row['greenup_current_status'] == 'insufficient_clear_dates'
    assert 'six are required' in row['decision_explanation']
    assert '1 available acquisition(s)' in row['decision_explanation']
    assert 'Original explanation.' in row['decision_explanation']


def test_unavailable_and_unknown_publication_is_explicit(monkeypatch):
    _heuristic_instead_of_pelt(monkeypatch)
    obs = observations(['2026-11-01'],year_season='2026-2027', releases=[None])
    result = history.greenup_history(pd.DataFrame({'season':['2026-2027'],
                             'week_start':[pd.Timestamp('2026-11-08')]}), obs,
                             field_id='1', support=SUPPORT).iloc[0]
    assert result['component_a_vegetation_status'] == 'missing_publication_dates'
    assert result['vegetation_observations_available'] == 0
    assert result['vegetation_acquisitions_missing_publication_dates'] == 1
