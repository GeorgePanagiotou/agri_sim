"""Discover available approved data download entry points.

Downloads aren't run en masse by default: Earthdata/CDS credentials, quotas,
and requested AOI/date ranges differ between products.
"""
import argparse
import json
from agrisim.config import REPO

def available():
    return {
        'hls':'agrisim.data_sources.landsat',
        'landsat_history':'agrisim.data_sources.landsat_ndvi_history',
        'sentinel2':'agrisim.data_sources.sentinel2',
        'smap':'agrisim.data_sources.smap',
        'imerg':'agrisim.data_sources.imerg',
        'power':'agrisim.data_sources.power',
        'modis_or_ecostress':'agrisim.data_sources.download_appeears',
        'era5':'agrisim.data_sources.era5',
        'srtm':'agrisim.data_sources.srtm',
        'gaez':'agrisim.data_sources.gaez',
    }

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list',action='store_true',help='List individual downloader modules')
    args=parser.parse_args()
    print(json.dumps(available(),indent=2))
    print('Run: uv run python -m <module-name> --help')
if __name__=='__main__':main()
