"""Acquire a SPECIFIC FAO GAEZ suitability GeoTIFF selected by the user in the official portal.

Example:
  python data_prep/download_fao_gaez.py --url 'https://gaez-v4-data.fao.org/.../suitability.tif' \
    --crop wheat --scenario rainfed_low_input

No attempt is made to invent a unique crop/scenario raster URL. Obtain the
actual link in https://gaez.fao.org/ (or FAO's official GAEZ data repository).
The downloaded raster is regional suitability, not an individual farm test.
"""
import argparse
import json
from urllib.parse import urlparse
from datetime import datetime,timezone
import requests
try:
 from .config import RAW
except ImportError:
 from .config import RAW
ALLOWED_HOSTS=('gaez.fao.org','gaez-v4-data.fao.org','www.fao.org','fao.org')

def validate_source(url):
    p=urlparse(url)
    if p.scheme!='https' or p.hostname not in ALLOWED_HOSTS:
        raise ValueError('Only HTTPS downloads directly hosted on official FAO GAEZ domains are allowed')
    return p

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--url',required=True,help='Direct FAO GAEZ GeoTIFF download URL from the portal')
    ap.add_argument('--crop',required=True)
    ap.add_argument('--scenario',required=True,help='GAEZ actual input regime / climate scenario')
    a=ap.parse_args();p=validate_source(a.url)
    name=p.path.rsplit('/',1)[-1]
    if not name.lower().endswith(('.tif','.tiff')):ap.error('Please select a direct FAO GeoTIFF download')
    folder=RAW/'fao_gaez';folder.mkdir(parents=True,exist_ok=True)
    target=folder/f'{a.crop.lower()}_{a.scenario.lower()}_{name}'
    if not target.exists():
        r=requests.get(a.url,stream=True,timeout=(30,240),allow_redirects=False)
        r.raise_for_status()
        temp=target.with_suffix(target.suffix+'.partial')
        with temp.open('wb') as f:
            for part in r.iter_content(chunk_size=1<<20):
                if part:f.write(part)
        import rasterio
        with rasterio.open(temp) as ds:
            if ds.count<1:raise ValueError('Downloaded FAO raster has no bands')
        temp.rename(target)
    (target.with_suffix('.json')).write_text(json.dumps({
        'source':'FAO GAEZ','source_url':a.url,'crop':a.crop,'scenario':a.scenario,
        'retrieved_utc':datetime.now(timezone.utc).isoformat(),
        'interpretation':'Check FAO documentation for layer-specific codes and units before scoring'
    },indent=2),encoding='utf-8')
    print('FAO GAEZ raster:',target)
if __name__=='__main__':main()
