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
| Supervised outcome ML | Code present, not trained | Needs farmer-confirmed outcomes from multiple independent farms |
| Streamlit UI | Working shell | Needs real data, polished interactivity and model integration |
| CI | Workflow present | GitHub Actions needs dependency resolution on GitHub, not tested remotely |
| NVIDIA RTX 5070 Ti | Optional CUDA extra configured | Actual GPU smoke test requires user's Windows PC and NVIDIA driver |

Offline verification covers package syntax, existing controls, retrospective decision logic and core new utilities. Remote APIs and CUDA cannot be validated in this workspace.

## November 14 integrated preprocessing update

The automated local pipeline `python -m agrisim.pipelines.prepare_multisource` now joins the previously tested HLS grid alignment, HLS-only PELT, Sentinel-2 3x3 HLS candidate footprint, SRTM terrain, optional native-unit ECOSTRESS ET, GAEZ five-crop rasters and the six-season regional daily environmental table. Refer to [REPRODUCIBLE_PREPROCESSING.md](REPRODUCIBLE_PREPROCESSING.md). All remote downloads and credentials still require user-side access and were not run in this sandbox.
