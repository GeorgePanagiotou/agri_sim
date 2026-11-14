# Sowing-window engine v1 (2026-11-14)

Phase 3 of the [gap report](../AgriSim_AI_Implementation_Gap_Report.md), design from SCOPE §7: **which candidate
week deserves a seedbed check** before sowing a rainfed crop. It never says "sow now"; the farmer checks the field
and decides. Regional, uncalibrated screen, **not a probability of establishment and not a forecast**.

```powershell
python -m agrisim.decision_engine.sowing_window
pytest -q tests/test_sowing_window.py
```

Code: `decision_engine/sowing_window.py`. Rules: [`configs/sowing_rules.yaml`](../configs/sowing_rules.yaml). Crop
windows and minimum soil temperatures: [`data/reference/sowing_windows.csv`](../data/reference/sowing_windows.csv)
(source and status per value). Inputs: the same POWER / IMERG / SMAP loaders as the
[risk engine](risk_engine.md), plus its heavy-rain level.

## Rules

Candidate weeks start every 7 days from the window start (wheat 1 Nov–15 Dec gives 1, 8, 15 … Nov). Each week is
judged with completed days before its start:

| Verdict | When | Basis |
|---|---|---|
| `unknown` | a needed input is missing | |
| `too_cold` | soil temperature (SMAP L4 0–5 cm, mean of the last 7 days; POWER 2 m air as proxy) < crop minimum | crop minimum from the literature, see the table |
| `too_dry` | rain in the last 10 days < 20 mm **and** SMAP surface moisture (3-day mean) below its Sep–Jun median | project choice, adapted from agroclimatic onset rules that use 20 mm (Sivakumar 1988) |
| `too_wet` | risk engine heavy-rain warning/severe: check field access and waterlogging first | project choice |
| `check_worthy` | none of the above | |

Two verdicts per week:
- **`verdict`** uses all the evidence available (SMAP for the seasons we hold, 2020–2026).
- **`verdict_long_record`** uses IMERG + POWER only, so every season from 2001 is judged the same way. The
  reliability statistics use this one.

| Crop | Window (team draft) | Min. soil temp | Source / status |
|---|---|---|---|
| winter wheat | 1 Nov – 15 Dec | 1.3 °C | emergence base, Cousens et al. 1992 · literature |
| barley | 25 Oct – 15 Dec | 2.2 °C | as above · literature |
| vetch–oat | 15 Oct – 30 Nov | 2.3 °C | oat value (Cousens 1992); vetch lower · analog |
| chickpea | 15 Nov – 31 Dec | 6.1 °C | emergence base · **citation to verify** |
| lentil | 1 Nov – 15 Dec | 5.0 °C | GRDC GrowNotes Lentil (field guidance) |
| phacelia | 10 Sep – 15 Oct | none | to source |
| sainfoin | 1 Oct – 15 Nov | none | to source |

**The windows are team drafts.** No official Greek extension calendar was found. A secondary source gives the broad
Greek winter-cereal season as early October to mid-January. They must be confirmed with a local agronomist.

## Outputs (`outputs/`)

- `sowing_weeks.csv`: one row per crop × season × week. It holds the evidence values and both verdicts, plus
  `evidence_mode`, `temp_source`, `rain_source` and a one-sentence `explanation`.
- `sowing_seasons.csv` / `sowing_seasons_long_record.csv`: per crop × season, the number of check-worthy weeks, the
  first check-worthy week, days after the window start, and the verdict sequence.
- `sowing_reliability.csv`: per crop over fully known seasons, the share of seasons with a check-worthy week and
  the median / latest days to the first one. These feed the **establishment-reliability** sub-score (SCOPE §7.2).

## First results (2001-02 … 2025-26, long-record verdicts)

- **Wheat, 2024-25** (the SCOPE §7.3 example):
  - 1 Nov and 8 Nov: too dry (0 mm in the previous 10 days).
  - 15 Nov: too dry (17 mm, just under the 20 mm rule).
  - 22 Nov: the first check-worthy week (47 mm).
  - **The 20 mm threshold matters.** It's the first thing to review locally.
- **Every crop had a check-worthy week in 84–100 % of seasons.** Phacelia, sown after the first September rain, is
  the most fragile (22 of 26 seasons).
- **To check, not a trend claim:** the median first workable week moved later from 2001–2012 to 2013–2025, with
  12–13 seasons per period.

  | Crop | 2001–2012 | 2013–2025 |
  |---|---|---|
  | Wheat | day 0 | day 14 |
  | Barley | day 3.5 | day 21 |
  | Lentil | day 0 | day 14 |

## Limitations

- Area-scale rain and moisture; a field after a local storm can differ.
- The soil-temperature minima almost never bind in Evia autumns. The SMAP L4 soil temperature (0–5 cm, 7-day mean)
  was 10.7–15.8 °C in Nov–Dec 2024, against crop minima of 1.3–6.1 °C, so moisture decides.
- With all six SMAP seasons, SMAP turned 9 weeks since 2020 from too dry to check-worthy (moist surface without
  20 mm of rain). The SMAP "moist" threshold is the Sep–Jun median, which includes the wet winter months, so in
  autumn it is a strict test.
- The SMAP "moist" threshold comes from the six seasons we hold (short baseline).
- No grower records or field observations exist to validate the verdicts (see SCOPE §7.5).
