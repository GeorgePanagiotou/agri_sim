# Area search: burned fields + grazing + bee forest in one area (2026-11-09)

## What was done

1. **Sentinel-2 L2A** cloud-masked median composites of North Evia (lon 22.80–23.70, lat 38.60–39.05), 20 m, UTM 34N,
   bands B02 B03 B04 B08 B11 B12: **pre** 1 Jul – 2 Aug 2021, **post** 20 Aug – 20 Sep 2021. Downloaded through
   STAIR's CDSE openEO sign-in (run in place, `fetch_s2.py`); ~4–5 min per job, ~110 MB each.
2. **dNBR** = NBR(pre) − NBR(post), NBR = (B08 − B12)/(B08 + B12). Burned = dNBR > 0.27 (also checked > 0.10).
3. **ESA WorldCover 2020** (10 m, pre-fire) read from the public S3 COGs, resampled (mode) to the S2 grid.
4. **10 km window search** for the most balanced mix of burned cropland, burned grass/shrub, burned forest and some
   forest left standing (`analyze_burn.py`). Village names from OpenStreetMap (Overpass).
5. **EFFIS** burnt-area polygon of the 2021 fire (public WFS) as an official cross-check.

Raw rasters stay in the session scratchpad (to delete). Scripts, maps and results are kept here.

## Results

**EFFIS (official):** fire of 3 Aug 2021, start Kourkouloi, **51,881 ha**. By CORINE: **agricultural 33.8 %**,
conifer 28.6 %, transitional woodland-shrub 9.6 %, sclerophyllous 2.5 %. Other fires in or near the area: 2016, 2018,
2019 (Psachna, south) and 1 Jul 2026 (755 ha, Sfaka).

**Our dNBR (> 0.27), whole AOI:** 43,854 ha burned (EFFIS also counts low severity): tree 40,123 · grass 1,653 ·
shrub 1,068 · cropland 835 ha.

Why burned "cropland" looks small next to EFFIS's 34 % agricultural: (a) WorldCover "cropland" is annual crops only;
olive groves and mixed farmland fall under tree/shrub, while CORINE puts them in agricultural; (b) summer stubble is
already dry, so a field fire changes NBR little and a 0.27 threshold misses it. Use dNBR > 0.10 for fields/grass and
check by eye.

**Top windows (10 km):**

| # | Centre | Villages | Character |
|---|---|---|---|
| 1 | 23.383, 38.803 | Kourkouloi (fire start), Kechries, Skepasti, Daphne, Myrtias, Strofylia, Kerameia, Farakla, Metochi, Spathari | **Best mix**: field mosaic on the plateau, Kireas river irrigated fields in the south, forest all round; burned 371 of 1,068 ha cropland, 595 ha grass/shrub, 5,648 ha forest |
| 2 | 23.269, 38.839 | Rovies, Palaiochori, Damia, Drymona | Forest + grass, few fields |
| 3 | 23.386, 38.893 | **Agia Anna, Achladi, Kotsikia, Pappades**, Amelantes | **Pine/honey forest**, almost fully burned; storm "Athena" floods (10–11 Oct 2021); Pappades = pollinator study site |
| 4 | 23.272, 38.929 | Kerasia, Kokkinomilia, Milies, Agdines | Forest + grass |
| 5 | 23.157, 38.945 | Istiaia plain | Many fields, mostly **unburned** (good control) |
| 6 | 23.499, 38.823 | Mantoudi, Kirinthos | Kireas valley fields, mostly **unburned** (control) |

## Proposal: one study area, "Kireas – Agia Anna"

**Box lon 23.32–23.50, lat 38.75–38.95** (≈ 15.6 × 22.1 km, 28,900 ha of land). It joins windows 1, 3 and 6.

| Land (WorldCover 2020) | Total ha | Burned (dNBR > 0.27 / > 0.10) |
|---|---|---|
| Tree (pine, oak, **olive**) | 22,128 | 16,298 / 17,704 |
| Grassland (grazing) | 2,595 | 797 / 1,536 |
| Shrubland (grazing) | 954 | 597 / 689 |
| Cropland | 2,100 | 523 / 971 |

What the area holds:
- **Fields** burned and unburned side by side (Kechries plateau; Kireas valley near Mantoudi/Kirinthos), so we can
  compare burned fields with unburned controls.
- **Grazing land** (grass/shrub around the villages).
- **Bee forest**: the Agia Anna / Pappades pine forest (pine honey), almost fully burned, with unburned patches.
- **The fire's origin** (Kourkouloi) and **the post-fire flood** (storm Athena, Oct 2021: Agia Anna, Achladi, Kotsikia):
  the "autumn storm on bare ground" key insight, with a real event.
- The Kireas river: water, irrigation, flood path.

## Round 2 (same day): fields seen in spring, Landsat history, POWER

**Imagery policy:** read/download only small windows, keep the scene list + derived products, delete the imagery.
All Sentinel-2 composites (6 jobs, 334 tile-scenes, listed in `sentinel2_scenes_used.csv` with openEO job ids) were
deleted after analysis. Landsat was never downloaded, only window reads (scene list in the repo:
`agrisim/data/processed/landsat_scenes.csv`).

**Sentinel-2 10 m, study area, 4 periods** (spring 2021, July 2021, Sept 2021, spring 2022), via STAIR's CDSE sign-in.
Fields = green in spring 2021 (NDVI ≥ 0.45) and dry in July (≤ 0.32). Burned = dNBR(Jul→Sep) above the 95th
percentile of the same kind of land **outside** the EFFIS perimeter (= change from harvest/drying alone) → **0.233**.

| Class | ha | Spring NDVI 2021 → 2022 | Green again spring 2022 |
|---|---|---|---|
| Arable field, burned | 293 | 0.82 → 0.75 | 89 % |
| Arable field, unburned | 738 | 0.80 → 0.68 | 76 % |
| Fields inside / outside the perimeter | 599 / 433 | 0.80→0.74 / 0.81→0.60 | 91 % / 65 % |
| Grazing land (grass/shrub), burned | 435 | 0.68 → 0.74 | 96 % |
| Grazing land, unburned | 782 | 0.68 → 0.71 | 96 % |
| Irrigated summer crops (green in July) | 809 | — | — (Kireas / Mantoudi plain, mostly outside the fire) |

Reading: burned fields were mostly sown/green again in spring 2022; outside the fire only 65 % were green, which
hints at fallow years (cereal → fallow rotation), to confirm with the Landsat history. Files: `fields_study_area.png`,
`field_stats.json`, `field_classes_10m.tif` (0 other, 1 field unburned, 2 field burned, 3 grazing unburned,
4 grazing burned, 5 irrigated summer crop, 6 forest burned).

**Landsat 1984–2025** (958 scenes, monthly NDVI cube, `landsat_field_history.png`): the fire is clear (forest NDVI
~0.7 → 0.33 in Aug 2021, back to ~0.6 by 2024–25, mostly shrub/grass regrowth). The first per-year field typing
(`cropland_year_types.csv`) is **not reliable yet**: fallow fields green up with weeds in spring, 30 m pixels mix
fields and hedgerows, the 2020 cropland mask is used for all years, and L5/L7/L8 NDVI need harmonizing. Calibrate
with the Sentinel-2 field map before using it.

**NASA POWER** (study-area cell 23.41 E, 38.85 N): **Oct 2021 = 327 mm, wettest October in 1981–2026** (median
38 mm); **largest 4-day total of the record, 225 mm, 8–11 Oct 2021** (storm Athena on the fresh burn scar).
1991–2020: Oct–Dec are the wettest months with the most ≥ 20 mm days. Days ≥ 35 °C: 5.4/yr (2011–20) → 11.2/yr
(2021–25). POWER is ~50 km reanalysis → confirm with GPM IMERG (needs Earthdata login) and stations.

## Gaps / next checks

- Beehive and pasture locations are not in any dataset found yet → beekeepers' association, ELGA, literature.
- Separate olives from forest (CORINE 2018 / Sentinel-2 phenology).
- Burned-field detection: lower threshold + NDVI time series; check by eye.
- Get the Copernicus EMS EMSR527 grading (needs login) for damage per land use.

## Sources

- EFFIS burnt areas WFS: https://maps.effis.emergency.copernicus.eu/effis (layer `ms:modis.ba.poly`)
- Copernicus EMS activation EMSR527 (JRC catalogue): https://data.jrc.ec.europa.eu/dataset/5ed86dcf-a9df-40b6-b295-2c1aada75759
- ESA WorldCover 2020: https://esa-worldcover.s3.eu-central-1.amazonaws.com/v100/2020/map/
- Storm Athena in North Evia, Oct 2021: https://www.cnn.gr/ellada/story/284775/kakokairia-athina-anoixan-kai-pali-oi-pliges-sti-voreia-eyvoia-anypologistes-oi-zimies ,
  https://www.protothema.gr/greece/article/1169660/kakokairia-athina-apisteutes-katastrofes-stin-voreia-euvoia/ ,
  mayor's statement: https://www.paron.gr/wp-content/uploads/2021/10/ΔΕΛΤΙΟ-ΤΥΠΟΥ-ΙΩΑΝΝΗΣ-ΚΟΝΤΖΙΑΣ.docx
- Pollinator recovery after the 2021 megafire (Kapsi et al.): https://www.royensoc.co.uk/wp-content/uploads/2025/09/OP6-Evgenia-Kapsi.pdf ;
  Pappades / honeybees: https://www.researchgate.net/publication/375096446
- Beekeeping losses: https://greekreporter.com/2021/08/13/greek-beekeeping-destroyed-by-recent-wildfires-in-evia/ ,
  https://www.tovima.gr/2021/08/28/international/fires-10000-tons-of-pine-honey-were-burned-beekeepers-demand-support-measures/
- Livestock feed support after the fire (Region of Central Greece): https://pste.gov.gr/wp-content/uploads/2021/08/Άμεση-Στήριξη-Πυρόπληκτων-Κτηνοτρόφων-Π.Στ.Ε.-με-ζωοτροφές-110821.pdf
- Livelihoods and recovery: https://spiral.imperial.ac.uk/entities/publication/b3e59e5e-4657-4503-9568-ea38124329e3 ,
  https://www.aljazeera.com/news/2021/9/20/greeces-summer-wildfires-threaten-professions-with-extinction
