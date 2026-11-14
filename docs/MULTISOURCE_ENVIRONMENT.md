# AgriSim AI — Multisource Environmental Feature Pipeline

**Purpose:** Build an auditable daily environmental table for the provisional North Evia pilot (`evia_pilot`, **23.43232° E, 38.75920° N**) covering the six September–June growing seasons **2020–2021 through 2025–2026** (expected **1,819 daily rows**). This is a retrospective environmental dataset, **not** crop-emergence ground truth or an operational weather forecast.

## 1. Install

Unzip `AgriSim_Multisource_Environment.zip` directly into your working project at `D:\AgriSim\AgriSim-AI`, maintaining the paths inside the ZIP.

```powershell
cd D:\AgriSim\AgriSim-AI
Expand-Archive `
  -Path "$env:USERPROFILE\Downloads\AgriSim_Multisource_Environment.zip" `
  -DestinationPath . -Force
```

The ZIP adds **one new** module, `src/agrisim/features/build_multisource_environment.py`. It **does not overwrite** your earlier `build_environment_multisource.py`, data downloaders or any data files.

The new module reuses the reader functions from the earlier `AgriSim_Data_Extensions.zip`. That earlier extension must already be installed. Your current AgriSim setup should have it because you successfully used `download_evia_smap_range` and `download_imerg_late_2025`.

Required dependencies (`pandas`, `numpy`, `pyarrow`, `rasterio`) are included in your project's `pyproject.toml`.

## 2. Expected input files

| Source | File(s) used | Interpretation |
|---|---|---|
| NASA POWER | `data/processed/power_daily_19910101_20261031.parquet` if available; otherwise latest full-span POWER file | Regional daily weather; choose most recent full-span data automatically |
| IMERG Final V07 | `data/raw/imerg_daily/2020.parquet` … `2025.parquet` | Observed regional-cell daily precipitation, aggregated to regional mean |
| IMERG Late V07 | `data/raw/imerg_late/2025_Q4.parquet` | 92 days in 2025 Q4; preserves `IMERG_Late_V07` provenance |
| SMAP L4 | `data/processed/evia_sowing/smap/smap_daily_YYYY-MM-DD_YYYY-MM-DD.csv` | Daily regional soil moisture and soil temperature; overlapping original pilot files deduplicated |
| NASA HLS L30 | `data/processed/features/vegetation_observations.csv` | NDVI/EVI2 from *provisional HLS candidate mask*; irregular acquisition dates |
| ESA Sentinel-2 L2A | `data/processed/features/sentinel2_aligned_evia_pilot_2024_2025.csv` | 2024–2025 NDVI/EVI2, spatially re-extracted against the same HLS candidate footprint |
| NASA SRTM | `data/processed/features/srtm_terrain_evia_pilot.csv` | Static elevation, slope, aspect |
| FAO GAEZ v4 | Five `data/raw/fao_gaez/*_rainfed_historical_low_input_suLr_*.tif` rasters | Static regional suitability index (1981–2010 historical baseline, current cropland) |

The code samples the five **raw FAO rasters** directly, so it is not affected by an earlier CSV bug that shortened `dry_pea` to `dry`.

### Missing input caveats

- **IMERG for January–June 2026 has not been confirmed downloaded.** Those dates remain `NaN` in this table, even though SMAP covers them.
- If your longest POWER file ends in December 2025, POWER observations for 2026 will be `NaN` rather than dropping 2026 rows. If the 2026 POWER file exists, it is automatically preferred.
- Sentinel-2 is currently processed only for **2024–2025**, whereas HLS covers all six seasons.
- NASA ECOSTRESS ET has been submitted to AppEEARS but was still queued, and ERA5-Land was blocked by CDS licence acceptance. **Neither is required** for this first version.

## 3. Build the table

```powershell
cd D:\AgriSim\AgriSim-AI

uv run python -m agrisim.features.build_multisource_environment `
  --min-clear 0.8
```

To explicitly select the POWER source:

```powershell
uv run python -m agrisim.features.build_multisource_environment `
  --power data/processed/power_daily_19910101_20261031.parquet `
  --min-clear 0.8
```

For a sensitivity run using a different vegetation quality threshold, e.g. 50%:

```powershell
uv run python -m agrisim.features.build_multisource_environment `
  --min-clear 0.5 `
  --out-dir data/processed/features/multisource_clear50
```

The script does not need the GPU and performs no network requests.

### Outputs

```text
data/processed/features/
  environment_multisource_daily.parquet        # 1,819 daily rows across 6 seasons
  environment_multisource_coverage.csv         # per-season source counts and gaps
  environment_multisource_gaez_crops.csv       # separate 5-row static crop table
  environment_multisource_manifest.json       # paths, threshold, assumptions, provenance
```

**The source datasets are not modified**, and no existing raw NASA/ESA/FAO files are overwritten. The outputs above are regenerated when you rerun the new module with the default output directory.

## 4. How the joins work

1. Construct an uninterrupted calendar from 30 days before September 1, 2020, through June 30, 2026.
2. Left-join POWER, regional IMERG Final/Late and daily SMAP **on date**. Missing source dates remain missing; rainfall is never filled with `0`.
3. Left-join observed HLS/Sentinel-2 NDVI/EVI2 with `clear_fraction >= 0.8`. Preserve each sensor as **separate columns** (do **not** average or apply a naive offset correction).
4. Add three SRTM terrain descriptors as **static contextual features** for the pilot area.
5. Read and sample five FAO GAEZ v4 suitability rasters at the pilot center; add five separately named **static suitability-index columns**, and export the normalized crop table.
6. Create `*_prior_*` temporal features with `.shift(1)` so they only use **completed prior days**. Compute these on the uninterrupted calendar so June observations aren't mistakenly treated as immediately preceding September.
7. Filter to the six September–June growing seasons. Ensure one row per date, assign season ID and season day, and export QA counts.

### Selected columns

- Keys: `date`, `field_id`, `season`, `season_day`, `geometry_status`.
- POWER: `power_temp_c`, `power_rain_mm`, and any other renamed POWER variables (e.g. `power_relative_humidity_pct`).
- IMERG: `gpm_rain_mm`, `gpm_product` (`IMERG_Final_V07` or `IMERG_Late_V07`), `gpm_valid_cells`, `imerg_missing`.
- SMAP: `smap_surface_m3m3`, `smap_soil_temp_c`, `smap_complete_day`, `smap_missing`.
- Vegetation: `hls_ndvi`, `hls_evi2`, `hls_clear_fraction`, `s2_ndvi`, `s2_evi2`, `s2_clear_fraction`, `hls_s2_same_day`, `hls_minus_s2_ndvi`.
- Static terrain: `srtm_elevation_m_median`, `srtm_slope_deg_median`, `srtm_aspect_deg_circular_mean`.
- Static crop suitability: `gaez_wheat_index`, `gaez_barley_index`, `gaez_maize_index`, `gaez_chickpea_index`, `gaez_dry_pea_index`.
- Past-only weather features: `imerg_rain_prior_7d_mm`, `imerg_rain_prior_14d_mm`, `power_temp_prior_7d_c`, `power_gdd5_prior_14d`, `smap_surface_prior_7d_m3m3`.

**Important:** Same-day observed weather, satellite indices and static GAEZ suitability are *retrospective* features. Only explicit `*_prior_*` features are guaranteed to exclude the candidate date; a deployment system also needs a true operational forecast or as-of-date data availability check.

### Spatial and scientific limitations

- The `evia_pilot` is a provisional HLS **3×3 pixel (roughly 90×90 m)** candidate sample, **not** a registered farm parcel.
- SMAP is coarse regional moisture, IMERG uses approximately 0.1-degree regional cells, POWER is gridded weather, and GAEZ has approximately 5 arc-minute pixels. Values must not be presented as field sensor readings.
- Same-day HLS and Sentinel-2 median NDVI differed by approximately 0.061 (S2 minus HLS median, based on six paired days). The pipeline **does not merge their NDVI** because this offset has not been calibrated.
- The 2024–2025 February NDVI acquisition gap remains approximately 33 days after combining available observations. Do not infer exact crop-emergence dates.
- GAEZ `suLr` index values are modeled **historical suitability for current cropland** on a 0–10,000 scale, not yields, probabilities, or rotation decisions. The same static values repeat on every date by design.
- There are **no verified crop, sowing, harvest, yield or rotation outcome labels**. Do not train supervised sowing-success models pretending spectral green-up is ground truth.

## 5. Validation after running

```powershell
@'
from pathlib import Path
import pandas as pd
p = Path("data/processed/features")
df = pd.read_parquet(p / "environment_multisource_daily.parquet")
qa = pd.read_csv(p / "environment_multisource_coverage.csv")
print("Rows:", len(df))
print("Seasons:", df.season.nunique())
print("Duplicate dates:", df.date.duplicated().sum())
print("IMERG product counts:", df.gpm_product.value_counts(dropna=False).to_dict())
print("Missing 2026 IMERG days:", df.loc[df.date >= "2026-01-01", "gpm_rain_mm"].isna().sum())
print("GAEZ crops:", sorted(c for c in df if c.startswith("gaez_") and c.endswith("_index")))
print("\nSOURCE COVERAGE BY SEASON")
print(qa.to_string(index=False))
assert len(df) == 1819
assert df.season.nunique() == 6
assert not df.date.duplicated().any()
'@ | uv run python -
```

Expected 2024–2025 quality-qualified vegetation counts given earlier validated CSVs: **HLS 16 dates** and **Sentinel-2 62 dates** at 80% clear (possibly 72 distinct multi-sensor dates). Exact final counts will be printed from *your files*; the script does not hard-code them.

### Run offline regression tests

```powershell
uv run pytest -q tests/test_multisource_environment.py
```

The tests cover six-season lengths, duplicate-date rejection, missing rainfall, prior-day leakage, ERA5/ECOSTRESS absence, GAEZ sampling, five expected crop layers, satellite NDVI separation, and seasonal rollover behavior.

## 6. After the table exists

1. **Audit outputs:** Identify which growing seasons have adequate weather/rain/moisture coverage and report all missing/quality-flagged values.
2. **Multisensor phenology:** Run **Sentinel-2-only PELT** first for 2024–2025; evaluate a separate HLS-only baseline and optional harmonization sensitivity. Never invent vegetation observations inside the February gap.
3. **Environmental risk features:** Calculate robust rainfall antecedents, GDD, moisture anomalies and relative heat/water-stress indices using only as-of-date information. Define missing-data behavior explicitly.
4. **Crop suitability comparison:** Use the five regional GAEZ layers as an initial **contextual filter**, not as trained success probabilities or automatic prescriptions.
5. **Evaluation:** Obtain verified field polygons, actual crop identities/rotations, sowing/harvest dates and outcomes before claiming model validation.
6. **Optional enhancements:** Retrieve ECOSTRESS ET when AppEEARS completes and append it as sparse, timestamped QC-filtered observations. ERA5-Land can be added later after CDS licence acceptance. Extend Sentinel-2 to the other five seasons when comprehensive historical phenology is needed.

## 7. Git workflow

Commit only the Python module, tests and documentation, not data or secret files:

```powershell
# In the Git clone on your feature branch:
git add src/agrisim/features/build_multisource_environment.py `
        tests/test_multisource_environment.py `
        docs/MULTISOURCE_ENVIRONMENT.md
git commit -m "Add auditable multisource environmental feature pipeline"
git push origin feature/agrisim-ai-architecture
```

Copy the tested files to your actual Git clone before committing if your active working directory is a separate copy.
