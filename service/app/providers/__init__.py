from ..config import Settings
from .base import Provider
from .imerg import ImergProvider
from .power import PowerProvider


def build_providers(settings: Settings) -> dict[str, Provider]:
    """Register new sources here (and add their native names in variables.py)."""
    return {p.name: p for p in (ImergProvider(settings), PowerProvider(settings))}