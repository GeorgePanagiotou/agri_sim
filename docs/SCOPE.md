# AgriSim AI: high-level scope

*v0.1, 2026-11-09. Living document: change it when the team decides something, and keep [STORY.md](STORY.md) (the
demo) and [DATA.md](DATA.md) (the data contract) in line with it.*

## 1. In one sentence

AgriSim AI uses 40 years of NASA satellite and climate data to show farmers, livestock keepers and beekeepers in
**fire-affected North Evia** how their land has changed, and lets them compare crop rotations that protect the soil,
save water and rebuild lost income, with the evidence, gaps and risks of each one spelled out.

## 2. Problem and place

- **Event:** the August 2021 North Evia wildfire burned about 50,000 ha. Apart from forest, it burned **farm fields,
  pastures and apiary areas**, and with them income from honey, resin, grazing and crops.
- **After the fire:** bare soil, higher runoff and erosion on and below the burned slopes, loss of bee forage and
  grazing, hotter and drier summers, autumn storms on unprotected ground.
- **Challenge link:** "Field Shift" asks for a decision-support tool that combines NASA Earth observations, soil, crop
  traits and farmer priorities to compare **at least 3 rotation strategies, including the current one**.

## 3. Users

| User | Their question |
|---|---|
| **Farmer** with burned or exposed fields | "What do I rotate on this field so it stops losing soil and still pays?" |
| **Livestock keeper** (goats/sheep) | "How do I replace the grazing and feed I lost?" |
| **Beekeeper** | "Which crops nearby can give my bees forage while the pine forest recovers?" |
| (secondary) Agronomist / municipality | "Where are the hotspots, and what do the data say before I visit?" |

Design for people with little GIS experience: plain language (Greek + English), few clicks, clear warnings.

## 4. Focus areas

**Burned agricultural, pasture and apiary zones** in North Evia. The team picks **2–3 specific spots** for the demo,
e.g. one burned field in a plain, one pasture on a slope, one apiary area next to the forest. Candidate areas: the
Istiaia plain edge, the Mantoudi/Kireas valley, the hills around Limni and Agia Anna (to confirm on the burn map).

## 5. What the tool does (core functions)

1. **Where & how bad:** maps the 2021 burn scar and burn severity (Landsat/HLS dNBR) and shows the vegetation
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
6. **What-if:** climate sliders (+1/+2 °C, −10/−20 % rain) and a "dry year / normal year" switch.

## 6. Rotations (first set, to refine with local input)

| # | Strategy | Main benefit |
|---|---|---|
| A | **Current** (from field history / farmer input), e.g. cereal → summer fallow | Baseline |
| B | **Legume forage**: cereal → vetch–oat / chickpea / lentil | N-fixing, autumn cover, feed |
| C | **Bee & soil**: cereal → sainfoin / clover / phacelia; perennial aromatic strips (oregano, thyme) on slopes | Bee forage, year-round cover, niche market |
| D | **Drought-tolerant / low-water** (optional): barley → chickpea, early sowing | Water saving in dry years |

## 7. Data (high level, details in DATA.md)

- **NASA core:** Landsat (5/7/8/9, 30 m, 1984 onwards), HLS (Landsat + Sentinel-2 harmonized, 30 m, 2013 onwards),
  MODIS (NDVI, ET, burned area), GPM IMERG (rain, extremes), SMAP (soil moisture), NASA POWER (daily climate since
  1981), NASADEM/SRTM (slope), ECOSTRESS (heat, optional), GRACE-FO (regional water trend, context only).
- **More detailed data, to search for:** fire perimeter and severity maps (EFFIS, Copernicus EMS), 10 m land cover
  (ESA WorldCover, CORINE), Sentinel-2 at 10 m, soil (SoilGrids, ESDAC/LUCAS, RUSLE layers), ground weather stations
  (meteo.gr / NOA, HNMS) to check the satellite data, municipal livestock and crop statistics (ELSTAT).
- **Local knowledge:** what is grown, where the beehives and pastures are, prices/markets. From contacts, if possible.
- **Crop traits table:** about 8–10 crops (FAO-56 crop coefficients and season lengths, FAO ECOCROP, cover by month,
  N-fixing, root depth, bee value, forage value), with a source for every value.

## 8. Method (high level)

```
download ─► harmonize to a common grid (30 m for land, climate as point/zone values)
        ─► indicators (climate calendar, water balance, erosion risk, NDVI recovery)
        ─► field history (classify yearly NDVI curves → crop / fallow / pasture)
        ─► rotation simulation (month by month: soil cover, water need, erosion, N, forage, bee forage)
        ─► scoring by farmer priorities ─► explanation cards + uncertainty
```

- **Water:** FAO-56 water balance (ET0 from POWER × crop coefficient vs. rain and soil water storage); check
  against SMAP and MODIS ET.
- **Erosion:** RUSLE (rain erosivity from GPM, soil from SoilGrids/ESDAC, slope from DEM, cover from NDVI and the
  rotation calendar). The rotation changes the cover factor month by month.
- **Scoring:** transparent weighted score; each sub-score shown separately, never only a single number.

## 9. Where AI is used (and kept explainable)

| Use | Method (candidate) | Why it is explainable |
|---|---|---|
| Field history: crop / fallow / pasture per year | Classify yearly NDVI curves (random forest or clustering) | Shows the NDVI curve behind each label |
| Bare-soil and stress periods | Detect seasonal transitions in NDVI / soil moisture | Marked on the timeline |
| Year types (normal / dry / hot) | Cluster climate years | Shows which years fall in each group |
| Plain-language explanations (GR/EN) | Language model, given only the computed numbers | Every sentence cites a number and a source |

The core (water balance, erosion, scoring) stays rule-based so every result can be traced.

## 10. In scope / out of scope

**In scope**
- North Evia, 2–3 demo spots, pre-computed results.
- At least 3 rotations including the current one, with evidence, gaps and risks.
- Burn-scar map and recovery, field history, climate trends, what-if sliders.
- Clear uncertainty, data-resolution notes and "check with your agronomist" prompts.

**Out of scope (for the hackathon)**
- Forest restoration planning, replanting the burned forest.
- Yield or price forecasts, financial advice.
- Live data download in the app, user accounts, database.
- Coverage of all of Greece. (The method should transfer to other areas; we say so but don't build it.)

## 11. Uncertainty and human judgment

- Show the **native resolution** of every layer (e.g. "rain: 10 km cell, your field is one small part of it").
- Mark **assumptions** (e.g. the current rotation detected from images, not confirmed by the farmer).
- Every strategy card lists **information gaps** and **risks for local review** (pests, markets, seed availability,
  grazing pressure, regulations).
- The tool suggests options. The farmer and a local agronomist decide.

## 12. Deliverables

- Streamlit app (demo on pre-computed data for the 2–3 spots).
- Short docs in `docs/` and a README.
- Pitch material: video/slides per the Space Apps submission rules (**to check**: format, length, deadline).
- Data sources and credits list, plus a list of what was reused from SeaGuard if the rules require it.

## 13. Team (proposal)

| Person | Part |
|---|---|
| 1 | Data: downloads, harmonization, data checks, field history |
| 2 | Engine: indicators, water balance, erosion, crop table, scoring |
| 3 | App + story: Streamlit, visuals, pitch |

All three of us work on data, so the first phase is shared: find, download and check the datasets.

## 14. Phases

1. **Data look:** download and check the first layers (POWER, Landsat/HLS around the fire, GPM, DEM); confirm the
   key insight (bare months vs. erosive autumn rain).
2. **Pick spots:** choose the 2–3 demo spots on the burn map; rebuild their field history.
3. **Engine:** crop table, water balance, erosion, scoring, explanations.
4. **App:** map, field page, comparison, what-if.
5. **Story:** video/slides, final checks, submission.

## 15. Success criteria (from the brief)

- [ ] Uses several NASA datasets, and explains what each adds.
- [ ] Compares at least 3 rotations, including the current one.
- [ ] Each strategy: why, evidence, benefits, gaps, risks.
- [ ] Farmer priorities change the result.
- [ ] Understandable without GIS skills; supports, never replaces, local expertise.
- [ ] Shows bare-field periods and vulnerable seasons.

## 16. Open questions

- Space Apps rules, judging criteria, deadline, submission format, Resources tab.
- The exact demo spots (burned fields, pastures, apiaries).
- A local contact (farmer, beekeeper, agronomist) to confirm the current rotations.
- Better-than-30 m data worth the effort (Sentinel-2 10 m? commercial/very-high-res archive?).
- Which AI components we actually build in the time we have.
