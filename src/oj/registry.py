from __future__ import annotations

from src.core.errors import TrackerError
from src.oj.atcoder import AtCoderAdapter
from src.oj.base import OJAdapter
from src.oj.cf import CodeforcesAdapter


_ADAPTER_FACTORIES = {
    "atcoder": AtCoderAdapter,
    "cf": CodeforcesAdapter,
}


def available_oj_names() -> list[str]:
    """Return the supported OJ names in stable CLI display order."""
    return sorted(_ADAPTER_FACTORIES.keys())


def get_adapter(oj: str) -> OJAdapter:
    """Instantiate the adapter registered for the requested OJ name."""
    factory = _ADAPTER_FACTORIES.get(oj)
    if factory is None:
        raise TrackerError(f"unsupported oj: {oj}")
    return factory()
