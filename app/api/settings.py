"""Model settings API: which provider answers (Meterless Nightshift primary, OpenCode Go secondary) and a connection test.

The override lives in process memory only. No response, log or trace ever carries a token: `token_set` is all
the API says about it.
"""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Body, Request

from app import model_config
from app.adapters import model as model_adapter
from app.api.routes import _error
from app.model_config import ModelConfig, ModelNotConfigured, TokenRequiredForNewBaseUrl

router = APIRouter()

TEST_TIMEOUT = 10.0  # seconds, per HTTP call of /settings/test
_FIELDS = ("provider", "base_url", "model_id", "token")
_TOKEN_ENV = {"meterless": "METERLESS_RUNTIME_TOKEN", "opencode": "MODEL_API_KEY"}


def _state(request: Request):
    return request.app.state.svc


def _fields(body: Any) -> dict[str, str | None]:
    """Only known string fields are accepted; the offending value is never echoed back (it may be a token)."""
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ValueError("body must be a JSON object")
    out: dict[str, str | None] = {}
    for k in _FIELDS:
        v = body.get(k)
        if v is not None and not isinstance(v, str):
            raise ValueError(f"{k} must be a string")
        out[k] = v
    return out


def _payload(request: Request) -> dict[str, Any]:
    s = _state(request).settings
    cfg = model_config.resolve()
    return {"mode": {"sample_mode": s.sample_mode, "data_backend": s.data_backend, "model_mode": s.model_mode},
            "model": {**cfg.public(), "source": model_config.source()},
            "providers": [{"id": pid, **{k: m[k] for k in ("label", "primary", "default_base_url",
                                                           "default_model_id")}}
                          for pid, m in model_config.PROVIDERS.items()]}


@router.get("/settings")
def get_settings(request: Request):
    try:
        return _payload(request)
    except ModelNotConfigured as e:
        return _error(500, "ModelNotConfigured", str(e))


@router.put("/settings/model")
def put_model(request: Request, body: Any = Body(default=None)):
    if _state(request).settings.sample_mode:
        return _error(409, "SampleModeNoModel", "SAMPLE mode replays recorded runs and does not call a model")
    try:
        f = _fields(body)
        model_config.apply_override(f.get("provider"), f.get("base_url"), f.get("model_id"), f.get("token"))
    except TokenRequiredForNewBaseUrl as e:
        return _error(422, "TokenRequiredForNewBaseUrl", str(e))
    except ValueError as e:
        return _error(422, "InvalidSetting", str(e))
    except ModelNotConfigured as e:
        return _error(500, "ModelNotConfigured", str(e))
    return _payload(request)


def _scrub(text: str, token: str) -> str:
    text = model_adapter.mask_secrets(text)
    return text.replace(token, "…redacted") if token else text


def _result(cfg: ModelConfig, t0: float, models: list[str], available: bool, error: dict | None,
            routed: str | None = None) -> dict[str, Any]:
    out = {"ok": error is None, "provider": cfg.provider, "base_url": model_config.safe_url(cfg.base_url),
           "latency_ms": round((time.monotonic() - t0) * 1000), "models": models[:200], "selected_model": cfg.model_id,
           "selected_model_available": available, "error": error, "routed_model": routed, "note": None}
    if routed and routed.startswith("webllm/"):  # observed: meterless/auto picked the on-device model
        out["note"] = (f"{cfg.model_id} was routed to the on-device model {routed}. A model this small cannot run the "
                       "agent reliably: set the model id to a concrete cloud model from the list.")
    return out


def _routed_model(reply: Any) -> str | None:
    """Nightshift reports the model that really answered in `meterless.routed_model` (else the OpenAI `model` field)."""
    if not isinstance(reply, dict):
        return None
    ns = reply.get("meterless")
    routed = ns.get("routed_model") if isinstance(ns, dict) else None
    routed = routed or reply.get("model")
    return routed if isinstance(routed, str) else None


def _err(kind: str, message: str, hint: str = "") -> dict[str, str]:
    return {"type": kind, "message": message, "hint": hint}


def _is_routing_id(cfg: ModelConfig) -> bool:
    """`meterless/auto` is a routing mode, not a model id, so it is never in /models."""
    return cfg.provider == "meterless" and cfg.model_id == model_config.PROVIDERS["meterless"]["default_model_id"]


def _run_test(cfg: ModelConfig, token_missing: bool) -> dict[str, Any]:
    t0, models, available = time.monotonic(), [], False
    if not cfg.token:
        env = _TOKEN_ENV[cfg.provider]
        msg = ("no token for this base URL" if token_missing else "no token configured")
        hint = (f"Enter the token together with the new URL." if token_missing
                else f"Set {env} (or enter the token in Settings).")
        if cfg.provider == "meterless":
            hint += " The provider's own key is entered inside Nightshift, not here."
        return _result(cfg, t0, models, False, _err("NotConfigured", msg, hint))
    unreachable_hint = ("Start Nightshift and check the Runtime URL; from a container use host.docker.internal "
                        "instead of 127.0.0.1 (works on Docker Desktop for Mac; UNVERIFIED on Linux)."
                        if cfg.provider == "meterless" else "Check the base URL and your network.")
    try:
        try:
            models = model_adapter.list_models(cfg, timeout=TEST_TIMEOUT)
            listed = True
        except model_adapter.ModelProviderError as e:
            # UNVERIFIED that OpenCode Go serves /models: for it, a missing endpoint is not a failure
            if cfg.provider == "opencode" and getattr(e, "status", None) in (404, 405):
                models, listed = [], False
            elif e.kind == "HTTPError":
                return _result(cfg, t0, models, False, _err(
                    "Unreachable", _scrub(str(e), cfg.token), "GET /models failed: check the base URL (it should end "
                    "in /v1) and that this is the Runtime URL."))
            else:
                raise
        if listed and not models:
            return _result(cfg, t0, models, False, _err(
                "NoModels", "the endpoint lists no models",
                "Connect a provider and model in Nightshift's Providers tab; /healthz being OK does not prove a "
                "model is connected." if cfg.provider == "meterless" else "The provider returned an empty list."))
        available = (not listed) or _is_routing_id(cfg) or cfg.model_id in models
        if not available:
            return _result(cfg, t0, models, False, _err(
                "ModelUnavailable", f"model {cfg.model_id!r} is not in the endpoint's model list",
                "Pick one of the listed ids" + (" or use meterless/auto." if cfg.provider == "meterless" else ".")))
        reply = model_adapter.chat_completion(
            cfg, {"model": cfg.model_id, "temperature": 0, "max_tokens": 16,
                  "messages": [{"role": "user", "content": "Reply with the single word OK."}]}, timeout=TEST_TIMEOUT)
    except model_adapter.ModelUnreachable as e:
        return _result(cfg, t0, models, False, _err("Unreachable", _scrub(str(e), cfg.token), unreachable_hint))
    except model_adapter.ModelProviderError as e:
        if e.kind == "Unauthorized":
            return _result(cfg, t0, models, False, _err("Unauthorized", _scrub(str(e), cfg.token),
                                                        "Check the token (Nightshift's Runtime token for Nightshift)."))
        hint = ("Nightshift answered but the chat call failed; check that a provider key and model are set in "
                "Nightshift's Providers tab." if cfg.provider == "meterless" else "")
        return _result(cfg, t0, models, available, _err("ChatFailed", _scrub(str(e), cfg.token), hint))
    except TimeoutError:
        return _result(cfg, t0, models, False, _err(
            "Timeout", f"no answer within {TEST_TIMEOUT:g}s", "The endpoint is slow or not answering; try again."))
    return _result(cfg, t0, models, True, None, routed=_routed_model(reply))


@router.post("/settings/test")
def test_model(request: Request, body: Any = Body(default=None)):
    """One-off connection test with optional overrides; nothing is persisted. Always HTTP 200."""
    t0 = time.monotonic()
    try:
        cfg = model_config.resolve()
    except ModelNotConfigured as e:
        return _result(model_config.env_config("meterless"), t0, [], False, _err("NotConfigured", str(e), "Fix MODEL_PROVIDER."))
    if _state(request).settings.sample_mode:
        return _result(cfg, t0, [], False, _err(
            "SampleMode", "SAMPLE mode replays recorded runs and does not call a model",
            "Run in FULL mode (SAMPLE_MODE=false) to test a model connection."))
    try:
        f = _fields(body)
        cfg, token_missing = model_config.merge(cfg, f.get("provider"), f.get("base_url"), f.get("model_id"),
                                                f.get("token"))
    except ValueError as e:
        return _result(cfg, t0, [], False, _err("NotConfigured", str(e), "Fix the setting and retry."))
    return _run_test(cfg, token_missing)
