"""ModelAdapter: single seam for model calls. Meterless engines receive this as the injected generator.

Modes (env `MODEL_MODE`):
  live    OpenAI-compatible provider chosen by `MODEL_PROVIDER`: Meterless Nightshift (default, no fallback) or
          OpenCode Go with failover to the backup provider (DeepInfra); see app/model_config.py
  record  live call, response stored as a cassette (secrets masked) — run only on the QA machine
  record-missing  replay a cassette when one exists, else live call + store it: re-recording after a prompt change
          keeps every unchanged answer instead of re-sampling it
  replay  answer from cassettes keyed by (role, system prompt, prompt); a miss raises CassetteMiss
  fake    deterministic offline responder (tests and keyless development only)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

from app import model_config
from app.model_config import ModelConfig, ModelNotConfigured

Generator = Callable[..., dict[str, Any]]

MODES = ("live", "record", "record-missing", "replay", "fake")
_SECRET_ENV = re.compile(r"(KEY|PASSWORD|TOKEN|SECRET)$")


class CassetteMiss(RuntimeError):
    """Replay mode found no recorded response: a hard failure, never a silent live call."""


class ModelBudgetExceeded(RuntimeError):
    pass


class ModelProviderError(RuntimeError):
    """The provider answered, but not usefully (bad token, HTTP error, malformed body)."""
    def __init__(self, kind: str, message: str, hint: str = ""):
        super().__init__(message)
        self.kind, self.hint = kind, hint


class ModelUnreachable(ModelProviderError, ConnectionError):
    """No connection to the provider; a ConnectionError, so the transport retry in `_live_call` covers it."""
    def __init__(self, message: str, hint: str = ""):
        super().__init__("Unreachable", message, hint)


def _unreachable(cfg: ModelConfig, reason: object) -> ModelUnreachable:
    where = model_config.safe_url(cfg.base_url)
    if cfg.provider == "meterless":
        return ModelUnreachable(f"Nightshift is not reachable at {where}; is it running? "
                                f"From Docker use host.docker.internal ({reason})",
                                "Start Nightshift and check its Runtime URL; from a container use "
                                "http://host.docker.internal:8088/v1 (UNVERIFIED: depends on the Docker setup).")
    return ModelUnreachable(f"model endpoint is not reachable at {where} ({reason})")


def provider_headers(cfg: ModelConfig, session: str | None = None) -> dict[str, str]:
    h = {"Content-Type": "application/json", "Authorization": f"Bearer {cfg.token}",
         # Cloudflare in front of the OpenCode endpoint rejects urllib's default UA (error 1010)
         "User-Agent": "servicewhy/0.1"}
    if cfg.provider == "meterless":
        h.update({"meterless-app": cfg.app, "meterless-scope": "user"})  # never x-opencode-session
    elif session:
        h["x-opencode-session"] = session
    return h


def _open_json(cfg: ModelConfig, req: urllib.request.Request, timeout: float) -> Any:
    """One HTTP exchange, errors mapped to typed exceptions; the token never reaches a message."""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return json.load(res)
    except urllib.error.HTTPError as e:
        raw = e.read(2000).decode("utf-8", "replace")
        snippet = mask_secrets(raw).strip().replace(chr(10), " ")[:300]
        if e.code in (401, 403):
            raise ModelProviderError("Unauthorized", f"HTTP {e.code}: the token was rejected at "
                                     f"{model_config.safe_url(cfg.base_url)}", "Check the Runtime token.") from None
        err = ModelProviderError("HTTPError", f"HTTP {e.code} from {model_config.safe_url(cfg.base_url)}: {snippet}")
        err.status = e.code
        raise err from None
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError):
            raise TimeoutError(f"no answer from {model_config.safe_url(cfg.base_url)} within {timeout:g}s") from None
        raise _unreachable(cfg, e.reason) from None
    except ConnectionError as e:  # reset after connect
        raise _unreachable(cfg, e) from None
    except ValueError as e:  # not JSON
        raise ModelProviderError("HTTPError", f"{model_config.safe_url(cfg.base_url)} did not return JSON") from e


def chat_completion(cfg: ModelConfig, payload: dict[str, Any], *, session: str | None = None,
                    timeout: float = 60.0) -> dict[str, Any]:
    """POST {base}/chat/completions. A 400 that complains about `temperature` is retried once without it."""
    headers = provider_headers(cfg, session)
    url = f"{cfg.base_url}/chat/completions"
    for attempt in (0, 1):
        req = urllib.request.Request(url, json.dumps(payload).encode(), headers)
        try:
            return _open_json(cfg, req, timeout)
        except ModelProviderError as e:
            if attempt == 0 and getattr(e, "status", None) == 400 and "temperature" in str(e).lower() \
                    and "temperature" in payload:
                payload = {k: v for k, v in payload.items() if k != "temperature"}
                continue
            raise
    raise AssertionError("unreachable")


def list_models(cfg: ModelConfig, *, timeout: float = 10.0) -> list[str]:
    """GET {base}/models (OpenAI list shape `{"data": [{"id": ...}]}`)."""
    req = urllib.request.Request(f"{cfg.base_url}/models", headers=provider_headers(cfg))
    body = _open_json(cfg, req, timeout)
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        raise ModelProviderError("HTTPError", f"{model_config.safe_url(cfg.base_url)}/models returned an unexpected shape")
    return [m["id"] for m in data if isinstance(m, dict) and isinstance(m.get("id"), str)]


def _reply_text(cfg: ModelConfig, body: Any) -> str:
    try:
        text = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        text = None
    if not isinstance(text, str):
        raise ModelProviderError("ChatFailed", f"{model_config.safe_url(cfg.base_url)} returned no message content")
    return text


def make_meterless_generator(cfg: ModelConfig, *, session_id: str | None = None, timeout: float = 60.0) -> Generator:
    """Chat generator for Meterless Nightshift's OpenAI-compatible Runtime (same call signature as `make_generator`)."""
    if not cfg.token:
        raise ModelNotConfigured("no Nightshift Runtime token: set METERLESS_RUNTIME_TOKEN (or enter it in "
                                 "Settings); the provider's own key belongs in Nightshift's Providers tab")
    session = session_id or str(uuid.uuid4())

    def generator(prompt: str, attachments=None, system_prompt: str | None = None,
                  on_stream=None, abort_signal=None) -> dict[str, Any]:
        messages = ([{"role": "system", "content": system_prompt}] if system_prompt else [])
        messages.append({"role": "user", "content": prompt})
        body = chat_completion(cfg, {"model": cfg.model_id, "messages": messages, "temperature": 0}, timeout=timeout)
        return {"text": _reply_text(cfg, body), "usage": body.get("usage"), "session": session,
                "model": body.get("model") or cfg.model_id}

    return generator


def make_generator(*, session_id: str | None = None, timeout: float = 60.0, prefix: str = "MODEL") -> Generator:
    """OpenAI-compatible chat generator. Config from {prefix}_API_KEY / {prefix}_BASE_URL / {prefix}_ID."""
    if prefix == "MODEL":  # the primary OpenCode Go endpoint honours a runtime override from Settings
        cfg = model_config.resolve()
        cfg = cfg if cfg.provider == "opencode" else model_config.env_config("opencode")
        key, base, model = cfg.token, cfg.base_url, cfg.model_id
        if not key:
            raise ModelNotConfigured("no OpenCode Go key: set MODEL_API_KEY (or enter it in Settings)")
    else:
        key, base = os.environ[f"{prefix}_API_KEY"], os.environ[f"{prefix}_BASE_URL"].rstrip("/")
        model = os.environ[f"{prefix}_ID"]
    session = session_id or str(uuid.uuid4())

    def generator(prompt: str, attachments=None, system_prompt: str | None = None,
                  on_stream=None, abort_signal=None) -> dict[str, Any]:
        messages = ([{"role": "system", "content": system_prompt}] if system_prompt else [])
        messages.append({"role": "user", "content": prompt})
        req = urllib.request.Request(
            f"{base}/chat/completions",
            json.dumps({"model": model, "messages": messages, "temperature": 0}).encode(),
            {"Content-Type": "application/json", "Authorization": f"Bearer {key}",
             "x-opencode-session": session,
             # Cloudflare in front of the endpoint rejects urllib's default UA (error 1010)
             "User-Agent": "servicewhy/0.1"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as res:
            body = json.load(res)
        return {"text": body["choices"][0]["message"]["content"], "usage": body.get("usage"), "session": session,
                "model": model}

    return generator


def cassette_key(role: str, system_prompt: str | None, prompt: str) -> str:
    return hashlib.sha256("\x1f".join((role, system_prompt or "", prompt)).encode()).hexdigest()[:24]


def mask_secrets(text: str, env: dict[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    secrets = [v for k, v in env.items() if _SECRET_ENV.search(k)] + model_config.secret_values()
    for v in secrets:
        if v and len(v) >= 6:
            text = text.replace(v, "…redacted")
    return text


def extract_json(text: str) -> dict[str, Any]:
    """Models wrap JSON in prose or code fences; take the outermost object. Reasoning models (observed: Nemotron 3 Ultra
    through Nightshift) put their thinking before a closing `</think>` and may quote braces in it, so keep what follows."""
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"no JSON object in model output: {text[:120]!r}")
    return json.loads(text[start:end + 1])


class ModelAdapter:
    def __init__(self, mode: str = "live", *, session_id: str | None = None, cassette_dir: str | Path = "cassettes",
                 max_calls: int = 40, live: Generator | None = None, backup: Generator | None = None,
                 fake: Callable[[str, str | None, str], str] | None = None):
        if mode not in MODES:
            raise ValueError(f"MODEL_MODE must be one of {MODES}, got {mode!r}")
        self.mode, self.session_id = mode, session_id or str(uuid.uuid4())
        self.cassette_dir, self.max_calls, self.calls = Path(cassette_dir), max_calls, 0
        self._live, self._backup, self._fake = live, backup, fake
        self._cfg: ModelConfig | None = None

    @classmethod
    def from_env(cls, *, session_id: str, cassette_dir: str | Path) -> "ModelAdapter":
        return cls(os.environ.get("MODEL_MODE", "live").strip().lower(), session_id=session_id,
                   cassette_dir=cassette_dir, max_calls=int(os.environ.get("MODEL_MAX_CALLS", "40")))

    @property
    def config(self) -> ModelConfig:
        """Provider settings, resolved once per adapter (= once per run) so one run never mixes providers."""
        if self._cfg is None:
            self._cfg = model_config.resolve()
        return self._cfg

    @property
    def provider(self) -> str:
        return {"fake": "fake", "replay": "cassette"}.get(self.mode) or self.config.provider

    @property
    def model_id(self) -> str:
        return {"fake": "fake-offline", "replay": "cassette-replay"}.get(self.mode) or self.config.model_id

    # ---- providers -------------------------------------------------------------------------------
    def _live_call(self, prompt: str, system_prompt: str | None) -> dict[str, Any]:
        cfg = self.config
        if self._live is None:
            self._live = (make_meterless_generator(cfg, session_id=self.session_id) if cfg.provider == "meterless"
                          else make_generator(session_id=self.session_id))
        # No silent fallback: the backup provider belongs to OpenCode Go only, never to Nightshift
        if cfg.provider == "opencode" and self._backup is None and os.environ.get("MODEL_BACKUP_API_KEY"):
            self._backup = make_generator(session_id=self.session_id, prefix="MODEL_BACKUP")
        last: Exception | None = None
        for gen in [g for g in (self._live, self._live, self._backup) if g is not None]:
            try:
                return gen(prompt, system_prompt=system_prompt)
            except ModelProviderError as e:
                if not isinstance(e, ModelUnreachable):  # an answer, not a transport failure: no retry
                    raise
                last = e
                time.sleep(0.5)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:  # transport only
                last = e
                time.sleep(0.5)
        if isinstance(last, (ModelUnreachable, TimeoutError)) and cfg.provider == "meterless":
            raise last
        raise RuntimeError(f"model providers unavailable: {last}")

    def _path(self, role: str, key: str) -> Path:
        return self.cassette_dir / role / f"{key}.json"

    # ---- public ----------------------------------------------------------------------------------
    def complete(self, role: str, prompt: str, system_prompt: str | None = None) -> dict[str, Any]:
        self.calls += 1
        if self.calls > self.max_calls:
            raise ModelBudgetExceeded(f"model call budget of {self.max_calls} per run exhausted")
        key = cassette_key(role, system_prompt, prompt)
        if self.mode == "fake":
            if self._fake is None:
                from app.adapters.fake_model import respond
                self._fake = respond
            return {"text": self._fake(role, system_prompt, prompt), "session": self.session_id, "source": "fake"}
        if self.mode in ("replay", "record-missing"):
            path = self._path(role, key)
            if path.exists():
                rec = json.loads(path.read_text(encoding="utf-8"))
                return {"text": rec["response"]["text"], "session": self.session_id, "source": f"cassette:{key}"}
            if self.mode == "replay":
                raise CassetteMiss(f"no cassette for role={role} key={key} in {self.cassette_dir}")
        out = self._live_call(prompt, system_prompt)
        if self.mode in ("record", "record-missing"):
            path = self._path(role, key)
            path.parent.mkdir(parents=True, exist_ok=True)
            rec = {"role": role, "key": key, "model": out.get("model"), "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "system_prompt": mask_secrets(system_prompt or ""), "prompt": mask_secrets(prompt),
                   "response": {"text": mask_secrets(out["text"])}}
            path.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n")
        return {"text": out["text"], "session": self.session_id, "source": self.mode, "usage": out.get("usage")}

    def complete_json(self, role: str, prompt: str, system_prompt: str | None = None) -> tuple[dict[str, Any], dict]:
        out = self.complete(role, prompt, system_prompt)
        return extract_json(out["text"]), out

    def generator(self, role: str) -> Generator:
        """Meterless-style injected generator bound to one role."""
        def gen(prompt: str, attachments=None, system_prompt: str | None = None, on_stream=None, abort_signal=None):
            return self.complete(role, prompt, system_prompt)
        return gen
