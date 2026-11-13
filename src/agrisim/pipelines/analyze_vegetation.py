"""Run chronological quality-screened satellite index and green-up analysis."""
import argparse
from pathlib import Path
from agrisim.timeseries.vegetation_indices import build as vegetation
from agrisim.timeseries.greenup import run as greenup

def run(hls_batch=None,sentinel_dir=None,parcels=None,*,method='heuristic'):
    frame=vegetation(hls_batch,sentinel_dir,parcels=parcels)
    events=greenup(method=method)
    return frame,events

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--hls-batch',type=Path);ap.add_argument('--sentinel-dir',type=Path)
    ap.add_argument('--parcels',type=Path);ap.add_argument('--method',choices=['heuristic','pelt'],default='heuristic')
    a=ap.parse_args();run(a.hls_batch,a.sentinel_dir,a.parcels,method=a.method)
if __name__=='__main__':main()
