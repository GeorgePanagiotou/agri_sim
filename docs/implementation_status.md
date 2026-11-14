# Implementation status (2026-11-14)

| Subsystem | Status | Notes |
|---|---|---|
| NASA HLSL30, Landsat C2 L2, Sentinel-2, SMAP, GPM IMERG, POWER | Existing acquisition modules migrated | Live remote services not exercised here |
| MODIS, ECOSTRESS, SRTM, ERA5-Land and FAO GAEZ | Data-acquisition/processing entry points present | Some require OAuth/CDS setup or a selected URL |
| NDVI, EVI2, SAVI from reflectance | Implemented | HLS/ESA quality and source checks; no verified labels |
| Savitzky-Golay, PELT | Implemented | Offline tests; PELT runtime requires ruptures installed |
| BFAST | **Empty placeholder** | Separate research/validation needed for multi-year trend/seasonality decomposition |
| Temporal interpolation, as-of joins, vegetation derivatives | Implemented | Short-gap, retrospective only; candidate weather uses past-only features |
| TWI / exact parcel runoff | Not implemented | SRTM terrain sampling only; needs DEM hydrology flow accumulation |
| NDWI using SWIR | Not wired | Current HLS downloads only B03/B04/B05; a product-specific SWIR downloader is needed |
| ET0 / daily water bucket | Prototype | Requires correct unit inputs, crop Kc and local soil storage; not calibrated |
| Crop rotation ranking and water scenarios | Prototype | User-supplied priorities and crop phases, not yield predictions |
| Sowing / drought / temperature risk screening | Working heuristics | Uncalibrated historical regional signals, not forecasts |
| Sowing-window engine v1 | Implemented (2026-11-14) | 7 rotation crops, windows (team draft) + sourced soil-temperature minima in `data/reference/sowing_windows.csv`; 4 tests; [sowing_window.md](sowing_window.md) |
| Sentinel-2 via Planetary Computer | Implemented (2026-11-14) | `download_sentinel2_pc.py`: same ESA L2A product and file format as the CDSE script, no account; 447 dates 2020-2026 |
| FAO GAEZ v4 layers | Downloaded (2026-11-14) | Official URLs from FAO's GAEZ image-service catalogue (res05/CRUTS32/Hist/8110L/suLr_*) |
| Environmental Risk Engine v1 | Implemented (2026-11-14) | Drought, dry spell, heat, frost, heavy rain; sourced thresholds in `configs/risk_rules.yaml`; 12 tests; event checks in [risk_engine.md](risk_engine.md) |
| Supervised outcome ML | Code present, not trained | Needs farmer-confirmed outcomes from multiple independent farms |
| Streamlit UI | Working shell | Needs real data, polished interactivity and model integration |
| CI | Workflow present | GitHub Actions needs dependency resolution on GitHub, not tested remotely |
| NVIDIA RTX 5070 Ti | Optional CUDA extra configured | Actual GPU smoke test requires user's Windows PC and NVIDIA driver |

Offline verification covers package syntax, existing controls, retrospective decision logic and core new utilities. Remote APIs and CUDA cannot be validated in this workspace.

## November 14 integrated preprocessing update

The automated local pipeline `python -m agrisim.pipelines.prepare_multisource` now joins the previously tested HLS grid alignment, HLS-only PELT, Sentinel-2 3x3 HLS candidate footprint, SRTM terrain, optional native-unit ECOSTRESS ET, GAEZ five-crop rasters and the six-season regional daily environmental table. Refer to [REPRODUCIBLE_PREPROCESSING.md](REPRODUCIBLE_PREPROCESSING.md). All remote downloads and credentials still require user-side access and were not run in this sandbox.
