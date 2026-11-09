# Reference data: sources and status

Supporting (non-NASA) data, agreed 2026-11-09: **SoilGrids** and **FAO** tables.

## crops.csv

Every row says how sure each value is (`stage_status`, `kc_status`, `root_p_status`):

- `fao56`: copied from FAO Irrigation and Drainage Paper 56 (Allen et al. 1998), read on 2026-11-09:
  - Table 11, lengths of crop development stages: https://www.fao.org/4/x0490e/x0490e0b.htm
  - Table 12, single crop coefficients Kc_ini, Kc_mid, Kc_end: same page
  - Table 22, maximum rooting depth Zr and depletion fraction p: https://www.fao.org/4/x0490e/x0490e0e.htm
- `fao56_group`: the FAO page shows some Kc_ini cells as images; the FAO crop-group value is used
  (cereals 0.3, legumes 0.4, oil crops 0.35). Check against the printed paper.
- `analog`: crop not in FAO-56; values borrowed from the nearest FAO crop (named in `notes`).
- `team_estimate`: placeholder; replace with a source before showing it as evidence.

`forage_value` and `bee_value` (0 none, 1 low, 2 good, 3 excellent) are **team estimates** for now; they need a
source (e.g. Greek beekeeping federation / apicultural literature, agronomist). `n_fixing` = legume (1) or not (0).

Not yet added: FAO ECOCROP temperature/rainfall limits per crop.

## rotations.csv

First draft of strategies A–D for **rainfed fields** (irrigated fields to add). Strategy A is based on the Landsat
crop/fallow history (`exploration/2026-11-09_landsat_fields/`) and must be confirmed locally.

## Soil (data/processed/soil_30m.tif)

SoilGrids 2.0, ISRIC (Poggio et al. 2021), 250 m mean values, https://files.isric.org/soilgrids/latest/data/ ;
CC-BY 4.0. Derived: AWC with Saxton & Rawls (2006); RUSLE K with Williams (1995, EPIC) × 0.1317.
