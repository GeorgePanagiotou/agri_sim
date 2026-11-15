"""Does an area fit the AgriSim rules? Climate class + crop suitability for ANY location.

- Köppen–Geiger climate class from NASA POWER monthly climatology (2 m temperature, corrected precipitation), with
  the rules of Beck et al. (2018, Sci. Data 5:180214): E first, then B (arid), then A / C / D.
- Rule fit: the crop list, Oct–Dec sowing windows, Oct–Sep season and field-map thresholds were built for North Evia
  (Csa). Cs* climates fit; semi-arid winter-rain climates fit partly; everything else is not calibrated. Southern
  Hemisphere seasons are reversed, which the engines do not handle yet.
- FAO GAEZ v4 crop suitability (rainfed, low input, 1981–2010 climate; index 0–10000) for the five AgriSim crops,
  read from the global 5-arc-minute rasters in data/reference/gaez/ (CC BY 4.0, FAO & IIASA).
"""
from __future__ import annotations

import calendar
import json
import ssl
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
GAEZ_DIR = REPO / "data" / "reference" / "gaez"
GAEZ = {"wheat": "wheat_rainfed_historical_low_input_suLr_whe.tif",
        "barley": "barley_rainfed_historical_low_input_suLr_brl.tif",
        "maize": "maize_rainfed_historical_low_input_suLr_mze.tif",
        "chickpea": "chickpea_rainfed_historical_low_input_suLr_chk.tif",
        "dry pea": "dry_pea_rainfed_historical_low_input_suLr_pea.tif"}
POWER_CLIM = "https://power.larc.nasa.gov/api/temporal/climatology/point"
MONTHS = [m.upper() for m in calendar.month_abbr[1:]]
DAYS = np.array([31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])

NAMES = {
    "Af": "tropical rainforest", "Am": "tropical monsoon", "Aw": "tropical savanna",
    "BWh": "hot desert", "BWk": "cold desert", "BSh": "hot semi-arid", "BSk": "cold semi-arid",
    "Csa": "Mediterranean, hot summer", "Csb": "Mediterranean, warm summer", "Csc": "Mediterranean, cold summer",
    "Cwa": "humid subtropical, dry winter", "Cwb": "subtropical highland, dry winter", "Cwc": "subpolar oceanic, dry winter",
    "Cfa": "humid subtropical", "Cfb": "oceanic", "Cfc": "subpolar oceanic",
    "ET": "tundra", "EF": "ice cap",
}
for _s, _n in (("s", "dry summer"), ("w", "dry winter"), ("f", "no dry season")):
    for _t, _m in (("a", "hot summer"), ("b", "warm summer"), ("c", "cold summer"), ("d", "very cold winter")):
        NAMES.setdefault(f"D{_s}{_t}", f"continental, {_n}, {_m}")


def koppen(temp_c, precip_mm, lat: float) -> str:
    """Köppen–Geiger class from 12 monthly mean temperatures (°C) and monthly precipitation totals (mm)."""
    t, p = np.asarray(temp_c, float), np.asarray(precip_mm, float)
    if t.shape != (12,) or p.shape != (12,):
        raise ValueError("need 12 monthly values each")
    summer = np.isin(np.arange(1, 13), [4, 5, 6, 7, 8, 9] if lat >= 0 else [10, 11, 12, 1, 2, 3])
    mat, map_ = t.mean(), p.sum()
    tcold, thot = t.min(), t.max()
    ps, pw = p[summer], p[~summer]
    if ps.sum() >= 0.7 * map_:
        pth = 2 * mat + 28
    elif pw.sum() >= 0.7 * map_:
        pth = 2 * mat
    else:
        pth = 2 * mat + 14
    if thot < 10:
        return "ET" if thot > 0 else "EF"
    if map_ < 10 * pth:
        return ("BW" if map_ < 5 * pth else "BS") + ("h" if mat >= 18 else "k")
    if tcold >= 18:
        pdry = p.min()
        return "Af" if pdry >= 60 else ("Am" if pdry >= 100 - map_ / 25 else "Aw")
    second = ("s" if ps.min() < 40 and ps.min() < pw.max() / 3
              else "w" if pw.min() < ps.max() / 10 else "f")
    warm = int((t > 10).sum())
    if tcold > 0:
        third = "a" if thot >= 22 else ("b" if warm >= 4 else "c")
        return "C" + second + third
    third = "a" if thot >= 22 else ("b" if warm >= 4 else ("d" if tcold < -38 else "c"))
    return "D" + second + third


def rule_fit(code: str, lat: float, winter_rain_share: float) -> tuple[str, str]:
    """(level, explanation); level = calibrated | partly | not calibrated."""
    south = (" It is in the Southern Hemisphere: seasons are reversed, and the engines' Oct–Sep season and Oct–Dec "
             "sowing windows do not match it yet.") if lat < 0 else ""
    if lat < 0:
        return "not calibrated", f"{code} ({NAMES.get(code, code)}).{south}"
    if code.startswith("Cs"):
        return "calibrated", (f"{code} ({NAMES.get(code, code)}), the same climate family as North Evia (Csa): the "
                              "winter-crop list, Oct–Dec sowing windows and Oct–Sep season apply.")
    if code in ("BSk", "BSh") and winter_rain_share >= 0.6:
        return "partly", (f"{code} ({NAMES.get(code, code)}) with mostly winter rain: the winter-crop calendar "
                          "applies, but drought is the normal state, so drought levels and crops need local review.")
    if code.startswith("Ds") and winter_rain_share >= 0.6:
        return "partly", (f"{code} ({NAMES.get(code, code)}): winter-rain like the Mediterranean, so winter cereals "
                          "fit, but winters are freezing: sowing must finish earlier and frost risk is higher than "
                          "the Evia rules assume.")
    return "not calibrated", (f"{code} ({NAMES.get(code, code)}): different rain season or winters. The sowing "
                              "windows, crop list and risk thresholds were built for a Mediterranean winter-rain "
                              "climate; treat sowing, risk and crop/fallow results here as untested.")


def _verify():
    try:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        return True


def power_normals(lon: float, lat: float, cache: Path | None = None) -> dict:
    """Monthly 2 m temperature (°C) and precipitation (mm/month) normals from NASA POWER climatology."""
    if cache and cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    import httpx
    r = httpx.get(POWER_CLIM, params={"parameters": "T2M,PRECTOTCORR", "community": "AG", "longitude": round(lon, 3),
                                      "latitude": round(lat, 3), "format": "JSON"}, timeout=60, verify=_verify())
    r.raise_for_status()
    js = r.json()
    par = js["properties"]["parameter"]
    out = {"temp_c": [float(par["T2M"][m]) for m in MONTHS],
           "precip_mm": [round(float(par["PRECTOTCORR"][m]) * d, 1) for m, d in zip(MONTHS, DAYS)],
           "period": js.get("header", {}).get("range", "POWER climatology"),
           "source": "NASA POWER climatology (MERRA-2 T2M, PRECTOTCORR), community AG"}
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out), encoding="utf-8")
    return out


def gaez_suitability(lon: float, lat: float, box: tuple[float, float, float, float] | None = None) -> dict:
    """{crop: {"pilot": index at the point, "box_max": best 5' cell in the box}} (0–10000; None = no data)."""
    import rasterio
    from rasterio.windows import from_bounds
    out = {}
    for crop, fname in GAEZ.items():
        path = GAEZ_DIR / fname
        if not path.exists():
            continue
        with rasterio.open(path) as src:
            v = next(src.sample([(lon, lat)]))[0]
            pilot = None if v == src.nodata or v < 0 else int(v)
            best = None
            if box:
                w, e, s, n = box
                a = src.read(1, window=from_bounds(w, s, e, n, src.transform), boundless=True, fill_value=-9)
                a = a[a >= 0]
                best = int(a.max()) if a.size else None
        out[crop] = {"pilot": pilot, "box_max": best}
    return out


def assess(area) -> dict:
    """Everything the Area explorer shows about fit, for an agrisim.area.Area."""
    lon, lat = area.pilot
    normals = power_normals(lon, lat, cache=area.data_root / "processed" / "climate_normals_power.json")
    summer = np.isin(np.arange(1, 13), [4, 5, 6, 7, 8, 9] if lat >= 0 else [10, 11, 12, 1, 2, 3])
    p = np.array(normals["precip_mm"])
    winter_share = float(p[~summer].sum() / p.sum()) if p.sum() > 0 else 0.0
    code = koppen(normals["temp_c"], normals["precip_mm"], lat)
    level, text = rule_fit(code, lat, winter_share)
    return {"koppen": code, "name": NAMES.get(code, code), "fit": level, "explanation": text,
            "winter_rain_share": winter_share, "normals": normals,
            "gaez": gaez_suitability(lon, lat, area.study_area)}
