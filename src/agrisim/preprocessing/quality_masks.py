"""Surface reflectance and QA masks for NASA HLS and ESA Sentinel-2.

HLS Fmask bits: cirrus 0, cloud 1, adjacent cloud 2, shadow 3, snow 4, water 5;
Aerosol bits 6-7=3 mean high. Bit meanings should be checked against HLS v2
product guide when adapting to another product.
"""
import numpy as np

def hls_clear_mask(fmask, *, reject_water=True, reject_high_aerosol=True):
    f = np.asarray(fmask).astype('uint8')
    invalid = (f == 255) | ((f & 1) != 0)  # fill or cirrus
    invalid |= (f & ((1 << 1) | (1 << 2) | (1 << 3) | (1 << 4))) != 0
    if reject_water: invalid |= (f & (1 << 5)) != 0
    if reject_high_aerosol: invalid |= ((f >> 6) & 3) == 3
    return ~invalid

def sentinel2_clear_mask(scl, *, exclude_water=True):
    """ESA L2A scene classification: accept vegetation, bare soil and optionally water."""
    scl = np.asarray(scl)
    return np.isin(scl, [4, 5] if exclude_water else [4, 5, 6])

def reflectance_valid(*bands, mask=None, min_reflectance=0.0, max_reflectance=1.3):
    if not bands: raise ValueError('Supply bands')
    valid = np.ones(np.shape(bands[0]), dtype=bool)
    for band in bands:
        b = np.asarray(band, dtype=float)
        if b.shape != valid.shape: raise ValueError('Band shape mismatch')
        valid &= np.isfinite(b) & (b >= min_reflectance) & (b <= max_reflectance)
    if mask is not None: valid &= np.asarray(mask, dtype=bool)
    return valid
