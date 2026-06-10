"""Tool-specific adapters for structure prediction engines."""

from __future__ import annotations

from predict_structure.adapters.base import BaseAdapter
from predict_structure.adapters.boltz import BoltzAdapter
from predict_structure.adapters.chai import ChaiAdapter
from predict_structure.adapters.alphafold import AlphaFoldAdapter
from predict_structure.adapters.esmfold import ESMFoldAdapter
from predict_structure.adapters.esmfold2 import ESMFold2Adapter
from predict_structure.adapters.openfold import OpenFoldAdapter

ADAPTERS: dict[str, type[BaseAdapter]] = {
    "boltz": BoltzAdapter,
    "chai": ChaiAdapter,
    "alphafold": AlphaFoldAdapter,
    "esmfold": ESMFoldAdapter,
    "esmfold2": ESMFold2Adapter,
    "openfold": OpenFoldAdapter,
}


def get_adapter(tool_name: str) -> BaseAdapter:
    """Return an adapter instance for the given tool name.

    Args:
        tool_name: One of "boltz", "chai", "alphafold", "esmfold", "openfold".

    Returns:
        Configured adapter instance.

    Raises:
        ValueError: If tool_name is not recognized.
    """
    cls = ADAPTERS.get(tool_name.lower())
    if cls is None:
        raise ValueError(f"Unknown tool '{tool_name}'. Choose from: {list(ADAPTERS)}")
    return cls()


__all__ = [
    "BaseAdapter",
    "BoltzAdapter",
    "ChaiAdapter",
    "AlphaFoldAdapter",
    "ESMFoldAdapter",
    "ESMFold2Adapter",
    "OpenFoldAdapter",
    "ADAPTERS",
    "get_adapter",
]
