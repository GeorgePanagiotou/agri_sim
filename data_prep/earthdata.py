"""NASA Earthdata Login for the download scripts (IMERG, NASADEM, ...).

Order: EARTHDATA_USERNAME + EARTHDATA_PASSWORD in the environment (the Streamlit Area explorer passes the user's
Settings login to the pipeline run this way; never written to disk), else ~/.netrc (~/_netrc on Windows).
Credentials are never printed or logged.
"""
import os

import earthaccess


def login():
    env = bool(os.environ.get("EARTHDATA_USERNAME") and os.environ.get("EARTHDATA_PASSWORD"))
    try:
        auth = earthaccess.login(strategy="environment" if env else "netrc")
    except Exception as exc:  # noqa: BLE001 - earthaccess raises different types per strategy
        auth, err = None, type(exc).__name__
    else:
        err = None
    if not auth or not getattr(auth, "authenticated", False):
        source = "the Settings login (EARTHDATA_USERNAME/PASSWORD)" if env else "~/.netrc"
        raise SystemExit(f"Earthdata login failed via {source}{f' ({err})' if err else ''}. Sign in under "
                         "Settings in the app's Area explorer, or create ~/.netrc for urs.earthdata.nasa.gov.")
    return auth
