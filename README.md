# AgriSim AI

Crop-rotation decision support from NASA Earth observations, NASA Space Apps Challenge 2026
(*Field Shift: Adapting Farms with NASA Data*). Demo region: North Evia, Greece, after the 2021 wildfires.

```
                                                docs/SCOPE.md  high-level scope
data_prep/   download + harmonize data         docs/STORY.md  what we build
engine/      indicators, water, erosion, scores docs/DATA.md   data sources + file contract
app/         Streamlit app                      docs/TASKS.md  tasks, roles, requests
data/        raw (ignored) · processed · reference · output
```

Run (from this folder): `..\.venv\Scripts\streamlit run app/streamlit_app.py`
