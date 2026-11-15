"""Deterministic source and rule hashes for replay/audit of issued recommendations."""
from __future__ import annotations
import hashlib
from pathlib import Path

TRACKED = (
 'src/agrisim/decision_engine/fusion.py',
 'src/agrisim/decision_engine/pipeline.py',
 'src/agrisim/decision_engine/sowing_window.py',
 'src/agrisim/decision_engine/environmental_risk.py',
 'src/agrisim/decision_engine/rotation.py',
 'src/agrisim/decision_engine/vegetation_history.py',
 'src/agrisim/timeseries/greenup.py',
 'configs/sowing_rules.yaml',
 'configs/risk_rules.yaml',
 'data/reference/rotations.csv',
 'data/reference/sowing_windows.csv',
)


def source_manifest(root: Path) -> dict:
    """SHA-256 of the actual files used by this project's rule-based engine.

    Hashes detect drift but do NOT preserve the original code/config bytes.
    A complete replay requires the same code revision and input archives.
    """
    root=Path(root)
    result={}
    for rel in TRACKED:
        path=root/rel
        result[rel]=(hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file()
                     else None)
    return {'hash_algorithm':'sha256','source_file_hashes':result,
            'replay_status':'hashes_only_requires_original_code_and_datasets'}
