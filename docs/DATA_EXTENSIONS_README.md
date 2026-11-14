# AgriSim AI — SMAP, IMERG Late and FAO GAEZ extensions

**Updated:** 2026-11-14  
**Study area:** provisional `evia_pilot`, 23.43232 E, 38.75920 N (North Evia).  
**Scope:** Add new Python modules; do **not** replace the working downloaders or overwrite validated raw observations.  
**Implementation status:** Offline code/tests provided; NASA/FAO network downloads must run on the user's Windows machine with their own credentials. `--plan` previews. `--smoke-test` checks one real IMERG granule.

## Install safely

From `D:\AgriSim\AgriSim-AI`, unzip `AgriSim_Data_Extensions.zip` into the project root. It contains:

```text
src/agrisim/data_sources/download_evia_smap_range.py
src/agrisim/data_sources/download_imerg_late_2025.py
src/agrisim/data_sources/download_gaez_official.py
src/agrisim/data_sources/inspect_fao_gaez.py
src/agrisim/features/build_environment_multisource.py
tests/test_data_extensions.py
docs/DATA_EXTENSIONS_README.md
```

It does **not** contain `.env`, actual downloaded data, or the existing SMAP, IMERG Final and GAEZ downloaders. The IMERG Late script expects your already working **Earthdata-token version** of `src/agrisim/data_sources/download_imerg_daily.py`, which provides `authenticate()`, `_date_of()`, `read()` and `STUDY_AREA`.

Run dependency/syntax checks:

```powershell
uv run pytest -q tests/test_data_extensions.py
uv run python -m agrisim.data_sources.download_evia_smap_range --help
uv run python -m agrisim.data_sources.download_imerg_late_2025 --help
uv run python -m agrisim.data_sources.download_gaez_official --help
```

Never commit `.env`, Earthdata tokens, raw granules, or processed geospatial datasets to Git.

## 1. Extend SMAP (NASA SPL4SMGP v008)

**Already validated:** `data/processed/evia_sowing/smap/smap_daily.csv` has 306/306 complete days from Sep–Jan of 2023/24 and 2024/25, eight 3-hourly samples per day. This remains unchanged.

The new `download_evia_smap_range` module reuses existing NASA CMR/OPeNDAP code and monthly checkpoints (`data/raw/evia_sowing/smap/points_YYYY-MM.csv`). It writes separate range-specific outputs in `data/processed/evia_sowing/smap/`, so you can resume without re-fetching cached points.

All **six** requested September–June growing seasons:

```powershell
$seasons = @(
  @('2020-09-01','2021-06-30'),
  @('2021-09-01','2022-06-30'),
  @('2022-09-01','2023-06-30'),
  @('2023-09-01','2024-06-30'),
  @('2024-09-01','2025-06-30'),
  @('2025-09-01','2026-06-30')
)

# Metadata/catalog preview, no NASA point downloads:
foreach ($s in $seasons) {
  uv run --env-file .env python -m agrisim.data_sources.download_evia_smap_range `
    --start $s[0] --end $s[1] --workers 4 --plan
}

# Actual acquisition, resumable. Run each season independently if preferred:
foreach ($s in $seasons) {
  uv run --env-file .env python -m agrisim.data_sources.download_evia_smap_range `
    --start $s[0] --end $s[1] --workers 4
  if ($LASTEXITCODE -ne 0) { throw "SMAP failed for $($s[0]) to $($s[1]); resume this season" }
}
```

Note: SMAP uses a native approximately 9-km grid cell; these are **regional** soil-moisture/soil-temperature estimates, not field measurements. The feature is `sm_surface_m3m3`, not root-zone moisture: don't label it as the latter.

Files for each window:

```text
data/processed/evia_sowing/smap/
  smap_daily_2020-09-01_2021-06-30.csv
  smap_3hourly_2020-09-01_2021-06-30.csv
  granules_2020-09-01_2021-06-30.csv
  ...same pattern for remaining seasons...
```

Count complete days / gaps after downloads:

```powershell
@'
from pathlib import Path
import pandas as pd
root = Path('data/processed/evia_sowing/smap')
for f in sorted(root.glob('smap_daily_20*-*.csv')):
    d = pd.read_csv(f)
    complete = d.complete_day.astype(str).str.lower().eq('true')
    print(f.name, 'rows', len(d), 'complete', int(complete.sum()), 'incomplete', int((~complete).sum()))
'@ | uv run python -
```

Do not treat an incomplete day's mean as complete; the multisource feature builder masks such daily means.

## 2. IMERG Late V07 — Oct–Dec 2025

Your original `GPM_3IMERGDF` **Final V07** data are downloaded for 2020–Sep 30, 2025. NASA CMR returned **92 Late V07** `GPM_3IMERGDL` catalog dates for Oct–Dec 2025, but no Final V08 records in your preceding catalog check.

The new `download_imerg_late_2025` module retains the distinct product identity and stores the new data under `data/raw/imerg_late/` instead of `data/raw/imerg_daily/`.

```powershell
# Catalog/cache plan:
uv run --env-file .env python -m agrisim.data_sources.download_imerg_late_2025 --plan

# Test one genuine Late Run NetCDF and verify variable/unit parsing:
uv run --env-file .env python -m agrisim.data_sources.download_imerg_late_2025 --smoke-test

# Download all missing Late Run days (bounded batches, resumable):
uv run --env-file .env python -m agrisim.data_sources.download_imerg_late_2025 --workers 2
```

Expected outputs once finished:

```text
data/raw/imerg_late/2025_Q4.parquet
data/raw/imerg_late/2025_Q4_manifest.json
data/processed/imerg_late_area_mean_2025Q4.parquet
```

Check downloaded days:

```powershell
@'
import pandas as pd
p = 'data/raw/imerg_late/2025_Q4.parquet'
d = pd.read_parquet(p)
dates = pd.to_datetime(d['date']).dt.normalize()
missing = pd.date_range('2025-10-01','2025-12-31').difference(dates.unique())
print('Days:', dates.nunique(), '/ 92')
print('Missing:', len(missing), missing[:10].tolist())
print('Distinct sources:', d['source'].unique().tolist())
'@ | uv run python -
```

**Scientific caveat:** Late and Final precipitation products have different latency/calibration. Keep `gpm_product` as a feature/source indicator. The current code verifies that observed grid cells have the same coordinates before combining. It **does not** perform an empirically validated Late-vs-Final bias calibration.

The full-globe files may be downloaded temporarily to extract the 0.1-degree regional cells; don't interrupt the network unnecessarily. A failed run saves completed batches for resumption. 2026 IMERG coverage is a separate work item.

## 3. FAO GAEZ v4 suitability — select a real layer first

FAO's GAEZ v4 is a *collection*, not a single suitability GeoTIFF. It depends on:
- **Crop** (e.g. wheat `whe`, barley `brl`, olive `olv`),
- **Water**: rainfed or irrigated,
- **Input level**: high/low,
- **Climate**: historic period or future scenario,
- **Indicator**: suitability **index** vs suitability **class** (and current cropland vs all land if applicable).

Official resources:
- https://gaez.fao.org/ — browse the Data Viewer / GAEZ v4 suitability theme.
- https://gaez-v4-data.fao.org/ — official v4 data repository.
- https://www.fao.org/gaez/gaezv4/en — methodology and source.

Find a *specific* suitability-index layer for the crop/scenario needed (for the initial rainfed pilot, wheat is a reasonable **example**, not a claimed project crop). Copy the actual direct `.tif` URL from FAO's portal/repository, **do not reconstruct a filename by guesswork**. The repository sometimes provides a URL in FAO's documented S3 bucket `data.gaezdev.aws.fao.org` hosted on `s3.eu-west-1.amazonaws.com`. The module validates that origin.

```powershell
# Paste a REAL direct URL copied from FAO (do not leave the placeholder):
$gaezUrl = '<FAO_GAEZ_V4_DIRECT_SUITABILITY_INDEX_TIF_URL>'

uv run python -m agrisim.data_sources.download_gaez_official `
  --url $gaezUrl --crop wheat `
  --scenario rainfed_historical_exact_fao_selection `
  --kind suitability-index --plan

uv run python -m agrisim.data_sources.download_gaez_official `
  --url $gaezUrl --crop wheat `
  --scenario rainfed_historical_exact_fao_selection `
  --kind suitability-index
```

This adds a GeoTIFF and JSON provenance manifest under `data/raw/fao_gaez/`, verifies geographic coverage of Evia, and reports the **raw** pixel value. Raw values are **not** automatically interpreted as agronomic suitability scores. Consult the exact FAO layer legend/codebook before assigning classes or creating recommendations.

**GAEZ v5 is available**, but this extension intentionally follows your existing `download_fao_gaez.py` v4 architecture. Do not mix versions silently.

**FAO data cannot be downloaded without specifying a valid official suitability raster URL.** Neither this patch nor an unverified guessed URL can select a crop/scenario scientifically.

## 4. Optional: build the integrated environmental table

After downloads, the included `build_environment_multisource` module uses the **existing** POWER, HLS, Sentinel-2 aligned, SRTM and new IMERG/SMAP files, with separate satellite NDVI columns and explicit product metadata.

```powershell
uv run python -m agrisim.features.build_environment_multisource `
  --power data/processed/power_daily_19910101_20251231.parquet `
  --min-clear 0.8
```

Output: `data/processed/features/environment_multisource_daily.parquet`.

- Rainfall and soil moisture **missing** days stay `NaN`, never become zero.
- Rainfall from IMERG Final and Late retains product identity.
- Incomplete SMAP days are excluded from measured moisture values.
- HLS and Sentinel-2 vegetation-index columns are separate due to unresolved sensor offset (only six same-day pairs in the 2024–25 pilot).
- Prior-day rolling rainfall/temperature excludes current day to reduce leakage in start-of-day prediction.
- Terrain values are static and repeated per day; GAEZ is *not* automatically joined until the chosen layer's units/legend are verified.
- `evia_pilot` has an **unverified** provisional 3×3 HLS footprint, not a confirmed crop field or agricultural label.

## 5. Commit only source, tests and docs

Copy the tested changes into the working Git clone, then:

```powershell
git status
git add src/agrisim/data_sources/download_evia_smap_range.py `
        src/agrisim/data_sources/download_imerg_late_2025.py `
        src/agrisim/data_sources/download_gaez_official.py `
        src/agrisim/data_sources/inspect_fao_gaez.py `
        src/agrisim/features/build_environment_multisource.py `
        tests/test_data_extensions.py `
        docs/DATA_EXTENSIONS_README.md
git commit -m "Add resumable SMAP, IMERG Late and FAO GAEZ acquisition tools"
git push origin feature/agrisim-ai-architecture
```

## Validation status

The patch was checked with Python compilation and **10 offline tests**, including SMAP 3-hourly completeness and checkpoint merging, IMERG source tags, preservation of rainfall gaps, validation of FAO URL origin, overlap detection, sensor-specific vegetation columns and nonleaky rolling features. **No live Earthdata or FAO downloads were run in the assistant environment.**
