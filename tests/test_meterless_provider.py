"""Meterless Nightshift provider: wire contract against a local stub, typed errors, no silent fallback."""
import time
from dataclasses import replace

import pytest

from app import model_config
from app.adapters import model as model_mod
from app.adapters.model import (ModelAdapter, ModelProviderError, ModelUnreachable, make_meterless_generator,
                                mask_secrets)
from app.model_config import ModelNotConfigured
from conftest import DEMO
from nightshift_stub import TOKEN, closed_port_url, nightshift


@pytest.fixture(autouse=True)
def clean_provider_env(monkeypatch):
    for k in ("MODEL_PROVIDER", "METERLESS_BASE_URL", "METERLESS_MODEL", "METERLESS_APP", "MODEL_BASE_URL",
              "MODEL_ID", "MODEL_BACKUP_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", "")
    monkeypatch.setenv("MODEL_API_KEY", "")
    monkeypatch.setattr(time, "sleep", lambda s: None)  # the transport retry waits 0.5 s between attempts
    model_config.clear_override()
    yield
    model_config.clear_override()


def use_nightshift(monkeypatch, url, token=TOKEN):
    monkeypatch.setenv("METERLESS_BASE_URL", url)
    monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", token)


def test_chat_speaks_the_nightshift_runtime_contract(monkeypatch):
    with nightshift() as ns:
        use_nightshift(monkeypatch, ns.url)
        out = ModelAdapter("live", session_id="sess-1").complete("writer", "hello", "be brief")
    assert out["text"] == "OK" and out["source"] == "live"
    (req,) = ns.requests
    assert (req["method"], req["path"]) == ("POST", "/v1/chat/completions")
    assert req["headers"]["authorization"] == f"Bearer {TOKEN}"
    assert req["headers"]["meterless-app"] == "servicewhy" and req["headers"]["meterless-scope"] == "user"
    assert "x-opencode-session" not in req["headers"]
    assert req["json"]["model"] == "meterless/auto"  # the default routing id
    assert req["json"]["messages"] == [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hello"}]


def test_model_discovery_hits_v1_models_with_the_same_headers(monkeypatch):
    with nightshift(models=("a/b", "c/d")) as ns:
        use_nightshift(monkeypatch, ns.url)
        assert model_mod.list_models(model_config.resolve()) == ["a/b", "c/d"]
    (req,) = ns.requests
    assert (req["method"], req["path"]) == ("GET", "/v1/models")
    assert req["headers"]["meterless-app"] == "servicewhy" and "x-opencode-session" not in req["headers"]


def test_adapter_reports_the_active_provider_and_model(monkeypatch):
    monkeypatch.setenv("METERLESS_MODEL", "meta/llama-x")
    a = ModelAdapter("live")
    assert (a.provider, a.model_id) == ("meterless", "meta/llama-x")
    monkeypatch.setenv("MODEL_PROVIDER", "opencode")
    assert (ModelAdapter("live").provider, ModelAdapter("live").model_id) == ("opencode", "deepseek-v4.1-flash")
    assert (ModelAdapter("fake").provider, ModelAdapter("fake").model_id) == ("fake", "fake-offline")
    assert (ModelAdapter("replay").provider, ModelAdapter("replay").model_id) == ("cassette", "cassette-replay")


def test_unauthorized_is_a_typed_error_and_is_not_retried(monkeypatch):
    with nightshift() as ns:
        use_nightshift(monkeypatch, ns.url, token="a-wrong-token-123456")
        with pytest.raises(ModelProviderError) as e:
            ModelAdapter("live").complete("writer", "p")
    assert e.value.kind == "Unauthorized" and "a-wrong-token-123456" not in str(e.value)
    assert len(ns.requests) == 1


def test_connection_refused_names_nightshift_and_the_docker_host(monkeypatch):
    url = closed_port_url()
    use_nightshift(monkeypatch, url)
    monkeypatch.setenv("MODEL_BACKUP_API_KEY", "backup-key-0123456")
    a = ModelAdapter("live")
    with pytest.raises(ModelUnreachable, match=r"Nightshift is not reachable at http://127\.0\.0\.1:\d+/v1; is it "
                                                r"running\? From Docker use host\.docker\.internal"):
        a.complete("writer", "p")
    assert a._backup is None  # no silent fallback from Nightshift to another provider


def test_slow_runtime_times_out(monkeypatch):
    with nightshift(delay=1.0) as ns:
        use_nightshift(monkeypatch, ns.url)
        gen = make_meterless_generator(model_config.resolve(), timeout=0.3)
        with pytest.raises(TimeoutError):
            gen("p")


def test_http_400_about_temperature_is_retried_once_without_it(monkeypatch):
    with nightshift(reject_temperature=True) as ns:
        use_nightshift(monkeypatch, ns.url)
        out = make_meterless_generator(model_config.resolve())("p")
    assert out["text"] == "OK" and len(ns.requests) == 2
    assert "temperature" in ns.requests[0]["json"] and "temperature" not in ns.requests[1]["json"]


def test_other_http_errors_surface_the_status(monkeypatch):
    with nightshift(chat_status=503) as ns:
        use_nightshift(monkeypatch, ns.url)
        with pytest.raises(ModelProviderError, match="HTTP 503"):
            make_meterless_generator(model_config.resolve())("p")
    assert len(ns.requests) == 1


def test_live_without_a_token_raises_model_not_configured(monkeypatch):
    with pytest.raises(ModelNotConfigured, match="METERLESS_RUNTIME_TOKEN"):
        ModelAdapter("live").complete("writer", "p")


def test_run_maps_a_missing_token_to_the_structured_error_envelope(settings):
    from fastapi.testclient import TestClient
    from app.main import create_app
    r = TestClient(create_app(replace(settings, model_mode="live"))).post("/run", json={"input": {"query": DEMO}})
    assert r.status_code == 502
    body = r.json()
    assert body["status"] == "error" and body["error"]["type"] == "ModelNotConfigured"
    assert body["error"]["recoverable"] is True and "METERLESS_RUNTIME_TOKEN" in body["error"]["message"]
    assert "Traceback" not in r.text


def test_opencode_provider_keeps_the_original_headers(monkeypatch):
    with nightshift(token="opencode-key-0123456") as ns:
        monkeypatch.setenv("MODEL_PROVIDER", "opencode")
        monkeypatch.setenv("MODEL_API_KEY", "opencode-key-0123456")
        monkeypatch.setenv("MODEL_BASE_URL", ns.url)
        monkeypatch.setenv("MODEL_ID", "some-model")
        out = ModelAdapter("live", session_id="sess-42").complete("writer", "p")
    assert out["text"] == "OK"
    (req,) = ns.requests
    assert req["headers"]["x-opencode-session"] == "sess-42"
    assert req["headers"]["authorization"] == "Bearer opencode-key-0123456"
    assert "meterless-app" not in req["headers"] and "meterless-scope" not in req["headers"]
    assert req["json"]["model"] == "some-model"


def test_cassettes_record_with_nightshift_and_replay_in_any_provider(monkeypatch, tmp_path):
    with nightshift(reply='{"v": 1}') as ns:
        use_nightshift(monkeypatch, ns.url)
        rec = ModelAdapter("record", cassette_dir=tmp_path).complete("writer", "prompt", "sys")
    assert rec["source"] == "record" and len(list(tmp_path.rglob("*.json"))) == 1
    for provider in ("meterless", "opencode"):
        monkeypatch.setenv("MODEL_PROVIDER", provider)
        out = ModelAdapter("replay", cassette_dir=tmp_path).complete("writer", "prompt", "sys")
        assert out["text"] == '{"v": 1}' and out["source"].startswith("cassette:")


def test_a_runtime_token_is_masked_and_is_what_live_calls_send(monkeypatch):
    with nightshift(token="runtime-set-token-987654") as ns:
        monkeypatch.setenv("METERLESS_BASE_URL", ns.url)
        model_config.apply_override("meterless", None, "meta/llama-x", "runtime-set-token-987654")
        assert "runtime-set-token-987654" not in mask_secrets("leak: runtime-set-token-987654")
        out = ModelAdapter("live").complete("writer", "p")
    assert out["text"] == "OK"
    assert ns.requests[0]["headers"]["authorization"] == "Bearer runtime-set-token-987654"
    assert ns.requests[0]["json"]["model"] == "meta/llama-x"
    model_config.clear_override()
    assert mask_secrets("runtime-set-token-987654") == "runtime-set-token-987654"  # forgotten with the override


def test_run_trace_and_output_carry_provider_and_model_but_no_token(client, settings):
    from app.logging.trace import read_trace
    r = client.post("/run", json={"run_id": "prov-001", "input": {"query": DEMO}}).json()
    assert r["output"]["mode"]["model_provider"] == "fake" and r["output"]["mode"]["model_id"] == "fake-offline"
    start = next(e for e in read_trace(settings.logs_dir / "trace-prov-001.jsonl") if e["event"] == "run_start")
    assert start["data"]["model_provider"] == "fake" and start["data"]["model_id"] == "fake-offline"
