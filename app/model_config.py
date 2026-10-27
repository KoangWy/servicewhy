"""Model provider configuration: environment values merged with an in-memory runtime override.

Providers (env `MODEL_PROVIDER`, default `meterless`):
  meterless  Meterless Nightshift, an OpenAI-compatible local Runtime. The provider's own key lives in
             Nightshift, never here; this app only needs the Runtime URL, the Runtime token and a routing id.
             METERLESS_BASE_URL (default http://127.0.0.1:8088/v1), METERLESS_RUNTIME_TOKEN,
             METERLESS_MODEL (default meterless/auto), METERLESS_APP (default servicewhy).
  opencode   OpenCode Go (secondary): MODEL_BASE_URL / MODEL_API_KEY / MODEL_ID, unchanged.

The runtime override (set through `PUT /settings/model`) lives in process memory only: it is never written to
disk, and its token is registered with the secret masker so traces and logs cannot contain it.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, replace
from urllib.parse import urlsplit, urlunsplit

PROVIDERS: dict[str, dict] = {
    "meterless": {"label": "Meterless Nightshift", "primary": True, "default_base_url": "http://127.0.0.1:8088/v1",
                  "default_model_id": "meterless/auto", "env": ("METERLESS_BASE_URL", "METERLESS_RUNTIME_TOKEN",
                                                                "METERLESS_MODEL")},
    "opencode": {"label": "OpenCode Go", "primary": False, "default_base_url": "https://opencode.ai/zen/go/v1",
                 "default_model_id": "deepseek-v4.1-flash", "env": ("MODEL_BASE_URL", "MODEL_API_KEY", "MODEL_ID")},
}


class ModelNotConfigured(RuntimeError):
    """No usable model configuration (typically a missing token): fix the setting, no code change needed."""


class TokenRequiredForNewBaseUrl(ValueError):
    """A changed base URL must arrive with its own token, so a stored token is never redirected to another host."""


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    base_url: str
    model_id: str
    token: str
    app: str = "servicewhy"

    def public(self) -> dict:
        """Everything a response may show: never the token, never credentials embedded in the URL."""
        return {"provider": self.provider, "base_url": safe_url(self.base_url), "model_id": self.model_id,
                "token_set": bool(self.token)}


_lock = threading.Lock()
_override: ModelConfig | None = None


def safe_url(url: str) -> str:
    """Drop userinfo and query string from a URL before it is shown or logged."""
    p = urlsplit(url)
    host = p.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    netloc = host + (f":{p.port}" if p.port else "")
    return urlunsplit((p.scheme, netloc, p.path, "", "")) if p.scheme else url


def _norm(url: str, provider: str | None = None) -> str:
    """Trim a pasted URL. For Nightshift the Runtime base is always `<host>/v1`: a pasted `/chat/completions` or
    `/models` tail is dropped, a bare host gets `/v1`, and a repeated `/v1/v1` collapses (never `/v1/v1`)."""
    url = url.strip().rstrip("/")
    if provider == "meterless" and url:
        for tail in ("/chat/completions", "/models"):
            if url.endswith(tail):
                url = url[:-len(tail)].rstrip("/")
        while url.endswith("/v1/v1"):
            url = url[:-3]
        if not url.endswith("/v1"):
            url += "/v1"
    return url


def env_provider() -> str:
    provider = os.environ.get("MODEL_PROVIDER", "meterless").strip().lower() or "meterless"
    if provider not in PROVIDERS:
        raise ModelNotConfigured(f"MODEL_PROVIDER must be one of {sorted(PROVIDERS)}, got {provider!r}")
    return provider


def env_config(provider: str) -> ModelConfig:
    """The configuration the environment alone describes for one provider."""
    meta = PROVIDERS[provider]
    url_var, token_var, model_var = meta["env"]
    app = os.environ.get("METERLESS_APP", "").strip() or "servicewhy"
    return ModelConfig(provider, _norm(os.environ.get(url_var, "") or meta["default_base_url"], provider),
                       os.environ.get(model_var, "").strip() or meta["default_model_id"],
                       os.environ.get(token_var, "").strip(), app)


def resolve() -> ModelConfig:
    with _lock:
        return _override if _override is not None else env_config(env_provider())


def source() -> str:
    with _lock:
        return "runtime" if _override is not None else "env"


def merge(cur: ModelConfig, provider: str | None, base_url: str | None, model_id: str | None,
          token: str | None) -> tuple[ModelConfig, bool]:
    """Apply request fields over `cur`; blank strings count as omitted.

    Returns (config, token_missing). token_missing is True when the base URL changes and the request carries no
    token for it: the stored token must never follow a new host, so the config falls back to the token the
    environment holds for that exact URL (or none).
    """
    provider = (provider or "").strip().lower() or cur.provider
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}; expected one of {sorted(PROVIDERS)}")
    base = cur if provider == cur.provider else env_config(provider)
    new_url = _norm(base_url or "", provider) or base.base_url
    if not new_url.lower().startswith(("http://", "https://")) or not urlsplit(new_url).hostname:
        raise ValueError("base_url must be an http(s) URL such as http://127.0.0.1:8088/v1")
    if urlsplit(new_url).username or urlsplit(new_url).password:
        raise ValueError("base_url must not embed credentials; send the token separately")
    new = replace(base, base_url=new_url, model_id=(model_id or "").strip() or base.model_id)
    token = (token or "").strip()
    if token:
        return replace(new, token=token), False
    if new_url == cur.base_url:
        return replace(new, token=base.token), False
    env = env_config(provider)
    if new_url == env.base_url:  # back to the environment's own endpoint: its own token is safe to use
        return replace(new, token=env.token), False
    return replace(new, token=""), True


def apply_override(provider: str | None, base_url: str | None, model_id: str | None,
                   token: str | None) -> ModelConfig:
    global _override
    with _lock:
        cur = _override if _override is not None else env_config(env_provider())
        new, token_missing = merge(cur, provider, base_url, model_id, token)
        if token_missing:
            raise TokenRequiredForNewBaseUrl("base_url changed: send the token for the new URL in the same request")
        _override = new
        return new


def clear_override() -> None:
    global _override
    with _lock:
        _override = None


def secret_values() -> list[str]:
    """Runtime-set tokens, for the secret masker."""
    with _lock:
        return [_override.token] if _override is not None and _override.token else []
