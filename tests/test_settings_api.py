"""Settings API: provider overview, in-memory override, connection test. No network beyond loopback stubs."""
import json
import logging
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app import model_config
from app.api import settings as settings_api
from app.main import create_app
from nightshift_stub import TOKEN, closed_port_url, nightshift

SECRET = "super-secret-runtime-token-424242"


@pytest.fixture(autouse=True)
def clean_provider_env(monkeypatch):
    for k in ("MODEL_PROVIDER", "METERLESS_BASE_URL", "METERLESS_MODEL", "METERLESS_APP", "MODEL_BASE_URL", "MODEL_ID",
              "CORS_ORIGINS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", "")
    monkeypatch.setenv("MODEL_API_KEY", "")
    model_config.clear_override()
    yield
    model_config.clear_override()


@pytest.fixture
def sample_client(settings):
    return TestClient(create_app(replace(settings, sample_mode=True)))


def err(r):
    assert r.json()["status"] == "error"
    return r.json()["error"]


def test_get_settings_has_the_contract_shape(client):
    body = client.get("/settings").json()
    assert body["mode"] == {"sample_mode": False, "data_backend": "local", "model_mode": "fake"}
    assert body["model"] == {"provider": "meterless", "base_url": "http://127.0.0.1:8088/v1",
                             "model_id": "meterless/auto", "token_set": False, "source": "env"}
    assert body["providers"] == [
        {"id": "meterless", "label": "Meterless Nightshift", "primary": True,
         "default_base_url": "http://127.0.0.1:8088/v1", "default_model_id": "meterless/auto"},
        {"id": "opencode", "label": "OpenCode Go", "primary": False,
         "default_base_url": "https://opencode.ai/zen/go/v1", "default_model_id": "deepseek-v4.1-flash"}]


def test_get_settings_reads_the_environment(client, monkeypatch):
    monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", SECRET)
    monkeypatch.setenv("METERLESS_BASE_URL", "http://user:pw@host.docker.internal:8088/v1/?k=1")
    r = client.get("/settings")
    assert r.json()["model"]["token_set"] is True
    assert r.json()["model"]["base_url"] == "http://host.docker.internal:8088/v1/"  # no credentials, no query
    assert SECRET not in r.text and "pw" not in r.json()["model"]["base_url"]


def test_put_model_overrides_in_memory_and_never_returns_the_token(client, caplog):
    caplog.set_level(logging.DEBUG)
    r = client.put("/settings/model", json={"provider": "meterless", "model_id": "meta/llama-x", "token": SECRET})
    assert r.status_code == 200
    assert r.json()["model"] == {"provider": "meterless", "base_url": "http://127.0.0.1:8088/v1",
                                 "model_id": "meta/llama-x", "token_set": True, "source": "runtime"}
    again = client.get("/settings")
    assert again.json() == r.json()
    for text in (r.text, again.text, client.get("/health").text, caplog.text):
        assert SECRET not in text
    assert model_config.resolve().token == SECRET  # held in memory for the next run


def test_token_is_never_written_to_disk(client, settings, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client.put("/settings/model", json={"token": SECRET})
    client.post("/run", json={"run_id": "tok-run", "input": {"query": "Why did Saturday dinner revenue drop 18%?"}})
    for f in [*tmp_path.rglob("*"), *settings.logs_dir.rglob("*")]:
        if f.is_file():
            assert SECRET not in f.read_text(errors="ignore"), f


def test_changing_base_url_requires_a_token_in_the_same_request(client):
    client.put("/settings/model", json={"token": SECRET})
    r = client.put("/settings/model", json={"base_url": "http://evil.example/v1"})
    assert r.status_code == 422
    e = err(r)
    assert e["type"] == "TokenRequiredForNewBaseUrl" and e["recoverable"] is True and e["message"]
    assert client.get("/settings").json()["model"]["base_url"] == "http://127.0.0.1:8088/v1"  # nothing was applied
    ok = client.put("/settings/model", json={"base_url": "http://192.0.2.7:8088/v1/", "token": "another-token-777777"})
    assert ok.status_code == 200 and ok.json()["model"]["base_url"] == "http://192.0.2.7:8088/v1"
    assert model_config.resolve().token == "another-token-777777"


def test_switching_provider_never_carries_the_token_over(client, monkeypatch):
    client.put("/settings/model", json={"token": SECRET})
    r = client.put("/settings/model", json={"provider": "opencode"})  # env holds no OpenCode key
    assert r.status_code == 200
    assert r.json()["model"] == {"provider": "opencode", "base_url": "https://opencode.ai/zen/go/v1",
                                 "model_id": "deepseek-v4.1-flash", "token_set": False, "source": "runtime"}
    assert model_config.resolve().token == ""


def test_invalid_settings_are_rejected_without_echoing_values(client):
    for body, needle in (({"provider": "nope"}, "unknown provider"), ({"base_url": "ftp://x/v1", "token": SECRET}, "http"),
                         ({"base_url": "http://u:p@h/v1", "token": SECRET}, "credentials"),
                         ({"token": 12345}, "string")):
        r = client.put("/settings/model", json=body)
        assert r.status_code == 422 and err(r)["type"] == "InvalidSetting" and needle in err(r)["message"]
        assert SECRET not in r.text
    assert client.get("/settings").json()["model"]["source"] == "env"


def test_put_is_refused_in_sample_mode(sample_client):
    r = sample_client.put("/settings/model", json={"token": SECRET})
    assert r.status_code == 409
    assert err(r) == {"type": "SampleModeNoModel", "recoverable": True,
                      "message": "SAMPLE mode replays recorded runs and does not call a model"}
    assert sample_client.get("/settings").json()["mode"]["sample_mode"] is True


def test_settings_test_in_sample_mode_is_ok_false(sample_client):
    r = sample_client.post("/settings/test", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and body["error"]["type"] == "SampleMode" and body["models"] == []


def test_settings_test_succeeds_against_nightshift(client, monkeypatch):
    with nightshift(models=("meta/llama-x", "other/model")) as ns:
        r = client.post("/settings/test", json={"base_url": ns.url, "token": TOKEN, "model_id": "meta/llama-x"})
    body = r.json()
    assert r.status_code == 200 and body["ok"] is True and body["error"] is None
    assert body["provider"] == "meterless" and body["base_url"] == ns.url
    assert body["models"] == ["meta/llama-x", "other/model"]
    assert body["selected_model"] == "meta/llama-x" and body["selected_model_available"] is True
    assert isinstance(body["latency_ms"], int)
    models_req, chat_req = ns.requests
    assert (models_req["path"], chat_req["path"]) == ("/v1/models", "/v1/chat/completions")
    assert chat_req["json"]["max_tokens"] == 16
    assert chat_req["json"]["messages"] == [{"role": "user", "content": "Reply with the single word OK."}]
    for req in ns.requests:
        assert req["headers"]["meterless-app"] == "servicewhy" and req["headers"]["meterless-scope"] == "user"
        assert "x-opencode-session" not in req["headers"]
    assert TOKEN not in r.text
    assert client.get("/settings").json()["model"]["source"] == "env"  # a test is a one-off, never persisted


def test_auto_is_a_routing_mode_so_it_is_accepted_without_being_listed(client):
    with nightshift(models=("meta/llama-x",)) as ns:
        body = client.post("/settings/test", json={"base_url": ns.url, "token": TOKEN}).json()
    assert body["ok"] is True and body["selected_model"] == "meterless/auto" and body["selected_model_available"] is True


def test_settings_test_uses_the_stored_override_when_no_fields_are_sent(client):
    with nightshift() as ns:
        client.put("/settings/model", json={"base_url": ns.url, "token": TOKEN, "model_id": "meta/llama-x"})
        body = client.post("/settings/test").json()
    assert body["ok"] is True and body["base_url"] == ns.url


def test_settings_test_error_types(client, monkeypatch):
    def test(**fields):
        r = client.post("/settings/test", json=fields)
        assert r.status_code == 200 and r.json()["ok"] is False
        e = r.json()["error"]
        assert set(e) == {"type", "message", "hint"} and e["message"]
        assert TOKEN not in r.text and SECRET not in r.text
        return r.json()

    with nightshift() as ns:
        assert test(base_url=ns.url, token="the-wrong-token-1234")["error"]["type"] == "Unauthorized"
    with nightshift(models=()) as ns:
        body = test(base_url=ns.url, token=TOKEN)
        assert body["error"]["type"] == "NoModels" and body["models"] == []
        assert [r["path"] for r in ns.requests] == ["/v1/models"]  # no chat call without a model
    with nightshift(models=("a/b",)) as ns:
        body = test(base_url=ns.url, token=TOKEN, model_id="not/listed")
        assert body["error"]["type"] == "ModelUnavailable" and body["selected_model_available"] is False
        assert body["models"] == ["a/b"]
    with nightshift(chat_status=503) as ns:
        body = test(base_url=ns.url, token=TOKEN)
        assert body["error"]["type"] == "ChatFailed" and "503" in body["error"]["message"]
    body = test(base_url=closed_port_url(), token=TOKEN)
    assert body["error"]["type"] == "Unreachable" and "Nightshift is not reachable" in body["error"]["message"]
    assert "host.docker.internal" in body["error"]["hint"]
    assert test()["error"]["type"] == "NotConfigured"  # no token anywhere
    assert test(base_url="http://192.0.2.9/v1")["error"]["type"] == "NotConfigured"  # new URL, no token for it
    assert test(provider="nope")["error"]["type"] == "NotConfigured"
    monkeypatch.setattr(settings_api, "TEST_TIMEOUT", 0.3)
    with nightshift(delay=1.0) as ns:
        assert test(base_url=ns.url, token=TOKEN)["error"]["type"] == "Timeout"


def test_the_stored_token_is_never_sent_to_a_url_given_only_in_a_test(client):
    client.put("/settings/model", json={"token": TOKEN})
    with nightshift() as ns:
        body = client.post("/settings/test", json={"base_url": ns.url}).json()
    assert body["error"]["type"] == "NotConfigured" and ns.requests == []


def test_settings_test_works_for_opencode_and_tolerates_a_missing_models_endpoint(client):
    with nightshift(token="opencode-key-0123456") as ns:
        body = client.post("/settings/test", json={"provider": "opencode", "base_url": ns.url,
                                                    "token": "opencode-key-0123456", "model_id": "m"}).json()
    # the stub serves /models, so the model must be listed; an unlisted id is reported as such
    assert body["provider"] == "opencode" and body["error"]["type"] == "ModelUnavailable"
    with nightshift(token="opencode-key-0123456", models=("m",)) as ns:
        body = client.post("/settings/test", json={"provider": "opencode", "base_url": ns.url,
                                                    "token": "opencode-key-0123456", "model_id": "m"}).json()
    assert body["ok"] is True
    assert all("x-opencode-session" not in r["headers"] and "meterless-app" not in r["headers"] for r in ns.requests)
    with nightshift(token="opencode-key-0123456", models=None) as ns:  # UNVERIFIED that OpenCode Go serves /models
        body = client.post("/settings/test", json={"provider": "opencode", "base_url": ns.url,
                                                    "token": "opencode-key-0123456", "model_id": "m"}).json()
        meterless = client.post("/settings/test", json={"base_url": ns.url, "token": "opencode-key-0123456"}).json()
    assert body["ok"] is True and body["models"] == []
    assert meterless["ok"] is False and meterless["error"]["type"] == "Unreachable"  # Nightshift must serve /models
    assert "404" in meterless["error"]["message"]


def test_cors_allows_only_the_configured_origins(settings, monkeypatch):
    c = TestClient(create_app(settings))
    pre = lambda origin: c.options("/settings/model", headers={  # noqa: E731
        "Origin": origin, "Access-Control-Request-Method": "PUT"})
    assert pre("http://localhost:5173").headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert pre("http://127.0.0.1:5173").headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"
    evil = pre("http://evil.example")
    assert evil.status_code == 400 and "access-control-allow-origin" not in evil.headers
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example, https://b.example")
    c2 = TestClient(create_app(settings))
    assert c2.options("/settings", headers={"Origin": "https://b.example", "Access-Control-Request-Method": "GET"}
                      ).headers["access-control-allow-origin"] == "https://b.example"
