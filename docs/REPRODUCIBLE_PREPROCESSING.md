# AgriSim AI — Reproducible data preprocessing

**North Evia pilot:** `evia_pilot` at longitude `23.43232`, latitude `38.75920`. All imagery statistics relate to the provisional **3 × 3 HLS 30 m candidate mask**; this is **not** a surveyed agricultural parcel.

The scripts below are integrated into `src/agrisim/` and replace earlier PowerShell `@' ... '@ | uv run python -` one-off preprocessing snippets. **No manual changes to Python files are required after installing the update.** The downloaded raw rasters, NASA product caches and credentials remain on your PC and are **not included** in this source-code package.

## 1. Update an existing working checkout safely

In PowerShell, with `AgriSim_Integrated_Update.zip` saved in Downloads:

```powershell
cd D:\AgriSim\AgriSim-AI
Copy-Item .env "$env:USERPROFILE\agrisim-env-backup.txt" -ErrorAction SilentlyContinue
# No .env or raw data exists inside the update ZIP; nothing secret is uploaded.
Expand-Archive "$env:USERPROFILE\Downloads\AgriSim_Integrated_Update.zip" -DestinationPath . -Force
uv run pytest -q
```

**Before replacing any scripts you edited independently**, commit or back up your local code first; the update contains selected revised `.py` files and tests. It never replaces `data/raw`, `data/processed`, `.env`, `~/.netrc`, or `~/.cdsapirc`.

## 2. One local command for preprocessing and integration

Run the read-only plan first:

```powershell
uv run python -m agrisim.pipelines.prepare_multisource --plan
```

If the HLS batch, SRTM ZIP, GAEZ rasters, SMAP CSVs, and IMERG caches are found, regenerate the processed features:

```powershell
uv run python -m agrisim.pipelines.prepare_multisource --min-clear 0.8
```

The command performs, in order:

1. Select the latest **complete** HLS batch under `data/processed/evia_sowing/hls_batches` and extract L30 NDVI/EVI2/SAVI from original reflectance and Fmask, within the HLS 3 × 3 candidate mask.
2. Run real `ruptures` PELT on the HLS seasonal vegetation series (Savitzky–Golay smoothing and observed-date quality checks). This is **retrospective spectral green-up**, not verified crop emergence.
3. Reproject the **HLS candidate mask** onto every single-date ESA Sentinel-2 L2A TIFF, apply `SCL ∈ {4,5}` and `dataMask`, compute NDVI/EVI2/SAVI from physical reflectance and write `sentinel2_aligned_evia_pilot.csv`. It **does not** use the old full 990 × 990 m-window median or mix S2 and HLS NDVI directly.
4. Extract the approved NASA SRTM HGT ZIP and compute projected-grid elevation, slope, downslope aspect; save an aligned GeoTIFF and a one-row static CSV.
5. If ECOSTRESS ET GeoTIFFs are available, extract raw ETdaily overpasses at the same approximate footprint. **Keep source-reported `W/m²` units, no unverified mm/day conversion and no claim of cloud QA**.
6. Build `environment_multisource_daily.parquet` from POWER, IMERG Final/Late, SMAP, separately keyed HLS/S2, SRTM, and five FAO GAEZ crop rasters; optionally add the *raw* ECOSTRESS observational columns. The 2020–2026 default has **1,819 daily growing-season rows**.
7. Confirm that the feature table has the expected number of dates and no duplicate `(field_id, date)` rows.

**No remote API calls occur in this command**, and it doesn't modify raw downloaded files. It does regenerate existing files in `data/processed/features`.

## 3. Individual reusable commands

| Purpose | Module / command |
|---|---|
| NASA HLS preview | `uv run python -m agrisim.data_sources.landsat --fields data/reference/evia_hls_fields.csv --all-dates --workers 4 --plan` |
| NASA HLS cached-only processing | `uv run python -m agrisim.data_sources.landsat --fields data/reference/evia_hls_fields.csv --all-dates --cached-only --workers 4` |
| NASA HLS vegetation + PELT | `uv run python -m agrisim.pipelines.analyze_vegetation --hls-batch data/processed/evia_sowing/hls_batches/<BATCH_ID> --method pelt` |
| ESA Sentinel-2 aligned to HLS mask | `uv run python -m agrisim.preprocessing.sentinel2_aligned` |
| SRTM elevation + slope + aspect | `uv run python -m agrisim.preprocessing.srtm_terrain` |
| ECOSTRESS raw ET overpasses | `uv run python -m agrisim.features.ecostress` |
| Daily multisource join | `uv run python -m agrisim.features.build_multisource_environment --min-clear 0.8` |
| Regression tests | `uv run pytest -q` |

Sentinel-2 acquisition (not preprocessing) still uses `uv run --env-file .env python -m agrisim.data_sources.sentinel2 ... --download` and requires CDSE OAuth credentials. The acquisition script writes original five-band TIFFs and JSON manifests. NASA AppEEARS download is separate and requires Earthdata authentication. **Never commit credentials.**

## 4. Input files already acquired in the user's pilot

| Source | Local file or directory | Coverage caveat |
|---|---|---|
| POWER | `data/processed/power_daily_19910101_20261031.parquet` (builder auto-discovers the latest full-span archive) | Daily regional meteorology, not parcel measurements |
| IMERG Final V07 | `data/raw/imerg_daily/{2020..2025}.parquet` | Final V07 ends 2025-09-30 |
| IMERG Late V07 | `data/raw/imerg_late/2025_Q4.parquet` | 92 dates in Q4 2025; remains labelled Late, not Final |
| SMAP L4 | `data/processed/evia_sowing/smap/smap_daily_YYYY-MM-DD_YYYY-MM-DD.csv` | 1,819/1,819 season days validated, ~9 km support |
| HLS L30 | `data/processed/evia_sowing/hls_batches/<ID>/evia_pilot/hls/field_context.npz` | 370 NASA/mirror cross-verified granules, 11 NASA-only excluded |
| Sentinel-2 L2A | `data/raw/sentinel2/s2_l2a_*.tif` and paired metadata JSONs | 107 dates only for 2024–2025; sensor offset not harmonized |
| SRTM | `data/raw/srtm/N38E023.SRTMGL1.hgt.zip` | One static DEM; derived terrain is approximate |
| GAEZ v4 | `data/raw/fao_gaez/{wheat,barley,maize,chickpea,dry_pea}_rainfed_historical_low_input_suLr_*.tif` | Historical 1981–2010, low-input rainfed current-cropland suitability, 5 arc-min grid |
| ECOSTRESS JET | `data/raw/appeears/agrisim_ecostress_et_20240901_20241031/*ETdaily*.tif` | 5 occasional overpasses, raw `W/m²` labels, no cloud QA |
| ERA5-Land | Not used by this pipeline | Optional; requires accepted CDS licences |

## 5. Outputs and safeguards

The local pipeline writes under `data/processed/features/`:

- `vegetation_observations.csv`, `greenup_events.csv`: HLS observations and seasonal retrospective PELT assessments.
- `sentinel2_aligned_evia_pilot.csv`: Sentinel-2 indices over exactly the provisional HLS candidate region (not full 990 m image).
- `srtm_terrain_evia_pilot.tif`, `srtm_terrain_evia_pilot.csv`: aligned static terrain.
- `ecostress_overpasses.csv`: **optional raw** ECOSTRESS units and observed timestamps.
- `environment_multisource_daily.parquet`, `environment_multisource_coverage.csv`, `environment_multisource_gaez_crops.csv`, `environment_multisource_manifest.json`: integrated data, data coverage, crop values, and provenance.

Data safeguards:

- Missing vegetation or rainfall is **NaN**, not zero.
- Raw ECOSTRESS ET is not silently converted to mm/day or treated as QA-certified.
- HLS and S2 NDVI remain in **different columns** because of the observed same-day sensor offset.
- IMERG Final vs Late is explicit; source/calibration changes are not hidden.
- Lagged rainfall/soil-moisture/temperature features use **prior-day history** and preserve insufficiently observed windows.
- GAEZ values are **static regional agro-ecological context**, not daily crop-success predictions.
- Existing outputs are **observational, not independently verified agronomic labels**. Supervised crop-outcome training requires ground-truth crop history and results.

## 6. Testing and future work

The source archive includes offline regression tests for HLS grid differences, Sentinel-2 pixel alignment, QA filtering, SRTM aspect and slope, NASA ECOSTRESS filename timestamp parsing and unit preservation, IMERG Final/Late separation, SMAP resumability, five GAEZ rasters, and the six-season daily join. Tests do not exercise live NASA/ESA services or your local 370 HLS granules and 107 Sentinel-2 TIFFs; run the plan + preprocessing command on your Windows installation to verify those inputs.

Remaining science and data items: verify pilot parcel geometry, obtain independent crop/sowing/outcome labels, calibrate decision thresholds, optionally add ERA5-Land and ECOSTRESS LST/QA layers, process additional Sentinel-2 seasons, and assess PELT sensitivity around large winter observation gaps.
