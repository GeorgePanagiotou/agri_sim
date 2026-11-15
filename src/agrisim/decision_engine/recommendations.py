"""Thin entry-point for the NEW partial Decision Engine (B+D->E) architecture.

Rotation and vegetation integration must be explicit; no fake cross-joins.
"""
from __future__ import annotations
import pandas as pd
from .fusion import fuse


def generate(sowing_features: pd.DataFrame, risk_features: pd.DataFrame,
             ranked_rotations: pd.DataFrame | None = None, **kwargs) -> pd.DataFrame:
    if ranked_rotations is not None:
        raise NotImplementedError(
            "Rotation module C is not yet connected to the new fusion contract. "
            "Use B+D only until crop-compatible rotation inputs are designed."
        )
    return fuse(sowing_features, risk_features, **kwargs)
