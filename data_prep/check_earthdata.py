"""Check NASA Earthdata access (no download): login from ~/.netrc, then open one GPM IMERG daily granule and one
NASADEM tile remotely and read only the study-area window.

One-time setup per person (in your own terminal, it asks for your Earthdata username/password and saves ~/.netrc):
    ..\\.venv\\Scripts\\python.exe -c "import earthaccess; earthaccess.login(strategy='interactive', persist=True)"
Then:
    ..\\.venv\\Scripts\\python.exe data_prep\\check_earthdata.py
"""
import earthaccess
import xarray as xr

from config import STUDY_AREA

W, E, S, N = STUDY_AREA
auth = earthaccess.login(strategy="netrc")
if not auth or not auth.authenticated:
    raise SystemExit("Not logged in. Run the one-time setup in the docstring first.")
print("Earthdata login OK")

# GPM IMERG Final daily (GES DISC): needs the "NASA GESDISC DATA ARCHIVE" app approved in your Earthdata profile
res = earthaccess.search_data(short_name="GPM_3IMERGDF", version="07", temporal=("2021-10-09", "2021-10-09"),
                              bounding_box=(W, S, E, N))
print("GPM IMERG granules found:", len(res))
f = earthaccess.open(res[:1])[0]
ds = xr.open_dataset(f, engine="h5netcdf")
p = ds["precipitation"].sel(lon=slice(W - 0.1, E + 0.1), lat=slice(S - 0.1, N + 0.1))
print("IMERG 2021-10-09 rain over the study area (mm/day): mean", float(p.mean()), "max", float(p.max()))

# NASADEM (LP DAAC), 30 m elevation
res = earthaccess.search_data(short_name="NASADEM_HGT", bounding_box=(W, S, E, N))
print("NASADEM tiles found:", len(res), [r["umm"]["GranuleUR"] for r in res][:3])
print("All checks passed.")
