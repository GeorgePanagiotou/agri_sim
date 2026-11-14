# AgriSim AI — HLS & Sentinel-2 Preprocessing and Next Steps

**Project:** North Evia (`evia_pilot`) satellite vegetation time series  
**Last updated:** 2026-11-14  
**Environment:** Windows PowerShell, Python 3.11, `uv`  
**Working directory:** `D:\AgriSim\AgriSim-AI`  
**Git clone (separate directory):** `D:\AgriSim\agri_sim`

> **Interpretation:** The point at longitude **23.43232**, latitude **38.75920** and the HLS `candidate_mask` identify a **provisional sampling area**, **not a surveyed agricultural field**. Satellite vegetation changes are *not* verified sowing, emergence, crop-type, or yield labels. Do not label the PELT outputs as ground truth.

## 1. Status as of 2026-11-14

| Component | Observed result | Notes |
| --- | --- | --- |
| NASA HLSL30 v2 | **370** HLS granules cached and processed; **186** acquisition dates in **6** growing seasons (2020–2026) | **11** NASA-only granules are absent from the Planetary Computer mirror, mostly affecting 2025–2026. |
| HLS clear vegetation | **82 / 186** dates have non-null NDVI | Original PELT eligibility filtering kept **78** dates across six seasons. |
| HLS PELT | 6 seasonal assessments, 3 potential retrospective spectral green-ups | Other 3 have `no_confirmed_greenup`; not proof of absent vegetation growth. |
| ESA Sentinel-2 L2A | **107** dated 10 m GeoTIFF windows downloaded for **2024-09-01 to 2025-06-30** | Each GeoTIFF has **5 bands**, **99 × 99** pixels. |
| Sentinel-2 original full-window indices | 78 / 107 dates with NDVI; 53 dates ≥80% clear | Full window samples ~990 × 990 m and must **not** be compared directly to the HLS candidate area. |
| Sentinel-2 aligned to HLS mask | **67 / 107** dates with NDVI; **62** ≥80% clear | Reprojection yields **81** Sentinel-2 pixels per image in the provisional 90 × 90 m sampling footprint. |
| Multisensor comparison (2024–2025) | **16 HLS + 62 Sentinel-2 = 78** source-specific rows on **72** unique dates | Six same-day pairs; median **S2 − HLS NDVI = −0.0609**. **Not harmonized**. |
| Longest high-quality combined gap | **33 days** (2025-02-01 to 2025-03-06) | Do not infer an exact green-up date inside this unobserved interval. |
| Other datasets | NASA POWER available; IMERG 2023–2024 complete; 2025 incomplete at last check; SMAP two pilot autumn–winter seasons | The live status of IMERG 2025 completion has not been rechecked here. |

### Important output paths

```text
data/raw/sentinel2/
  catalogue_evia_pilot_2024-09-01_2025-06-30.json
  s2_l2a_*.tif                         # 107 5-band images
  s2_l2a_*.json                        # one manifest per image

data/processed/evia_sowing/hls_batches/
  20261114T003254Z-5284ba4b/
    field_coverage.csv
    labels_template.csv
    evia_pilot/hls/
      field_context.npz                # reflectance, Fmask, clear, candidate_mask, CRS, transform
      acquisitions.csv
      nasa_catalog.csv

data/processed/features/
  vegetation_observations.csv
  greenup_events.csv
  sentinel2_vegetation_observations_2024_2025.csv    # ORIGINAL full-window values
  sentinel2_aligned_evia_pilot_2024_2025.csv       # ALIGNED footprint values
  vegetation_multisensor_2024_2025.csv             # SENSOR-SPECIFIC rows, no correction
  multisensor_ndvi_2024_2025.png
```

## 2. Dependencies and security

The existing AgriSim project uses `numpy`, `pandas`, `rasterio`, `pyproj`, `scipy`, and `ruptures` (for PELT). Work inside the project root:

```powershell
cd D:\AgriSim\AgriSim-AI
uv sync
```

For the Sentinel-2 downloader, Copernicus OAuth credentials belong in a **Git-ignored** `.env` file, never source code:

```dotenv
CDSE_CLIENT_ID=<your-own-client-id>
CDSE_CLIENT_SECRET=<your-own-client-secret>
```

Use `uv run --env-file .env ...` for acquisition commands. The HLS downloader uses public catalogues and cached data; do not share NASA Earthdata tokens or any other secrets. Keep `data/`, `.env`, `.venv`, and generated model checkpoints out of Git.

---

# Part A — NASA HLS Landsat preprocessing

## 3. Acquisition and cached processing

HLS `L30` source: NASA HLSL30 v2.0; mirrored raster assets through Microsoft Planetary Computer. The project cross-checks each mirror granule against NASA CMR. The updated downloader allows **NASA-only** scenes to be reported as unavailable without silently claiming they were downloaded; it still rejects unverified mirror-only scene IDs.

The input `data/reference/evia_hls_fields.csv` contains one `evia_pilot` row for each of these periods:

```text
2020-09-01 through 2021-06-30
2021-09-01 through 2022-06-30
2022-09-01 through 2023-06-30
2023-09-01 through 2024-06-30
2024-09-01 through 2025-06-30
2025-09-01 through 2026-06-30
```

To recheck the acquisition plan without downloading:

```powershell
uv run python -m agrisim.data_sources.landsat `
    --fields data/reference/evia_hls_fields.csv `
    --all-dates `
    --workers 4 `
    --plan
```

To process **existing cached windows only** (preferred; no new requests):

```powershell
uv run python -m agrisim.data_sources.landsat `
    --fields data/reference/evia_hls_fields.csv `
    --all-dates `
    --cached-only `
    --workers 4
```

**Do not delete the existing raw HLS cache.** If the software reports grids differing across HLS tiles `T34SGH` and `T34SGJ`, use the previously tested grid-alignment version of `src/agrisim/data_sources/download_evia_hls.py`. The current batch is already produced and should be reused.

### HLS archive schema

```text
field_context.npz
  reflectance      (186, 3, 33, 33), float32  # B03 green, B04 red, B05 NIR
  fmask            (186, 33, 33), uint8
  clear            (186, 33, 33), bool
  candidate_mask   (33, 33), bool             # 9 central 30 m pixels
  dates            (186,)
  granules         (186,)
  bands            (3,) = [B03, B04, B05]
  crs              WKT scalar
  transform        six Affine coefficients
  longitude,latitude
```

The processed HLS batch is on a common **30 m raster grid**. HLS applies its own quality mask before computing vegetation statistics. Its 3×3 candidate mask covers approximately **90 × 90 m**.

## 4. HLS vegetation preprocessing script

This is a reproducible wrapper around the **actual AgriSim package** (`agrisim.timeseries.vegetation_indices.read_hls_batch`), not a substitute for its raster quality logic. Copy to `scripts/preprocess_hls_vegetation.py` if a saved script is useful.

```python
from pathlib import Path
import pandas as pd
from agrisim.timeseries.vegetation_indices import read_hls_batch

BATCH_ROOT = Path("data/processed/evia_sowing/hls_batches")
OUTPUT = Path("data/processed/features/hls_vegetation_observations_all_seasons.csv")

batches = [p for p in BATCH_ROOT.iterdir() if p.is_dir()]
if not batches:
    raise FileNotFoundError(f"No HLS batches in {BATCH_ROOT}")
batch = max(batches, key=lambda p: p.stat().st_mtime)

observations = read_hls_batch(batch)
observations = observations.sort_values(["field_id", "date_utc"])
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
observations.to_csv(OUTPUT, index=False)

print("Batch:", batch.name)
print("Total observations:", len(observations))
print("Non-null NDVI:", int(observations["ndvi_median"].notna().sum()))
print("Source counts:")
print(observations["source"].value_counts().to_string())
print("Coverage by season:")
print(observations.groupby("season").agg(
    acquisitions=("date_utc", "size"),
    clear_ndvi=("ndvi_median", lambda s: int(s.notna().sum())),
).to_string())
print("Saved:", OUTPUT)
```

Run:

```powershell
uv run python scripts/preprocess_hls_vegetation.py
```

Or use the existing CLI directly; note that its default output is `vegetation_observations.csv` and will be overwritten if you rerun it:

```powershell
uv run python -m agrisim.timeseries.vegetation_indices `
    --hls-batch data/processed/evia_sowing/hls_batches/20261114T003254Z-5284ba4b `
    --out data/processed/features/hls_vegetation_observations_all_seasons.csv
```

**Index formulas**, using *unitless surface reflectance*, not raw display pixels:

```text
NDVI = (NIR − Red) / (NIR + Red)
EVI2 = 2.5 × (NIR − Red) / (NIR + 2.4 × Red + 1)
SAVI = 1.5 × (NIR − Red) / (NIR + Red + 0.5)
```

Do not compute SWIR-based NDWI from the current HLS archive: it contains B03/B04/B05 only, not SWIR.

## 5. HLS-only PELT baseline

The package uses **`ruptures.Pelt`**, Savitzky–Golay smoothing, and independent checks on *observed* NDVI/EVI2. Running it by source avoids cross-sensor averaging:

```powershell
uv run python -m agrisim.timeseries.greenup `
    --observations data/processed/features/hls_vegetation_observations_all_seasons.csv `
    --out data/processed/features/hls_greenup_events.csv `
    --method pelt `
    --series-out data/processed/features/hls_smoothed.csv
```

Earlier results: retrospective spectral green-up candidates in **2020–2021**, **2022–2023**, **2024–2025**; no confirmed detection in the other three seasons. These are retrospective **spectral** transitions, not verified crop emergence.

---

# Part B — ESA Sentinel-2 preprocessing

## 6. Acquisition scripts and band layout

Current Python entry point: `agrisim.data_sources.sentinel2` (delegates to `download_sentinel2_series.py`, which calls `download_sentinel2.py`).

Plan acquisition:

```powershell
uv run python -m agrisim.data_sources.sentinel2 `
    --start 2024-09-01 `
    --end 2025-06-30 `
    --site evia_pilot `
    --lon 23.43232 `
    --lat 38.75920 `
    --max-cloud 80 `
    --max-days 150 `
    --min-gap-days 1
```

Download (already completed for 2024–2025; **do not rerun unless needed**):

```powershell
uv run --env-file .env python -m agrisim.data_sources.sentinel2 `
    --start 2024-09-01 `
    --end 2025-06-30 `
    --site evia_pilot `
    --lon 23.43232 `
    --lat 38.75920 `
    --max-cloud 80 `
    --max-days 150 `
    --min-gap-days 1 `
    --download
```

Each dated GeoTIFF uses **EPSG:32634**, **10 m** resolution, **99 × 99** pixels, with these **five FLOAT32 bands**:

| Band number | Name | Meaning |
|---|---|---|
| 1 | `B03_green` | Surface green reflectance |
| 2 | `B04_red` | Surface red reflectance |
| 3 | `B08_nir` | Surface near-infrared reflectance |
| 4 | `SCL` | ESA scene classification |
| 5 | `dataMask` | Data validity mask |

The TIFFs contain no descriptive band labels; the corresponding **`.json` manifest** provides the verified `band_order`. Pixel reflectance is already in the unitless **REFLECTANCE** domain; **do not divide by 10,000 again**. The current conservative SCL mask accepts **class 4 (vegetation)** and **class 5 (non-vegetated)** and excludes water, cloud, shadow, snow, and unknown classes. The STAC scene-cloud percentage is **not** a substitute for local pixel masking.

## 7. Sentinel-2 aligned NDVI/EVI2 script (complete)

The preliminary full-window `sentinel2_vegetation_observations_2024_2025.csv` summarizes all **9,801 pixels**, which is not comparable with the HLS 3×3 footprint. The following code uses raster georeferencing and nearest-neighbor reprojection of the **HLS boolean mask** into each Sentinel-2 window. It then computes indices only for clear Sentinel-2 pixels **inside the common provisional footprint**.

Save this as `scripts/preprocess_sentinel2_aligned.py` or run it as a PowerShell here-string using `@' ... '@ | uv run python -`.

```python
from pathlib import Path
import json
import numpy as np
import pandas as pd
import rasterio
from rasterio.crs import CRS
from rasterio.transform import Affine
from rasterio.warp import reproject, Resampling

ROOT = Path("data/processed/evia_sowing/hls_batches")
BATCH = max((p for p in ROOT.iterdir() if p.is_dir()),
            key=lambda p: p.stat().st_mtime)
HLS_FILE = BATCH / "evia_pilot" / "hls" / "field_context.npz"
S2_DIR = Path("data/raw/sentinel2")
OUT = Path("data/processed/features/sentinel2_aligned_evia_pilot_2024_2025.csv")
EXPECTED = ["B03_green", "B04_red", "B08_nir", "SCL", "dataMask"]

with np.load(HLS_FILE, allow_pickle=False) as z:
    src_mask = z["candidate_mask"].astype("uint8")
    src_transform = Affine(*z["transform"].tolist())
    src_crs = CRS.from_wkt(z["crs"].item())

assert int(src_mask.sum()) == 9, "Inspect unexpected HLS candidate_mask"
rows = []

for tif in sorted(S2_DIR.glob("s2_l2a_*.tif")):
    meta = json.loads(tif.with_suffix(".json").read_text(encoding="utf-8"))
    if meta.get("band_order") != EXPECTED:
        raise ValueError(f"Unexpected Sentinel-2 band order: {tif}")
    if meta.get("is_temporal_mosaic") or meta.get("start_utc") != meta.get("end_utc"):
        continue  # Do not assign multi-day mosaics to a single date.
    date_utc = pd.to_datetime(meta["start_utc"], utc=True).date().isoformat()
    if not ("2024-09-01" <= date_utc <= "2025-06-30"):
        continue

    with rasterio.open(tif) as ds:
        if ds.count != 5:
            raise ValueError(f"Expected 5 bands: {tif}")
        local_mask = np.zeros((ds.height, ds.width), dtype="uint8")
        reproject(
            source=src_mask,
            destination=local_mask,
            src_transform=src_transform,
            src_crs=src_crs,
            dst_transform=ds.transform,
            dst_crs=ds.crs,
            src_nodata=0,
            dst_nodata=0,
            resampling=Resampling.nearest,
        )
        green, red, nir, scl, data_mask = ds.read()

    footprint = local_mask == 1
    total = int(footprint.sum())
    if total == 0:
        raise ValueError(f"HLS candidate footprint does not intersect {tif}")

    valid = (
        footprint
        & (data_mask > 0)
        & np.isin(scl, [4, 5])
        & np.isfinite(green)
        & np.isfinite(red)
        & np.isfinite(nir)
        & (green >= 0)
        & (red >= 0)
        & (nir >= 0)
        & ((nir + red) > 1e-5)
    )
    n = int(valid.sum())
    if n:
        r, n_ir = red[valid].astype("float64"), nir[valid].astype("float64")
        ndvi = (n_ir - r) / (n_ir + r)
        evi2 = 2.5 * (n_ir - r) / (n_ir + 2.4 * r + 1.0)
        ndvi_median, evi2_median = float(np.median(ndvi)), float(np.median(evi2))
    else:
        ndvi_median = evi2_median = float("nan")

    rows.append({
        "field_id": "evia_pilot",
        "season": "2024-2025",
        "date_utc": date_utc,
        "source": "ESA_Sentinel2_L2A",
        "source_granule": tif.stem,
        "spatial_support": "provisional_hls_center_3x3_reprojected",
        "resolution_m": 10,
        "footprint_pixels": total,
        "total_pixels": total,
        "valid_pixels": n,
        "clear_fraction": n / total,
        "ndvi_median": ndvi_median,
        "evi2_median": evi2_median,
    })

result = pd.DataFrame(rows).sort_values("date_utc")
OUT.parent.mkdir(parents=True, exist_ok=True)
result.to_csv(OUT, index=False)

print("HLS mask pixels:", int(src_mask.sum()))
print("Images processed:", len(result))
print("Aligned S2 pixel range:", result.footprint_pixels.min(),
      result.footprint_pixels.max())
print("Dates with NDVI:", int(result.ndvi_median.notna().sum()))
for cutoff in (0.50, 0.80, 0.90):
    eligible = result.ndvi_median.notna() & (result.clear_fraction >= cutoff)
    print(f"Dates >={cutoff:.0%} clear: {eligible.sum()}")
print("Saved:", OUT)
```

Run:

```powershell
uv run python scripts/preprocess_sentinel2_aligned.py
```

**Measured output:** 107 images; fixed 81-pixel footprint; 67 dates with NDVI; 64 ≥50% clear; 62 ≥80% clear; 60 ≥90% clear.

> **Spatial limitation:** Reprojecting the 30 m *mask* to the 10 m grid makes both measurements refer to approximately the same ground footprint, but edge-pixel choices, point-spread functions, spectral response, atmospheric correction, and spatial resolution still differ. This is a working **candidate** footprint, not a verified parcel geometry.

## 8. Sentinel-2-only PELT (next runnable test)

Build a quality-screened input to the existing `agrisim.timeseries.greenup` implementation. This avoids overwriting the HLS PELT baseline and allows a **Sentinel-2-only** assessment before experimental fusion.

```powershell
@'
from pathlib import Path
import pandas as pd

base = Path("data/processed/features")
df = pd.read_csv(base / "sentinel2_aligned_evia_pilot_2024_2025.csv")
keep = (
    df["ndvi_median"].notna()
    & df["evi2_median"].notna()
    & (df["clear_fraction"] >= 0.80)
)
out = base / "sentinel2_for_pelt_2024_2025.csv"
df.loc[keep].to_csv(out, index=False)
print("High-quality S2 dates:", int(keep.sum()))
print("Saved:", out)
'@ | uv run python -

uv run python -m agrisim.timeseries.greenup `
    --observations data/processed/features/sentinel2_for_pelt_2024_2025.csv `
    --out data/processed/features/sentinel2_greenup_events_2024_2025.csv `
    --method pelt `
    --series-out data/processed/features/sentinel2_smoothed_2024_2025.csv
```

This step has **not yet been run or validated** on your Sentinel-2 series. Inspect the `status`, `pelt_breaks`, and actual observation dates before interpreting results.

**Critical caveat:** The current `greenup.py` `smooth_group()` defaults to `max_gap_days=40`, which means it **may interpolate internally across the known 33-day February gap** for smoothing. This does **not** create actual observations, but can influence breakpoint placement. **Before treating PELT results as robust**, add/propagate a configurable `max_gap_days` and test a stricter cap (e.g. 15–20 days) versus the current 40-day default. Keep reported onset as an interval between genuinely observed dates. Do not use a synthetic daily date as an exact emergence date.

---

# Part C — Sensor comparison (NOT yet harmonized)

## 9. Combined observation file and same-day offsets

Your existing experimental file is:

```text
data/processed/features/vegetation_multisensor_2024_2025.csv
```

It contains **78** rows: **16 HLS** + **62 aligned Sentinel-2**, over **72 unique dates**. Six dates have both sensors with sufficient clear pixels. All six gave lower Sentinel-2 NDVI; median **S2 − HLS = −0.0609**. The same-day differences ranged from approximately **−0.1083** to **−0.0054**.

**Do not treat this CSV as radiometrically harmonized.** The measurements are stored in separate rows with `source`, and should be plotted with separate markers/colors. Do not average same-day HLS and Sentinel-2 values; do not add +0.0609 as an unquestioned correction. There are only six paired dates.

For a reproducible source comparison, use:

```python
from pathlib import Path
import pandas as pd

base = Path("data/processed/features")
hls = pd.read_csv(base / "vegetation_observations.csv")
s2 = pd.read_csv(base / "sentinel2_aligned_evia_pilot_2024_2025.csv")
hls = hls[hls.season.eq("2024-2025")]

cols = ["date_utc", "ndvi_median", "evi2_median", "clear_fraction", "valid_pixels"]
h = hls.loc[hls.ndvi_median.notna() & hls.clear_fraction.ge(0.8), cols].copy()
s = s2.loc[s2.ndvi_median.notna() & s2.clear_fraction.ge(0.8), cols].copy()

for x, name in ((h, "NASA_HLS"), (s, "ESA_Sentinel2")):
    x["date_utc"] = pd.to_datetime(x["date_utc"]).dt.normalize()
    x["source"] = name

pairs = h.merge(s, on="date_utc", suffixes=("_hls", "_s2"))
pairs["s2_minus_hls_ndvi"] = pairs.ndvi_median_s2 - pairs.ndvi_median_hls
print(pairs[["date_utc", "s2_minus_hls_ndvi"]].to_string(index=False))
print("Paired dates:", len(pairs))
print("Median S2-HLS offset:", pairs.s2_minus_hls_ndvi.median())

combined = pd.concat([h, s], ignore_index=True).sort_values(["date_utc", "source"])
out = base / "vegetation_multisensor_2024_2025.csv"
combined.to_csv(out, index=False)
print("Rows:", len(combined), "Unique dates:", combined.date_utc.nunique())
print("Saved:", out)
```

**Important:** The current `greenup.py` groups by `(field_id, season, source)`. The compact comparison code above only retains common metric columns and is for **bias/coverage diagnostics**, not directly for passing to `greenup.py`. Use the full-column quality-screened Sentinel-2 CSV in §8 for the immediate PELT test. If creating a true combined PELT input, preserve field/season provenance and explicitly decide how to account for sensor differences.

### Observation coverage and interpretation

On the aligned, quality-screened time series, high-quality measurements are:

```text
2025-01-29  Sentinel-2  NDVI ≈ 0.3002
2025-02-01  Sentinel-2  NDVI ≈ 0.3003
2025-03-06  HLS         NDVI ≈ 0.3954
2025-03-08  Sentinel-2  NDVI ≈ 0.4026
```

The **33-day gap** from February 1 to March 6 is still unresolved. The observed rise is consistent with vegetation development, but its precise onset, crop species, sowing date, and cause are unknown.

---

# Part D — Remaining work (in priority order)

## 10. Next steps and acceptance criteria

### Priority 1 — Validate Sentinel-2-only PELT

- [ ] Run the quality-screened Sentinel-2-only command in §8.
- [ ] Check observed dates near each proposed breakpoint, particularly February/March.
- [ ] Test sensitivity to ≥50%, ≥80%, and ≥90% clear-pixel thresholds, and Savitzky–Golay windows.
- [ ] Expose a configurable interpolation `max_gap_days`; rerun with a conservative gap cap and compare results.
- [ ] Save the underlying observations, PELT break indices, run parameters, plots, and uncertainties. A PELT break is **not** an independently verified crop-emergence date.

**Done when:** Results are reproducible from saved images; gap sensitivity and date uncertainty are explicitly reported.

### Priority 2 — Improve sensor harmonization and compare against HLS

- [ ] Compare the six existing same-day pairs in **both NDVI and EVI2**.
- [ ] Inspect same-day images and masks; evaluate whether edge pixels or clear-pixel mismatches explain offsets.
- [ ] Compare Sentinel-2-only PELT against HLS-only PELT independently first.
- [ ] If fusion is necessary, test robust or season-aware harmonization against held-out same-day matches and quantify uncertainty. Six matched dates are insufficient to claim a reliable universal correction.
- [ ] Never mix the original **990 × 990 m Sentinel-2** statistics with the **90 × 90 m HLS** series.

**Done when:** Sensor-specific biases are assessed, fusion does not create artificial transitions, and source provenance is preserved.

### Priority 3 — Download NASA SRTM elevation and derive terrain features

The existing project includes an SRTM downloader; verify its CLI first:

```powershell
uv run python -m agrisim.data_sources.download_srtm --help
```

The original module accepts `--limit` (defaults to 12) and requires NASA Earthdata authentication via `.netrc`:

```powershell
uv run python -m agrisim.data_sources.download_srtm --limit 12
```

Expected source: **NASA SRTMGL1.003**, approximately **30 m** terrain elevation. Verify whether the downloader retrieves files over the intended configured study-area bounding box. Derive elevation, slope and aspect; do not label a simple slope proxy as a calibrated runoff or erosion model.

**Done when:** DEM coverage and CRS are verified, nodata is handled, and slope/aspect statistics are reproducible over the study area.

### Priority 4 — Complete meteorological and soil-water time series

- [ ] **IMERG:** Check actual coverage of `data/raw/imerg_daily/2025.parquet`; the last verified status was **273/365 dates** through September 30, 2025. Re-run the downloader if the final quarter is still missing; separately extend to earlier growing seasons as warranted.
- [ ] **SMAP:** Current pilot archive is `data/processed/evia_sowing/smap/smap_daily.csv`, **306 complete dates** covering two Sep–Jan periods. Extend historical dates only after changing the source module's hard-coded pilot periods.
- [ ] **POWER:** Existing daily weather files are available. Use past-only feature windows for prospective sowing recommendations; don't leak future rainfall into features.
- [ ] Join by **UTC calendar date**, distinguish missing from zero rainfall and record each product's spatial scale. SMAP's coarse cell must not be presented as a 90 m field measurement.

**Done when:** Dataset coverage by season, missingness and spatial resolution are documented before feature engineering.

### Priority 5 — Extend Sentinel-2 to the remaining five seasons

- [ ] Download per-date Sentinel-2 L2A scenes for 2020–2021, 2021–2022, 2022–2023, 2023–2024, and 2025–2026, subject to service availability/quotas.
- [ ] Reuse `scripts/preprocess_sentinel2_aligned.py` with a **season-aware** date filter and output naming (the example in §7 is intentionally limited to 2024–2025).
- [ ] Validate monthly coverage and PELT stability individually by season; do not assume all seasons have 62 clear dates.
- [ ] Optionally retrieve the **11 NASA-only HLS** scenes directly from official NASA sources, keeping their provenance separate and never claiming they came from the mirror.

### Priority 6 — Agricultural suitability and product integration

- [ ] Add **FAO GAEZ** suitability layers with documented crop, assumptions, grid resolution and licensing/access constraints.
- [ ] Combine vegetation, POWER, IMERG, SMAP and terrain-derived features in a date-safe pipeline.
- [ ] Expose exploratory water/sowing windows, confidence indicators and data provenance in the Streamlit application.
- [ ] Obtain **independently verified parcel polygons**, real crop identities, sowing dates and crop outcomes before attempting supervised emergence/yield labels or declaring model accuracy.

## 11. Immediate command checklist

```powershell
# A. Check the existing HLS processed coverage
Import-Csv "data/processed/evia_sowing/hls_batches/20261114T003254Z-5284ba4b/field_coverage.csv" |
    Format-Table -AutoSize

# B. Produce/reproduce HLS vegetation features
uv run python -m agrisim.timeseries.vegetation_indices `
    --hls-batch data/processed/evia_sowing/hls_batches/20261114T003254Z-5284ba4b `
    --out data/processed/features/hls_vegetation_observations_all_seasons.csv

# C. After saving the code from §7:
uv run python scripts/preprocess_sentinel2_aligned.py

# D. Build the Sentinel-2 PELT input and run PELT as in §8

# E. Preview SRTM CLI, then acquire terrain once ready
uv run python -m agrisim.data_sources.download_srtm --help
```

## 12. GitHub workflow and documentation

The code you actively run is in `D:\AgriSim\AgriSim-AI`, while the Git repository used earlier was `D:\AgriSim\agri_sim`. Copy approved source changes and this guide into the **actual Git clone** before committing. Do not stage raw imagery, credentials or generated large datasets.

Suggested destination in the repository:

```text
docs/HLS_SENTINEL2_PREPROCESSING.md
```

Then:

```powershell
cd D:\AgriSim\agri_sim
git switch feature/agrisim-ai-architecture
git status
git add docs/HLS_SENTINEL2_PREPROCESSING.md
git commit -m "Document HLS and Sentinel-2 preprocessing workflow"
git push origin feature/agrisim-ai-architecture
```

If saving the optional scripts from this guide as `.py` files, stage them too after reviewing their paths and validating locally. These snippets document **reproducible processing**, not a claim that the future experiments (multisensor harmonization, stricter-gap PELT, SRTM integration) have already succeeded.
