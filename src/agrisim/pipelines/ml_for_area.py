"""ML models for the current area (AGRISIM_AREA), trained on that area's own satellite history.

Builds the 14 Nov and 1 Mar training tables and the live 14 Nov table for season 2027, then trains the
satellite-proxy XGBoost models (agrisim.models.train_satellite_proxies: forward split by season, compared with the
pixel's own 5-year baselines) for spring vigour and crop vs fallow. Output: <data_root>/processed/ml/models/<date>/.

Targets are Landsat-NDVI stand-ins, not farm records. The 3-class model is left out: its class weights inflate
the fallow share of the live predictions.

    python -m agrisim.pipelines.ml_for_area            (prepare_area runs it as step "ml_models")
"""
from __future__ import annotations

from agrisim.config import AREA_NAME, PROC
from agrisim.models import train_satellite_proxies as tsp
from agrisim.pipelines import build_training_table as bt

ML = PROC / "ml"
MODELS = ML / "models"
TABLES = {"11-14": "training_table_1114", "03-01": "training_table_0301"}
LIVE = ML / "predict_2027_1114.parquet"   # season 2027 = Oct 2026 .. Sep 2027


def main(argv=None) -> None:
    ML.mkdir(parents=True, exist_ok=True)
    for as_of, name in TABLES.items():
        path = ML / f"{name}.parquet"
        if not path.exists():
            bt.main(["--as-of", as_of, "--out", str(path)])
    if not LIVE.exists():
        bt.main(["--predict-season", "2027", "--as-of", "11-14", "--out", str(LIVE)])
    common = ["--input-dir", str(ML), "--output-dir", str(MODELS), "--tasks", "vigour", "crop"]
    tsp.main(["--date", "1114", "--live-2027", *common])
    tsp.main(["--date", "0301", *common])
    print(f"ML models for area {AREA_NAME} -> {MODELS}")


if __name__ == "__main__":
    main()
