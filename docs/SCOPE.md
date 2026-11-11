# AgriSim AI: high-level scope

*v0.2, 2026-11-11 (v0.1 2026-11-09). Living document: change it when the team decides something, and keep
[STORY.md](STORY.md) (the demo) and [DATA.md](DATA.md) (the data contract) in line with it.*

*v0.2 adds the **sowing-window module** (section 7), the team's proposal of 2026-11-11 (download scripts by Stylianos:
`data_prep/download_evia_hls.py`, `download_evia_smap.py`) and the **Prithvi foundation-model add-on** (section 10.1).
**Status: draft for team review**: the whole design will be reviewed again before the event.*

## 1. In one sentence

AgriSim AI uses 40 years of NASA satellite and climate data to show farmers, livestock keepers and beekeepers in
**fire-affected North Evia** how their land has changed, and lets them compare crop rotations that protect the soil,
save water and rebuild lost income, with the evidence, gaps and risks of each one spelled out.

## 2. Problem and place

- **Event:** the August 2021 North Evia wildfire burned about 50,000 ha. Apart from forest, it burned **farm fields,
  pastures and apiary areas**, and with them income from honey, resin, grazing and crops.
- **After the fire:** bare soil, higher runoff and erosion on and below the burned slopes, loss of bee forage and
  grazing, hotter and drier summers, autumn storms on unprotected ground.
- **Challenge link:** "Field Shift" asks for a decision-support tool that uses NASA Earth observations, soil, crop
  traits and farmer priorities "to help farmers **explore rotation strategies**" (main challenge statement). The
  Objectives add that a tool "**may** compare at least three rotation strategies, including the existing rotation",
  each with why, evidence, benefits, information gaps and risks for local review
  ([challenge page](https://www.spaceappschallenge.org/2026/challenges/adapting-farms-with-nasa-data/)). We follow
  that suggestion.

## 3. Users

| User | Their question |
|---|---|
| **Farmer** with burned or exposed fields | "What do I rotate on this field so it stops losing soil and still pays?" · "Is this the week to check my seedbed?" |
| **Livestock keeper** (goats/sheep) | "How do I replace the grazing and feed I lost?" |
| **Beekeeper** | "Which crops nearby can give my bees forage while the pine forest recovers?" |
| (secondary) Agronomist / municipality | "Where are the hotspots, and what do the data say before I visit?" |

Design for people with little GIS experience: plain language (Greek + English), few clicks, clear warnings.

## 4. Focus areas

**Burned agricultural, pasture and apiary zones** in North Evia. The study area is "Kireas – Agia Anna"
(lon 23.32–23.50, lat 38.75–38.95). The team picks **2–3 specific spots** for the demo, e.g. one burned field in a
valley, one pasture on a slope, one apiary area next to the forest. The sowing-window **pilot field** is one of them
(a confirmed rainfed field interior near the IMERG cell at 38.75 N, 23.45 E).

## 5. What the tool does (core functions)

1. **Where & how bad:** maps the 2021 burn scar and burn severity (Landsat dNBR) and shows the vegetation
   recovery year by year.
2. **Field history:** rebuilds what each field did in the past from **older satellite images** (Landsat back to the
   1980s): winter crop, fallow, summer crop, pasture, perennial. This gives the **current rotation** (strategy A) and
   its typical bare months.
3. **Local conditions:** a seasonal calendar and long-term trends (temperature, heat days, frost, rain, extreme rain,
   ET, soil moisture, water balance) plus slope, soil and erosion risk for the field.
4. **Farmer priorities:** sliders for soil protection, water saving, income, animal feed and bee forage, plus
   constraints (irrigation yes/no, equipment, market).
5. **Rotation comparison:** at least 3 strategies, scored against the priorities. Each gets a card with **why
   suggested · evidence · benefits · information gaps · risks for local review**.
6. **Sowing window (section 7):** for each crop of each strategy, how often and how late a workable sowing week came
   in past years (feeds the comparison). Plus a **"this week" view**: for a chosen date, does the evidence say a
   seedbed check is worth it?
7. **What-if:** climate sliders (+1/+2 °C, −10/−20 % rain) and a "dry year / normal year" switch.

## 6. Rotations (first set, to refine with local input)

| # | Strategy | Main benefit |
|---|---|---|
| A | **Current** (from field history / farmer input), e.g. cereal → summer fallow | Baseline |
| B | **Legume forage**: cereal → vetch–oat / chickpea / lentil | N-fixing, autumn cover, feed |
| C | **Bee & soil**: cereal → sainfoin / clover / phacelia; perennial aromatic strips (oregano, thyme) on slopes | Bee forage, year-round cover, niche market |
| D | **Drought-tolerant / low-water** (optional): barley → chickpea, early sowing | Water saving in dry years |

Sequences: [data/reference/rotations.csv](../data/reference/rotations.csv); crop traits:
[data/reference/crops.csv](../data/reference/crops.csv).

## 7. Sowing window (draft, to review)

**The decision:** *which week deserves a seedbed check before sowing* a rainfed crop. The tool does not say "sow
now". It says which weeks the evidence favours, and why. The farmer checks the field and decides.

**Why it belongs inside the rotation comparison (not a separate tool):** every strategy depends on its crops getting
established in time. Today each crop has one fixed draft sowing date in `crops.csv` (e.g. wheat 15 Nov). The module
replaces it with a **real, year-by-year establishment date**. That date drives the bare-soil months, the erosion score
and the water balance. Sowing timing then becomes part of each strategy's evidence and risk.

### 7.1 How it works

1. **Crop window:** each crop gets a feasible sowing window and a minimum soil temperature, as new columns in
   `crops.csv`: `sow_window_start`, `sow_window_end`, `tsoil_min_c`, with a source and status like the other columns.
   Examples, **to source**: wheat 1 Nov–15 Dec, vetch–oat 15 Oct–30 Nov, phacelia 10 Sep–15 Oct (after the first
   autumn rain).
2. **Weekly evidence**, for every week of the window in every past year:
   - preceding rain (GPM IMERG daily, field cell);
   - surface wetness (NASA POWER GWETTOP since 1981; SMAP L4 `sm_surface` since 2015);
   - soil temperature (SMAP L4 `soil_temp_layer1` since 2015; POWER air temperature as the proxy for the long record);
   - evaporative demand (POWER T2M_MIN/MAX, T2MDEW, WS2M, PS, ALLSKY_SFC_SW_DWN → FAO-56 ET0).
3. **Weekly verdict:** *check-worthy* / *too dry* / *too cold*, with the numbers behind it. The thresholds are rules
   with stated sources, to calibrate (e.g. "≥ X mm in the preceding 10 days and surface wetness above its seasonal
   median").
4. **Output per crop and year:** the first check-worthy week, or "none in the window". The record is ~44 years with
   POWER and 25 with IMERG.

### 7.2 What it changes in the comparison

| Where | Change |
|---|---|
| **New sub-score: establishment reliability** | For each strategy: the share of years each crop got a workable week inside its window, and how late (median / worst years) |
| **Crop calendar → bare months → erosion (RUSLE C)** | The simulation uses each year's establishment date. Late establishment = bare soil in Oct–Dec, when ~37 % of the year's rain falls (IMERG 2001–2024). This is the Evia story: bare soil under autumn storms |
| **Water balance** | The crop's Kc curve starts at the real establishment date |
| **Strategy cards** | Evidence / risk / gap lines come straight from the module |

It separates the strategies: phacelia in C needs the first September rain (fragile in dry autumns) while sainfoin
establishes once and covers the soil for 3 years; D depends on early rain; B's vetch–oat has an earlier window than
wheat.

Example card text (numbers invented):
> **B · Legume forage.** *Evidence:* vetch–oat had a workable week by 15 Nov in 19 of 25 years. In 2024 the first one
> was 15–21 Nov, after two dry weeks. *Risk for local review:* in 3 of the last 10 years there was no workable week
> before 1 Dec; a late-sown forage mix may miss the feed deadline. *Gap:* establishment times are FAO estimates, and
> no grower records exist yet.

### 7.3 The "this week" view (demo)

Pick a date and see the evidence for each crop. **Example, checked against our data (IMERG cell 38.75 N, 23.45 E):**
1–7 Nov 2024 had 0.0 mm (two dry weeks in a row). 8–14 Nov had 15.2 mm (area mean ~17 mm), almost all of it from
12 Nov. POWER surface wetness rose from 0.33 to 0.60. A farmer looking on **8 Nov** and on **15 Nov** had different
evidence for the same field and crop.

The view uses **past observations only**: no weather forecast. A real-time version would need a forecast feed; that
is out of scope.

### 7.4 Checking against reality (green-up dating)

- **Observed establishment:** date visible green-up at confirmed field interiors from per-scene **HLS L30** NDVI
  (B04 red, B05 NIR, Fmask; ~8-day revisit with Landsat 8 + 9). Compare it with the predicted sowing week plus the
  crop's establishment time (`len_ini`).
- **Method for the hackathon:** an NDVI threshold / curve rule (explainable, needs no labels). Autumn cloud leaves gaps
  of 1–3 weeks, so each green-up date comes with a range.
- **MobileNetV3** (CNN dating of green-up from image chips) is the planned next step. It needs dated labels
  (`labels_template.csv`) from grower records and field visits, which we don't have. We describe it, but don't claim
  it works.

### 7.5 Data

| Need | Source | Status |
|---|---|---|
| Per-scene field reflectance, green-up | HLS **HLSL30 v2.0** (B03, B04, B05, Fmask, acquisition dates, tile IDs), clipped to field interiors in the study box | script `download_evia_hls.py`, to run |
| Seedbed moisture + soil temperature | SMAP **SPL4SMGP.008** `sm_surface`, `soil_temp_layer1` (K → °C), point at each field, valid-reading counts; 9 km = regional context | script `download_evia_smap.py` (point) and AppEEARS task (all cells), pending |
| Rain | GPM IMERG Final daily (GPM_3IMERGDF v07) | have, to 2025-09 |
| Surface wetness, evaporative demand | NASA POWER daily AG: GWETTOP, T2M_MIN/MAX, T2MDEW, WS2M, PS, ALLSKY_SFC_SW_DWN | have, 1981–2026 |
| Soil, terrain, fields, crops | SoilGrids (texture, AWC), NASADEM, Landsat field map / history, `crops.csv`, `rotations.csv` | have |
| **Grower records** | field boundaries, crop/mixture, rotation year, actual sowing date, irrigation, reseeding, weeds, grazing, feasible windows, constraints (machinery, feed deadlines) | **not available**: template + stated gap |
| **Field observations** | dated visits / photos before and after green-up (field ID, crop, observer), incl. delayed or failed establishment; soil sensor readings with date, units, depth | **not available**: template + stated gap |

Before the scripts run: add `SOWING_LAT`, `SOWING_LON`, `SOWING_SEASONS` to `config.py` (pilot point from a
confirmed field interior on `landsat_field_map_30m.tif`), and switch the SMAP script's login to `~/_netrc` like the
other scripts.

## 8. Data (high level, details in DATA.md)

- **NASA core:** Landsat (5/7/8/9, 30 m, 1984 onwards), HLS L30 (per-scene Landsat 8/9, 30 m), MODIS (NDVI, ET, LST,
  burned area), GPM IMERG (rain, extremes), SMAP (soil moisture, soil temperature), NASA POWER (daily climate since
  1981), NASADEM (slope), ECOSTRESS (dry-season ET), GRACE / GRACE-FO (regional water trend, context only).
  Product data is NASA/USGS only (team rule). Sentinel-2, WorldCover and EFFIS were used in exploration only.
- **Supporting data:** SoilGrids (soil), FAO tables (crops).
- **More detailed data, to search for:** ground weather stations (meteo.gr / NOA, HNMS) to check the satellite data,
  municipal livestock and crop statistics (ELSTAT).
- **Local knowledge:** what is grown, where the beehives and pastures are, prices/markets, sowing dates. From
  contacts, if possible.
- **Crop traits table:** FAO-56 crop coefficients and season lengths, sowing windows, FAO ECOCROP, cover by month,
  N-fixing, root depth, bee value, forage value, with a source for every value.

## 9. Method (high level)

```
download ─► harmonize to a common grid (30 m for land, climate as point/zone values)
        ─► indicators (climate calendar, water balance, erosion risk, NDVI recovery)
        ─► field history (classify yearly NDVI curves → crop / fallow / pasture)
        ─► sowing window (per crop and year: first workable week → establishment date)
        ─► rotation simulation (month by month from the establishment date: soil cover, water need, erosion, N,
           forage, bee forage)
        ─► scoring by farmer priorities ─► explanation cards + uncertainty
```

- **Water:** FAO-56 water balance (ET0 from POWER × crop coefficient vs. rain and soil water storage); check
  against SMAP and MODIS ET.
- **Erosion:** RUSLE (rain erosivity from GPM, soil from SoilGrids, slope from DEM, cover from NDVI and the
  rotation calendar). The rotation and its establishment dates change the cover factor month by month.
- **Sowing window:** rule-based weekly verdicts (section 7). Thresholds sourced and shown.
- **Scoring:** transparent weighted score; each sub-score (incl. establishment reliability) shown separately, never
  only a single number.

## 10. Where AI is used (and kept explainable)

| Use | Method (candidate) | Why it is explainable |
|---|---|---|
| Field history: crop / fallow / pasture per year | Classify yearly NDVI curves (random forest or clustering) | Shows the NDVI curve behind each label |
| Bare-soil and stress periods | Detect seasonal transitions in NDVI / soil moisture | Marked on the timeline |
| Green-up dating (checks the sowing window) | NDVI threshold / curve rule on HLS L30 now; MobileNetV3 on image chips once dated labels exist | Shows the dated images and NDVI points around the green-up |
| Year types (normal / dry / hot) | Cluster climate years | Shows which years fall in each group |
| Burn map cross-check (add-on) | **Prithvi-EO** burn-scar model, inference only (10.1) | Shown next to dNBR and MODIS; agreement and disagreement mapped |
| "Fields like yours" (stretch) | **Prithvi-EO** frozen-encoder embeddings + clustering / nearest fields (10.1) | Shows the NDVI curves of the matched fields, not only a similarity score |
| Plain-language explanations (GR/EN) | Language model, given only the computed numbers | Every sentence cites a number and a source |

The core (water balance, erosion, sowing-window rules, scoring) stays rule-based so every result can be traced.

### 10.1 Prithvi (NASA–IBM foundation model)

**Prithvi-EO-2.0** is a vision transformer (300M / 600M parameters) pretrained by NASA and IBM on 4.2 M global
**HLS 30 m** time series, the same data family we use ([arXiv 2412.02732](https://arxiv.org/abs/2412.02732)). Input:
6 HLS bands (Blue, Green, Red, NIR narrow, SWIR1, SWIR2; for L30 = B02–B07), image chips of 224 × 224 px (~6.7 km),
one or more dates. Fine-tuning and inference with **TerraTorch** (Apache 2.0).

| Use | What we do | Labels needed | Priority |
|---|---|---|---|
| **Burn map cross-check** | Run a published burn-scar fine-tune on post-fire HLS L30 scenes (Aug–Sep 2021) over the study area; compare with Landsat dNBR and MODIS MCD64A1 (agreement map, % area each method flags) | none | **add-on**: first after the core works |
| **"Fields like yours"** | Frozen encoder → one embedding per field and season; cluster / nearest fields; helps field history and later carries grower records to similar fields | none (validated against our NDVI field-history classes) | stretch |
| Crop type / green-up dating | Fine-tune on local labels | yes, which we don't have | out (same gap as MobileNetV3) |

- **Rule-based core stays.** Prithvi checks and enriches. It never makes the recommendation, so every number still
  traces back to a dataset.
- **Transfer risk:** the published burn-scar fine-tunes were trained on US fires; the Evia comparison is itself the
  test, and we report it as such.
- **Practical:** PyTorch + TerraTorch (a few GB) and the weights (~1–2 GB) live outside git. Inference runs on CPU
  (slow, fine for a few chips); fine-tuning would need a GPU (out of scope).
- **Data:** the HLS script downloads 33 × 33 px windows of B03/B04/B05/Fmask only. Prithvi needs a second, small
  download: the 6 bands + Fmask as 224 × 224 chips, a few post-fire 2021 scenes (+ field-interior chips per season for
  the stretch use). Download = data prep (allowed before the event); running the model = building (at the event).
- **To check before use:** the weights licence on the Hugging Face model card; which burn-scar fine-tune exists for
  v2.0 (v1.0 has one); the model's band order and normalization.
- **Not used: Prithvi WxC** (2.3 B parameters, MERRA-2, [arXiv 2409.13598](https://arxiv.org/abs/2409.13598)). It
  could downscale weather, but weather resolution is not our bottleneck, and it needs a GPU.

## 11. In scope / out of scope

**In scope**
- North Evia, 2–3 demo spots, pre-computed results.
- At least 3 rotations including the current one, with evidence, gaps and risks.
- Sowing-window evidence for the rainfed crops of each strategy (past years) and the "this week" view on past dates.
- Burn-scar map and recovery, field history, climate trends, what-if sliders.
- Add-on once the core works: Prithvi-EO burn map cross-check (inference only); stretch: "fields like yours".
- Clear uncertainty, data-resolution notes and "check with your agronomist" prompts.

**Out of scope (for the hackathon)**
- Forest restoration planning, replanting the burned forest.
- Yield or price forecasts, financial advice.
- Weather forecasts / real-time sowing advice.
- Training MobileNetV3 (no labels yet); fine-tuning Prithvi; Prithvi WxC.
- Live data download in the app, user accounts, database.
- Coverage of all of Greece. (The method should transfer to other areas; we say so but don't build it.)

## 12. Uncertainty and human judgment

- Show the **native resolution** of every layer (e.g. "rain: 10 km cell, your field is one small part of it";
  "soil moisture: 9 km, regional context, not your seedbed").
- Mark **assumptions** (e.g. the current rotation detected from images, not confirmed by the farmer; establishment
  times from FAO tables, not grower records).
- Every strategy card lists **information gaps** and **risks for local review** (pests, markets, seed availability,
  grazing pressure, regulations, machinery access, feed deadlines).
- Known data issue: SMAP L3 2025 reads too low (see
  [exploration/2026-11-11_smap_check](../exploration/2026-11-11_smap_check/SMAP_CHECK.md)).
- The tool suggests options. The farmer and a local agronomist decide.

## 13. Deliverables

- Streamlit app (demo on pre-computed data for the 2–3 spots).
- Short docs in `docs/` and a README.
- Pitch material: video/slides per the Space Apps submission rules (**to check**: format, length; guides published
  13 Nov).
- Data sources and credits list, plus a list of what was reused from SeaGuard if the rules require it.

## 14. Team (proposal)

| Person | Part |
|---|---|
| 1 | Data: downloads, harmonization, data checks, field history |
| 2 | Engine: indicators, water balance, erosion, sowing window, crop table, scoring |
| 3 | App + story: Streamlit, visuals, pitch |

All three of us work on data, so the first phase is shared: find, download and check the datasets.

## 15. Phases

1. **Data look:** download and check the first layers (POWER, Landsat around the fire, GPM, DEM); confirm the
   key insight (bare months vs. erosive autumn rain). *Done before the event.*
2. **Pick spots:** choose the 2–3 demo spots and the sowing pilot field on the burn map; rebuild their field
   history; run the HLS / SMAP L4 downloads and the Prithvi HLS chips (6 bands, post-fire 2021).
3. **Engine:** crop table (incl. sowing windows), sowing window, water balance, erosion, scoring, explanations.
4. **App:** map, field page, comparison, "this week" view, what-if.
5. **Story:** video/slides, final checks, submission.

## 16. Success criteria (from the brief)

- [ ] Uses several NASA datasets, and explains what each adds.
- [ ] Compares at least 3 rotations, including the current one.
- [ ] Each strategy: why, evidence, benefits, gaps, risks.
- [ ] Farmer priorities change the result.
- [ ] Understandable without GIS skills; supports, never replaces, local expertise.
- [ ] Shows bare-field periods and vulnerable seasons.

## 17. Open questions

- Judging criteria and submission format (published 13 Nov), Resources tab.
- The exact demo spots and the sowing pilot field (burned fields, pastures, apiaries).
- Sowing windows, minimum soil temperatures and the weekly thresholds: which sources (FAO, Greek extension guides,
  local agronomists)?
- How many seasons the pilot covers (`SOWING_SEASONS`).
- A local contact (farmer, beekeeper, agronomist) to confirm the current rotations and sowing dates.
- Which AI components we actually build in the time we have.
- Prithvi: weights licence, a v2.0 burn-scar fine-tune or v1.0, CPU inference time on our laptops.
