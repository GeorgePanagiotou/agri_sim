# The story (draft v0, 2026-11-09)

> Draft. Confirm or change the **[?]** items as the team decides and as the data comes in.

## The place and the event

**North Evia (Euboea), Greece.** In **August 2021** a wildfire burned **about 50,000 ha**, mostly Aleppo-pine forest
around Mantoudi, Limni, Agia Anna and the hills above the Istiaia plain. Livelihoods that depended on the forest
(resin collection, pine honey, grazing) were hit, and the bare slopes now send more runoff and soil downhill onto the
farmland in the valleys.

## The user

A **farmer in a valley or plain next to the burn scar** (Istiaia plain, Mantoudi/Kireas valley **[?]**) with mostly
rainfed annual fields and maybe goats/sheep or bees. They ask: *"My fields lose soil every autumn, summers are hotter
and drier, and I lost income from the forest. What should I rotate on this field?"*

## The key insight (hypothesis, check with data first)

In the usual **cereal → summer fallow** rotation the field is **bare from June to October**. The **first autumn storms
(Sept–Nov)** are the most erosive rain of the year, and they hit that bare soil. Below the burned slopes the runoff
coming from upslope is larger than before 2021. **A rotation that keeps the soil covered in autumn** (a legume forage, a
melliferous cover crop, a perennial strip on slopes) cuts the erosion risk exactly when it peaks. It can also feed the
animals, fix nitrogen and give the beekeepers back some forage.

To check: GPM monthly erosivity vs. HLS/MODIS NDVI bare months; NDVI recovery of the burn scar since 2021.

## The rotations we compare (at least 3, the brief requires the current one)

| # | Strategy | Idea |
|---|---|---|
| A | **Current**: winter wheat/barley → summer fallow **[?]** | Baseline |
| B | **Legume forage**: cereal → vetch–oat (or chickpea/lentil) | N-fixing, autumn cover, feed for goats/sheep |
| C | **Bee & soil**: cereal → sainfoin / clover / phacelia, perennial aromatic strips (oregano, thyme) on slopes | Melliferous, all-year cover, niche market |
| D | (optional) **Drought-tolerant**: barley → chickpea, less water | Water-saving if summers keep drying |

Each strategy gets one card: **why suggested, evidence (which data, which numbers), benefits, information gaps, risks
for local review.**

## What the demo shows (keep to what fits the video)

1. **Map of North Evia**: the 2021 burn scar (Landsat/HLS dNBR) and its recovery over time, with 2–3 demo fields.
2. **Pick a field** → its conditions: a seasonal calendar (rain, ET, heat days, frost, soil moisture), water balance,
   slope and erosion risk, and the trends since the 1980s (NASA POWER).
3. **Set your priorities**: sliders for water saving, soil/erosion, income, animal feed, bees.
4. **Compare the rotations**: a month-by-month cover calendar against the erosion risk, water need vs. rain, and the
   strategy cards.
5. **What-if sliders**: +1/+2 °C, −10/−20 % rain → how the ranking changes.
6. Everywhere: **"Check with your agronomist"** where the data is thin.

## How the "AI" part stays honest

The core (water balance FAO-56, erosion RUSLE, weighted scoring) is deterministic and explainable. AI is used where it
helps and can be explained: e.g. detecting bare/crop periods from the NDVI time series, clustering years into
"normal / dry / hot" types, and generating plain-language explanations (Greek + English) from the computed numbers
only. **[? decide in the team]**
