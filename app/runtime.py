"""Wires the configured backends: Zetaris (FULL) or the keyless local store (tests / dev)."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.config import Settings


@lru_cache(maxsize=4)
def _local(seed: int, days: int, pg: str, fs: str):
    from app.sim.local_store import LocalDataAccessAdapter
    return LocalDataAccessAdapter(seed=seed, days=days, pg_source=pg, fs_database=fs)


def data_adapter(settings: Settings) -> Any:
    if settings.data_backend == "local":
        return _local(settings.seed, settings.sim_days, settings.pg_source, settings.fs_database)
    if settings.data_backend != "zetaris":
        raise ValueError(f"DATA_BACKEND must be zetaris or local, got {settings.data_backend!r}")
    from app.adapters.zetaris import DataAccessAdapter
    return DataAccessAdapter.from_env()


def orchestrator(settings: Settings):
    from app.orchestrator import Orchestrator
    return Orchestrator(settings, lambda: data_adapter(settings))
