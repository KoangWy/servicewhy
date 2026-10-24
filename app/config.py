"""Runtime configuration, read from the environment only (secrets never live in code).

Two judged modes (SPEC D10): FULL (`SAMPLE_MODE=false`, real compose stack) and SAMPLE (replay a
recorded run, zero network). `DATA_BACKEND=local` and `MODEL_MODE=fake|replay` exist for keyless
development and tests only; they never appear in the judged FULL path.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env reader: never overrides variables already set by the shell or compose."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def _flag(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    sample_mode: bool
    data_backend: str      # zetaris | local
    model_mode: str        # live | record | replay | fake
    seed: int
    sim_days: int
    logs_dir: Path
    data_dir: Path
    cassette_dir: Path
    sample_dir: Path
    pg_source: str         # Zetaris datasource name over PostgreSQL
    fs_database: str       # Zetaris Lightning database over the MinIO parquet filestore

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            sample_mode=_flag("SAMPLE_MODE"),
            data_backend=os.environ.get("DATA_BACKEND", "zetaris").strip().lower(),
            model_mode=os.environ.get("MODEL_MODE", "live").strip().lower(),
            seed=int(os.environ.get("SIM_SEED", "20261024")),
            sim_days=int(os.environ.get("SIM_DAYS", "35")),
            logs_dir=Path(os.environ.get("LOGS_DIR", ROOT / "logs")),
            data_dir=Path(os.environ.get("DATA_DIR", ROOT / "data" / "generated")),
            cassette_dir=Path(os.environ.get("CASSETTE_DIR", ROOT / "cassettes")),
            sample_dir=Path(os.environ.get("SAMPLE_DIR", ROOT / "logs" / "examples")),
            pg_source=os.environ.get("ZETARIS_PG_SOURCE", "svc_pg"),
            fs_database=os.environ.get("ZETARIS_FS_DATABASE", "svc_fs"),
        )
