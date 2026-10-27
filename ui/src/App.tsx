import { useEffect, useState } from "react";
import { api } from "./api";
import { FindingScreen } from "./components/FindingScreen";
import { ReportScreen } from "./components/ReportScreen";
import { TraceScreen } from "./components/TraceScreen";
import { PoweredBy, SyntheticBanner } from "./components/common";
import type { Health } from "./types";

function useHashRoute(): string {
  const read = () => window.location.hash.replace(/^#/, "") || "/";
  const [path, setPath] = useState(read);
  useEffect(() => {
    let current = path;
    const on = () => {
      const next = read();
      if (next === current) return;
      current = next;
      setPath(next);
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return path;
}

export default function App() {
  const path = useHashRoute();
  const [health, setHealth] = useState<Health | null>(null);
  const [healthFailed, setHealthFailed] = useState(false);
  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealthFailed(true));
  }, []);

  const mode = health
    ? health.sample_mode ? "sample mode: recorded run, no services" : `data: ${health.zetaris} · model: ${health.model}`
    : healthFailed ? "mode unknown: the API did not answer /health" : "checking mode…";
  const [, screen, arg] = path.split("/");
  return (
    <div className="min-h-dvh">
      <SyntheticBanner mode={mode} replay={!!health?.sample_mode} />
      <div className="mx-auto w-full max-w-4xl px-4 sm:px-6">
        <header className="py-8 sm:py-10">
          <h1 className="text-2xl font-semibold tracking-tight text-ink">
            <a href="#/" className="rounded-sm">ServiceWhy</a>
          </h1>
          <p className="mt-1 max-w-2xl text-muted">Explains why service or revenue changed; a verifier blocks what the data does not support.</p>
        </header>
        <main>
          {screen === "finding" && arg ? <FindingScreen id={arg} health={health} /> :
           screen === "trace" && arg ? <TraceScreen runId={arg} health={health} /> :
           <ReportScreen health={health} />}
        </main>
        <PoweredBy health={health} failed={healthFailed} />
      </div>
    </div>
  );
}
