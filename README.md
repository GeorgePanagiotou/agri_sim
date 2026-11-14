# AgriSim AI — Field Shift 2026

A modular, **non-MobileNet** decision-support prototype for rainfed crop rotations and sowing-week checks in North Evia, Greece. Uses only datasets named in the NASA Space Apps 2026 **Field Shift** challenge resources or ESA/FAO partner resources supplied in the challenge. NASA HLS Landsat and ESA Sentinel-2 imagery support NDVI/EVI2 phenology, environmental data support historical as-of-date assessment, and crop scenarios are explicitly farmer-editable.

## Setup (Windows / Python 3.11 / uv)

```powershell
cd AgriSim-AI
uv sync --extra app --extra notebooks
uv run pytest -q
uv run python -m agrisim.pipelines.download --list
uv run python -m agrisim.data_sources.power --help
uv run python -m agrisim.data_sources.landsat --help
uv run python -m agrisim.data_sources.sentinel2 --help
```

To check **RTX 5070 / 5070 Ti** with CUDA PyTorch, use `uv sync --extra gpu` and `uv run --extra gpu python scripts/check_gpu.py`. See [GPU setup](docs/gpu_setup.md). CUDA is optional; XGBoost / temporal analysis works on CPU first.


## Reproducible pilot preprocessing (no one-off script edits)

Once your North Evia NASA/ESA/FAO raw data have been downloaded, the following **local-only** commands rebuild the HLS indices, PELT events, footprint-aligned Sentinel-2 indices, SRTM terrain, optional ECOSTRESS raw overpasses and six-season multisource environmental table:

```powershell
uv run python -m agrisim.pipelines.prepare_multisource --plan
uv run python -m agrisim.pipelines.prepare_multisource --min-clear 0.8
uv run pytest -q
```

The command does not redownload imagery or touch raw/credential files; it **does regenerate** processed feature outputs. For details, input paths and scientific limitations see [Reproducible Preprocessing](docs/REPRODUCIBLE_PREPROCESSING.md).

## NASA GPM IMERG (local .env token)

The IMERG daily downloader loads `EARTHDATA_TOKEN` from the **repository-root**
`.env` file, using `python-dotenv` and `earthaccess.login(strategy="environment")`.
**Never** commit `.env` or share its token. If a token was exposed, revoke it
and create a replacement through Earthdata Login.

Create `.env` using `.env.example` as a template and set:

```dotenv
EARTHDATA_TOKEN=your_NEW_private_Earthdata_token
```

Start with exactly one downloaded day, without publishing a dataset:

```powershell
uv sync
uv run python -m agrisim.data_sources.download_imerg_daily --first-year 2023 --smoke-test
```

Then download a complete calendar year:

```powershell
uv run python -m agrisim.data_sources.download_imerg_daily --first-year 2023 --last-year 2023 --workers 2
```

This script now uses current CMR-discovered Earthdata Cloud granule URLs, **not**
the retired on-premises `gpm1.gesdisc.eosdis.nasa.gov` host. It downloads
full global daily NetCDF4 files temporarily, extracts only the nearby North
Evia 0.1-degree rainfall cells, and removes the global files. Allow adequate
download bandwidth. Small annual Parquet files remain resumable. NASA IMERG
Final Daily V07 precipitation is in mm/day; its coarse pixels are not farm
measurements.

**A valid token does not bypass a required GES DISC EULA/app authorization.**
If the smoke test reports `EulaNotAccepted`, review any outstanding agreements
and authorized apps in your Earthdata account and retry after approval.

## Main pipeline (after downloading NASA data)

```powershell
uv run python -m agrisim.pipelines.analyze_vegetation --hls-batch data/processed/evia_sowing/hls_batches/YOUR_BATCH --method pelt
uv run python -m agrisim.pipelines.generate_recommendations --skip-vegetation
uv run --extra app streamlit run app/streamlit_app.py
```

Data preparation writes to `data/processed/features`, while outputs go to `outputs`. A verified field boundary is required to call any image statistics **parcel-level**. Your initial location is a provisional 3×3 satellite footprint only.

## Project layout

- `src/agrisim/data_sources/`: reused official-product downloaders. E.g. `download_evia_hls.py` is the original technical implementation, while `landsat.py` is a simpler entry point.
- `preprocessing/`: masks, resampling, temporal joins and short-gap interpolation.
- `timeseries/`: NDVI/EVI2/SAVI, Savitzky–Golay smoothing, genuine `ruptures` PELT and green-up heuristics.
- `features/`: weather, FAO-style reference ET0, bucket water balance, terrain and agronomic context.
- `models/`: optional supervised training for independent farm outcomes using grouped validation. **No fake learned probabilities**.
- `decision_engine/`: field-week screening, risk indicators, rotation ranking, scenario water budgets and evidence fusion.
- `pipelines/`: command-line orchestration; `app/`: Streamlit interface; `notebooks/`: research notebooks.
- `tests/`, `docs/`, `.github/workflows/`: reproducibility.

## What is intentionally unfinished

`timeseries/bfast.py` is **empty**. Full BFAST seasonal/trend structural-break modelling requires a separate validated implementation and longer multi-year series; `PELT` is implemented instead. Several app and ML paths are prototypes; no actual farmer-verified labels are provided. Some remote services require authentication and manual product selection; downloads were not run live here. The case study is a **retrospective demonstration**, not an operational forecast, and the soil-water bucket is uncalibrated.

## Data scope

The repository ignores raw, processed, and large raster files. `data/reference` holds *templates*, not independent labels or confirmed field polygons. Scripts currently use official NASA/ESA/FAO product APIs and some documented mirrors for the **same approved products**. Keep product provenance metadata. For challenge source policy see `configs/data_sources.yaml` and `docs/datasets.md`.

## Source notes

- Challenge: https://www.spaceappschallenge.org/2026/challenges/adapting-farms-with-nasa-data/?tab=resources
- NASA HLS: https://lpdaac.usgs.gov/products/hlsl30v002/
- PyTorch wheels: https://pytorch.org/get-started/previous-versions/
- `uv` PyTorch index configuration: https://docs.astral.sh/uv/guides/integration/pytorch/
