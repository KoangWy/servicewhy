import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dataclasses import replace  # noqa: E402

import pytest  # noqa: E402

DEMO = "Why did Saturday dinner revenue drop 18%?"


@pytest.fixture
def settings(tmp_path):
    """Keyless settings: local seeded store, offline fake model, everything written under tmp_path."""
    from app.config import Settings
    return replace(Settings.from_env(), sample_mode=False, data_backend="local", model_mode="fake",
                   seed=20261024, sim_days=35, logs_dir=tmp_path / "logs", sample_dir=tmp_path / "examples",
                   cassette_dir=tmp_path / "cassettes", data_dir=tmp_path / "data")


@pytest.fixture
def client(settings):
    from fastapi.testclient import TestClient
    from app.main import create_app
    return TestClient(create_app(settings))


@pytest.fixture
def demo(client):
    r = client.post("/run", json={"run_id": "demo-001", "input": {"query": DEMO}})
    assert r.status_code == 200, r.text
    return r.json()
