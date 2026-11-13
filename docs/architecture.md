# AgriSim AI architecture — implemented as a modular Python package

```mermaid
flowchart TD
 A[Approved NASA/ESA/FAO data] --> B[Quality screening / preprocessing]
 B --> C[Vegetation time series: NDVI / EVI2 / Savitzky-Golay / PELT]
 B --> D[As-of-date weather / soil / terrain features]
 C --> D
 D --> E[Retrospective sowing-week screening]
 D --> F[Crop rotation priority ranking and bucket simulation]
 D --> G[Explainable risk flags]
 E --> H[Evidence fusion]
 F --> H
 G --> H
 H --> I[Streamlit application]
 J[Independent farm outcomes] --> K[Optional supervised ML models]
 D --> K
 K -. validated models only .-> H
```

The `timeseries/bfast.py` module is intentionally empty. The requested figures are archived in `docs/decision_architecture.png` and `docs/end_to_end_pipeline.png` as target diagrams; they depict features not yet validated or deployed. See `docs/implementation_status.md`.

The source downloader implementation files retain original names inside `data_sources` to preserve tested catalog and Earthdata logic. Their short named counterparts (e.g. `power.py`, `landsat.py`) are CLI entrypoints.
