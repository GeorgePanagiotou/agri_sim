# Any study area: one command from a bounding box to the ML training table (2026-11-14)

North Evia is the demo. The same scripts run for any area of up to 1 × 1 degree:

```powershell
python -m agrisim.pipelines.prepare_area --name messara --bbox 24.75 24.95 35.00 35.10 --label "Messara plain"
python -m agrisim.pipelines.prepare_area --name messara --plan                    # done / to do per step
python -m agrisim.pipelines.prepare_area --name messara --steps risk,sowing --force risk
```

**From the UI:** the Streamlit app's *Area explorer* page (`app/area_explorer.py`) does the same.
- Choose a prepared area, or draw a new box and create it.
- Start or resume its data preparation in the background.
- See the status of each step, the climate (rain from IMERG Final and scaled Late, plus POWER, via the climate API
  in `service/`) and the ML training table.
- The climate API serves every area in `configs/areas/` without a restart ([service/README.md](../service/README.md)).

## How the area is selected

- `configs/areas/<name>.yaml` holds the box (lon_min, lon_max, lat_min, lat_max), pilot point, CRS, folders and an
  optional fire window. `--bbox` writes it.
- The environment variable **`AGRISIM_AREA`** picks the area for every script (`data_prep/*.py` and the `agrisim`
  package). The default is `evia`.
- **Evia keeps its original paths** (`data/`, `outputs/`) and grid (UTM 34N), so nothing existing changed.
- Other areas use `data/areas/<name>/{raw,processed,outputs,logs}`, ignored by git.
- The grid is UTM, zone taken from the box centre (Crete → 35N), at 30 m, as in `data_prep/landsat_common.py`.
- Code: `src/agrisim/area.py`, `src/agrisim/pipelines/prepare_area.py`; tests in `tests/test_area.py`.

## Steps (each skipped when its output exists; logs in `<data_root>/logs/<step>.log`)

| Step | What | Source | Time (Evia-sized area) |
|---|---|---|---|
| harmonization | Landsat 5/7/9 → 8 NDVI offsets | copied from Evia (sensor-level); refit with `landsat_harmonize.py` | seconds |
| landsat | monthly 30 m NDVI cube, `--first-year` (default 1997) … 2025 | Landsat C2 L2, Planetary Computer windows | **hours** (network-bound) |
| field_map | land use + crop/fallow per pixel and season | the cube | minutes |
| soil | SoilGrids 2.0 on the grid | ISRIC (CC BY 4.0) | minutes |
| terrain | elevation, slope, flow accumulation, LS | NASADEM (Earthdata login) | minutes |
| imerg | IMERG Final daily per 0.1° cell, 2001 → | GES DISC OPeNDAP (Earthdata login) | ~10–20 min |
| imerg_late | IMERG Late Run after Final ends (~3.5 months) → yesterday, per quarter; Final wins where both exist | GES DISC OPeNDAP | ~5 min |
| imerg_late_cal | Late on Final days 2019 → Final end; Late→Final factor per half-year from the last 3 years (readers scale Late with it) | GES DISC OPeNDAP | ~15 min |
| power | POWER daily at the box centre, 1991 → end of last month | NASA POWER API | seconds |
| risk | Environmental Risk Engine v1 | the above | ~1 min |
| sowing | sowing-window engine v1 | the above | ~1 min |
| training_table | ML training table | the above | ~2 min |

## Area-specific parts

- **Burn maps:** `landsat_burn_2021.py` is Evia-only (fixed 2021 windows). Without a burn map, the field-map burn
  band is 0, the upslope burned share is 0 and `burn_dnbr_2021` is NaN.
- **Not yet area-generic:** MODIS (via AppEEARS), ECOSTRESS, SMAP L4 point, HLS / Sentinel-2 pilot windows and
  GAEZ. The training table adds the MODIS columns only when the files exist.
- **Demo fields** (`DEMO_FIELDS`) exist only for Evia.
- The pilot point defaults to the box centre. It is not a surveyed field.
