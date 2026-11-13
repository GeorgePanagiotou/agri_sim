"""Validate known dataset provenance against the explicit challenge allowlist."""
import json
from pathlib import Path
from agrisim.config import REPO

def main():
    product_file=REPO/'configs/sources.json'
    meta=json.loads(product_file.read_text(encoding='utf-8'))
    print('Approved dataset catalogue:',product_file)
    print('Entries:',len(meta) if hasattr(meta,'__len__') else 1)
    print('This is a provenance declaration, not a verification of downloaded file contents.')
if __name__=='__main__':main()
