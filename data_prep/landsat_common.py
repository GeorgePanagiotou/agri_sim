"""Shared by the Landsat scripts: the fixed 30 m UTM 34N study-area grid and remote window reads of Landsat
Collection 2 Level-2 COGs on Microsoft Planetary Computer (public, anonymous SAS token). Nothing is downloaded whole.
"""
import os

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".TIF,.tif,.vrt")  # .vrt: SoilGrids
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "4")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "2")

import numpy as np
import planetary_computer as pc
import pystac_client
import rasterio
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterio.warp import Resampling, transform_bounds

from config import CRS, STUDY_AREA

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
RES = 30.0
_w, _s, _e, _n = transform_bounds("EPSG:4326", CRS, STUDY_AREA[0], STUDY_AREA[2], STUDY_AREA[1], STUDY_AREA[3])
X0, Y1 = np.floor(_w / RES) * RES, np.ceil(_n / RES) * RES
WIDTH, HEIGHT = int(np.ceil((_e - X0) / RES)), int(np.ceil((Y1 - _s) / RES))
TRANSFORM = from_origin(X0, Y1, RES, RES)
X = X0 + RES * (np.arange(WIDTH) + 0.5)
Y = Y1 - RES * (np.arange(HEIGHT) + 0.5)
BBOX = [STUDY_AREA[0], STUDY_AREA[2], STUDY_AREA[1], STUDY_AREA[3]]  # W S E N

# QA_PIXEL bits: 0 fill, 1 dilated cloud, 2 cirrus (L8/9), 3 cloud, 4 cloud shadow, 5 snow
QA_BAD = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4) | (1 << 5)


def catalog():
    return pystac_client.Client.open(STAC)


def read(href, resampling=Resampling.bilinear):
    """One band of one scene, warped to the study-area grid."""
    with rasterio.open(pc.sign(href)) as src, WarpedVRT(src, crs=CRS, transform=TRANSFORM, width=WIDTH,
                                                        height=HEIGHT, resampling=resampling) as vrt:
        return vrt.read(1)


def reflectance(item, band):
    """Surface reflectance (Collection 2 scale/offset), float32."""
    return read(item.assets[band].href).astype("float32") * 2.75e-5 - 0.2


def clear_mask(item):
    qa = read(item.assets["qa_pixel"].href, Resampling.nearest)
    return ((qa & QA_BAD) == 0) & (qa != 0)


def water_mask(scene_ids):
    """Water where Landsat's own QA_PIXEL water flag (bit 7) is set in most clear observations of the given scenes."""
    cat = catalog()
    votes = np.zeros((HEIGHT, WIDTH), "int16")
    seen = np.zeros((HEIGHT, WIDTH), "int16")
    for it in cat.search(collections=["landsat-c2-l2"], ids=list(scene_ids)).items():
        qa = read(it.assets["qa_pixel"].href, Resampling.nearest)
        clear = ((qa & QA_BAD) == 0) & (qa != 0)
        votes += (clear & ((qa & (1 << 7)) > 0)).astype("int16")
        seen += clear.astype("int16")
    return (seen > 0) & (votes * 2 > seen)


def profile(dtype="uint8", count=1, nodata=None):
    return {"driver": "GTiff", "crs": CRS, "transform": TRANSFORM, "width": WIDTH, "height": HEIGHT,
            "count": count, "dtype": dtype, "nodata": nodata, "compress": "deflate"}
