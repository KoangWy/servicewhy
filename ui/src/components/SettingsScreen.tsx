import { useEffect, useState } from "react";
import { api, HttpError, isApiError } from "../api";
import type { ConnectionTest, ModelSettingsInput, ProviderInfo, Settings } from "../types";
import { Badge, btnPrimary, btnSecondary, field, panel } from "./common";

type Check = "pass" | "fail" | "skipped";

const CHECK_TONE = { pass: "ok", fail: "bad", skipped: "neutral" } as const;
const CHECK_TEXT = { pass: "Yes", fail: "No", skipped: "Not checked" } as const;

/** Reads the test result as a list of checks. Which checks ran follows from the error type the server reports. */
function checksOf(t: ConnectionTest): { label: string; state: Check; detail?: string }[] {
  const err = t.error?.type;
  const noConnection = err === "Unreachable" || err === "Timeout" || err === "NotConfigured" || err === "SampleMode";
  const reached = noConnection ? "skipped" : "pass";
  const authed: Check = noConnection ? "skipped" : err === "Unauthorized" ? "fail" : "pass";
  const modelsStage: Check = noConnection || err === "Unauthorized" ? "skipped" : err === "NoModels" ? "fail" : "pass";
  const selected: Check = modelsStage !== "pass" ? "skipped" : t.selected_model_available ? "pass" : "fail";
  const chat: Check = t.ok ? "pass" : err === "ChatFailed" ? "fail" : "skipped";
  return [
    { label: "Reachable", state: err === "Unreachable" || err === "Timeout" ? "fail" : reached },
    { label: "Authenticated", state: authed },
    { label: "Models found", state: modelsStage, detail: modelsStage === "pass" ? `${t.models.length}` : undefined },
    { label: "Selected model available", state: selected, detail: t.selected_model || undefined },
    { label: "Test reply received", state: chat },
  ];
}

function TestResult({ result }: { result: ConnectionTest }) {
  const err = result.error;
  return (
    <div
      role={result.ok ? "status" : "alert"}
      data-testid="test-result"
      className={`mt-4 rounded-card border p-4 text-sm ${result.ok ? "border-ok-line bg-ok-bg" : "border-bad-line bg-bad-bg"}`}
    >
      <p className={`font-medium ${result.ok ? "text-ok-fg" : "text-bad-fg"}`}>
        {result.ok ? "Connection works." : "Connection test failed."}
        {result.latency_ms ? <span className="font-normal tabular-nums"> {result.latency_ms} ms</span> : null}
      </p>
      <ul className="mt-3 grid gap-1.5">
        {checksOf(result).map((c) => (
          <li key={c.label} className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <Badge tone={CHECK_TONE[c.state]}>{CHECK_TEXT[c.state]}</Badge>
            <span className="text-ink">{c.label}</span>
            {c.detail ? <span className="font-mono text-xs text-muted [overflow-wrap:anywhere]">{c.detail}</span> : null}
          </li>
        ))}
      </ul>
      {result.routed_model ? (
        <p className="mt-3 text-sm text-ink">
          Answered by <span className="font-mono text-xs [overflow-wrap:anywhere]">{result.routed_model}</span>
        </p>
      ) : null}
      {result.note ? <p className="mt-2 text-sm font-medium text-warn-fg" data-testid="test-note">{result.note}</p> : null}
      {err ? (
        <div className="mt-3 border-t border-bad-line pt-3 text-ink">
          <p><strong className="font-semibold text-bad-fg">{err.type}:</strong> {err.message}</p>
          {err.hint ? <p className="mt-1 text-muted">{err.hint}</p> : null}
        </div>
      ) : null}
    </div>
  );
}

function Mode({ settings }: { settings: Settings }) {
  const { sample_mode, data_backend, model_mode } = settings.mode;
  return (
    <section className={panel} aria-labelledby="mode-h">
      <div className="flex flex-wrap items-center gap-3">
        <h3 id="mode-h" className="text-base font-semibold text-ink">Mode</h3>
        <Badge tone={sample_mode ? "warn" : "neutral"}>{sample_mode ? "SAMPLE" : "FULL"}</Badge>
      </div>
      <p className="mt-2 text-sm text-muted">
        {sample_mode
          ? "SAMPLE replays recorded runs. No data store is queried and no model is called."
          : "FULL runs the agent for real: it queries the data backend and calls the model configured below."}
      </p>
      <dl className="mt-3 grid gap-x-8 gap-y-1 text-sm sm:grid-cols-[auto_minmax(0,1fr)]">
        <dt className="text-muted">Data backend</dt>
        <dd className="text-ink">{data_backend}</dd>
        <dt className="text-muted">Model mode</dt>
        <dd className="text-ink">{model_mode}</dd>
      </dl>
      <p className="mt-3 text-xs text-muted">This is set when the API starts and cannot be changed here.</p>
    </section>
  );
}

function Provider({ settings, onSaved }: { settings: Settings; onSaved: (s: Settings) => void }) {
  const { model, providers } = settings;
  const locked = settings.mode.sample_mode;
  const [provider, setProvider] = useState<string>(model.provider);
  const [baseUrl, setBaseUrl] = useState(model.base_url);
  const [modelId, setModelId] = useState(model.model_id);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState<"save" | "test" | null>(null);
  const [notice, setNotice] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const [result, setResult] = useState<ConnectionTest | null>(null);

  const info: ProviderInfo | undefined = providers.find((p) => p.id === provider);
  const urlChanged = baseUrl.trim() !== model.base_url;

  const pick = (p: ProviderInfo) => {
    setProvider(p.id);
    const saved = p.id === model.provider;
    setBaseUrl(saved ? model.base_url : p.default_base_url);
    setModelId(saved ? model.model_id : p.default_model_id);
    setToken("");
    setNotice(null);
    setResult(null);
  };

  const input = (): ModelSettingsInput => ({
    provider,
    base_url: baseUrl.trim(),
    model_id: modelId.trim(),
    ...(token ? { token } : {}),
  });

  const save = async () => {
    setBusy("save");
    setNotice(null);
    try {
      const body = await api.saveModel(input());
      if (isApiError(body)) {
        setNotice({
          tone: "bad",
          text: body.error.type === "TokenRequiredForNewBaseUrl"
            ? "Enter the runtime token again to use a different base URL. A stored token is never sent to a new host, so it has to be supplied together with the new address."
            : `${body.error.type}: ${body.error.message}`,
        });
      } else {
        setToken("");
        setResult(null);
        setBaseUrl(body.model.base_url);
        setModelId(body.model.model_id);
        onSaved(body);
        setNotice({ tone: "ok", text: "Saved. This applies to the next run and is kept in memory only, so it resets when the API restarts." });
      }
    } catch (e) {
      setNotice({ tone: "bad", text: `Could not save: ${e instanceof Error ? e.message : String(e)}` });
    } finally {
      setBusy(null);
    }
  };

  const test = async () => {
    setBusy("test");
    setNotice(null);
    setResult(null);
    try {
      setResult(await api.testModel(input()));
    } catch (e) {
      setNotice({ tone: "bad", text: `Could not run the test: ${e instanceof Error ? e.message : String(e)}` });
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className={panel} aria-labelledby="model-h">
      <h3 id="model-h" className="text-base font-semibold text-ink">Model provider</h3>
      {locked ? (
        <p role="note" className="mt-3 rounded-control border border-warn-line bg-warn-bg px-3 py-2 text-sm text-warn-fg">
          SAMPLE replays recorded runs. Model settings are not used here. To run the agent for real, follow path B in the README.
        </p>
      ) : null}
      <form className="mt-4" onSubmit={(e) => { e.preventDefault(); save(); }} autoComplete="off">
        <fieldset disabled={locked} className="min-w-0 space-y-5">
          <legend className="sr-only">Model provider settings</legend>
          <div role="radiogroup" aria-label="Provider" className="grid gap-2 sm:grid-cols-2">
            {providers.map((p) => (
              <label key={p.id} className={`flex cursor-pointer items-start gap-3 rounded-control border p-3 text-sm ${provider === p.id ? "border-accent-ink bg-accent-soft" : "border-line-strong bg-surface"}`}>
                <input type="radio" name="provider" value={p.id} checked={provider === p.id} onChange={() => pick(p)} className="mt-0.5" />
                <span>
                  <span className="block font-medium text-ink">{p.label}</span>
                  <span className="block text-xs text-muted">{p.primary ? "Primary provider" : "Secondary provider"}</span>
                </span>
              </label>
            ))}
          </div>

          <div>
            <label htmlFor="base-url" className="block text-sm font-medium text-ink">Base URL</label>
            <input id="base-url" className={`${field} mt-1 font-mono`} value={baseUrl} spellCheck={false} placeholder={info?.default_base_url} onChange={(e) => setBaseUrl(e.target.value)} />
          </div>

          <div>
            <div className="flex flex-wrap items-center gap-2">
              <label htmlFor="token" className="block text-sm font-medium text-ink">Runtime token</label>
              <Badge tone={model.token_set ? "ok" : "neutral"}>{model.token_set ? "token set" : "no token set"}</Badge>
            </div>
            <input id="token" type="password" className={`${field} mt-1 font-mono`} value={token} autoComplete="new-password" spellCheck={false}
                   placeholder={model.token_set ? "Leave empty to keep the stored token" : "Paste the token"} onChange={(e) => setToken(e.target.value)} />
            {urlChanged && !token ? <p className="mt-1 text-xs text-muted">A different base URL needs the token entered again.</p> : null}
          </div>

          <div>
            <label htmlFor="model-id" className="block text-sm font-medium text-ink">Model / routing id</label>
            <input id="model-id" list="model-options" className={`${field} mt-1 font-mono`} value={modelId} spellCheck={false} placeholder={info?.default_model_id} onChange={(e) => setModelId(e.target.value)} />
            <datalist id="model-options">
              {(result?.models ?? []).map((m) => <option key={m} value={m} />)}
            </datalist>
            <p className="mt-1 text-xs text-muted">Run Test connection to fill this list with the models the server reports.</p>
          </div>

          <div className="flex flex-wrap gap-2">
            <button type="submit" className={btnPrimary} disabled={busy !== null}>{busy === "save" ? "Saving…" : "Save"}</button>
            <button type="button" className={btnSecondary} onClick={test} disabled={busy !== null}>{busy === "test" ? "Testing…" : "Test connection"}</button>
          </div>
        </fieldset>
      </form>

      <div aria-live="polite">
        {notice ? (
          <p role={notice.tone === "bad" ? "alert" : "status"} className={`mt-4 rounded-control border px-3 py-2 text-sm ${notice.tone === "ok" ? "border-ok-line bg-ok-bg text-ok-fg" : "border-bad-line bg-bad-bg text-bad-fg"}`}>
            {notice.text}
          </p>
        ) : null}
        {result ? <TestResult result={result} /> : null}
      </div>

      <div className="mt-6 space-y-1 border-t border-line pt-4 text-sm text-muted">
        <p>The underlying provider key (NVIDIA, OpenRouter, ...) is entered inside Meterless Nightshift, never here. This page only needs the Nightshift address, its runtime token and a model or routing id.</p>
        <p>In Nightshift, open the Console (top right) to find the Runtime URL and token. The default URL is <span className="font-mono text-xs">http://127.0.0.1:8088/v1</span>.</p>
        <p>The token is sent to the API once, kept in memory only, and never shown again.</p>
      </div>
    </section>
  );
}

export function SettingsScreen() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "missing" | "error">("loading");
  const [error, setError] = useState("");

  const load = () => {
    setState("loading");
    api.settings()
      .then((s) => {
        if (!s?.mode || !s.model) throw new Error("The settings response had an unexpected shape.");
        setSettings(s);
        setState("ready");
      })
      .catch((e) => {
        if (e instanceof HttpError && e.status === 404) return setState("missing");
        setError(e instanceof Error ? e.message : String(e));
        setState("error");
      });
  };
  useEffect(load, []);

  return (
    <section aria-labelledby="settings-h" className="space-y-6">
      <div>
        <h2 id="settings-h" className="text-lg font-semibold text-ink">Settings</h2>
        <p className="mt-0.5 text-sm text-muted">Which mode the API runs in and which model connection it uses.</p>
      </div>
      {state === "loading" ? <p role="status" className="text-sm text-muted">Loading settings…</p> : null}
      {state === "missing" ? (
        <div role="alert" className="rounded-card border border-warn-line bg-warn-bg p-4 text-sm text-warn-fg">
          <p className="font-medium">This API does not offer settings.</p>
          <p className="mt-1">It answered 404 for /settings, so it was built before the Settings API existed. Update and restart the API to configure the model here; nothing else in the app is affected.</p>
        </div>
      ) : null}
      {state === "error" ? (
        <div role="alert" className="rounded-card border border-bad-line bg-bad-bg p-4 text-sm text-bad-fg">
          <p>Could not load settings: {error}</p>
          <button type="button" onClick={load} className={`${btnSecondary} mt-3`}>Try again</button>
        </div>
      ) : null}
      {state === "ready" && settings ? (
        <>
          <Mode settings={settings} />
          <Provider settings={settings} onSaved={setSettings} />
        </>
      ) : null}
    </section>
  );
}
