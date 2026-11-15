# AgriSim AI: project submission text

NASA Space Apps Challenge 2026 · **Field Shift: Adapting Farms with NASA Data** · Athens

Video: [agrisim_demo_30s.mp4](agrisim_demo_30s.mp4) · Data links: [DATA_LINKS.md](DATA_LINKS.md) · Code: this
repository (Apache-2.0)

## 1. Summary

In August 2021 a wildfire burned about 50,000 ha of North Evia, Greece, a third of it farmland. Farmers there now
face hotter, drier summers, and erosive autumn storms that hit fields left bare after harvest. **AgriSim AI** turns
free NASA Earth observations into field-level decision support for them.

- **Field history:** for every 30 m field it rebuilds 40 years of crop and fallow history from Landsat.
- **Sowing check:** each week it checks whether conditions favour sowing, using GPM IMERG rainfall, SMAP soil
  moisture and NASA POWER temperature, and explains why.
- **Rotations:** it compares at least three rotations, the farmer's current one included, with the evidence for
  each and its risks.
- **In-season outlook:** machine-learning models trained on the satellite record flag, by spring, which fields
  are on track and which are likely fallow, with honest uncertainty.
- **Any area:** a user can draw a box anywhere. The same pipeline downloads the data, checks whether the rules fit
  that climate, and trains the area's own models. It ran in full on a second area, in Crete.

It supports the farmer's judgement and never replaces it.

## 2. Project details

### What it does and how it works

AgriSim AI is a data pipeline plus a web app (Streamlit) and a climate API (FastAPI).

1. **Field history from space.** Landsat Collection 2 surface reflectance, 1984–2026, is harmonised across Landsat
   5, 7, 8 and 9 into a monthly 30 m NDVI cube. From the yearly NDVI curve, each field pixel gets a land use and,
   for every season, *crop*, *fallow* or *summer crop*. A Landsat dNBR map adds the 2021 burn severity. This
   replaces farm records that do not exist.
2. **Sowing-window and risk engines.** Rules are explainable and past-only: every verdict uses only data available
   that day.
   - **Rain:** GPM IMERG Final, then the near-real-time IMERG Late Run up to yesterday. Late read 20–50 % wetter
     than Final in recent years, so we calibrate it to Final per area.
   - **Soil:** SMAP moisture and soil temperature.
   - **Climate:** NASA POWER temperature and climate normals.
   - **Output:** for each crop and week, *worth checking the field*, *too dry*, *too wet* or *too cold*, with the
     reason. Drought, dry-spell, heavy-rain, heat and frost levels are percentiles against 1991–2020 and 2001–2020.
3. **Terrain, soil and erosion.**
   - NASADEM slope and flow accumulation, plus SoilGrids texture, giving the RUSLE erosion factors.
   - Key finding: September–December bring 58 % of the year's erosive rain, exactly when cereal→fallow fields are
     bare.
4. **Rotations.** The current rotation, as observed by Landsat, is compared with alternatives (legume forage, bee-
   and soil-friendly cover, low water), with FAO GAEZ crop suitability.
5. **Machine learning.** XGBoost models predict spring vigour and crop vs fallow for each field.
   - They are tested on seasons they never saw, against each field's own 5-year history.
   - Before winter they have no skill, and we say so.
   - By 1 March, winter satellite greenness gives real skill: crop-vs-fallow AUC 0.81 vs 0.71 for the baseline in
     Evia, and 0.87 in Crete.
   - Conformal calibration gives honest 80 % ranges.
6. **Any area.** In the Area explorer the user picks or draws a box, then:
   - The pipeline downloads Landsat, IMERG, POWER, NASADEM and soil, and builds the tables and models. It runs in
     the background and can resume.
   - A climate check (Köppen class from NASA POWER normals) tells the user whether the rules apply there.
   - Users sign in to NASA Earthdata inside the app.

### Benefits and intended impact

- Better-timed sowing and fewer failed or eroded fields after the fire, from free, open NASA data that covers every
  field.
- Evidence a farmer, an agronomist or a cooperative can check: every number traces back to a dataset or a cited
  table, with its uncertainty and data gaps.
- Transferable: the same pipeline prepared a second area (Messara, Crete: 70,854 fields) with no code changes. The
  climate check marks where the rules are not yet valid.
- Honest science: the record shows no measurable yield benefit after fallow in Evia, and that the 2021 fire did not
  reduce cropping. We report both rather than assume them.

### Tools, languages, software and hardware

- **Language:** Python 3.11.
- **Data and modelling:** xarray, rasterio, pandas, NumPy, XGBoost, scikit-learn.
- **Interfaces:** Streamlit (app), FastAPI + Docker (climate API).
- **Data access:** earthaccess / NASA CMR and OPeNDAP, Microsoft Planetary Computer STAC (cloud-optimised window
  reads, no bulk downloads).
- **Engineering:** pytest (192 tests), GitHub Actions CI, Playwright (demo recording).
- **Hardware:** ordinary laptops; no GPU needed.
- **AI assistance:** Claude Code helped write pipeline code, tests and documentation.

### What is creative

- **Field histories from space:** 40 years of field histories rebuilt from the Landsat archive where no farm
  records exist.
- **Fresh but consistent rain:** a per-area calibration of IMERG Late to IMERG Final, so the live season is
  comparable with the historical record.
- **Knowing its limits:** a climate-fit check that tells the user when the tool should *not* be trusted.
- **Calibrated honesty:** uncertainty is calibrated, and negative results are reported.

### Factors we considered

- **Farmers decide.** The tool screens; it never says "sow now". Information gaps are flagged for local expert
  review.
- **No look-ahead.** Every feature and verdict uses only data available on the decision date.
- **Scale.** Climate data is regional (km); only Landsat, HLS and terrain resolve a field (30 m). We show that
  difference.
- **Satellite stand-ins.** The targets are not farm records. We validate on unseen seasons and say what is not
  verified.
- **Data latency.** IMERG Final lags 3.5 months, so we fill the gap with Late; POWER lags 2 days.
- **Open licences and privacy.** Data licences are documented, and Earthdata credentials are never stored.
- **Simplicity.** One command or one button from a bounding box to a working area.
