import { useEffect, useState } from "react";
import { ActivityProvider } from "./activity";
import { api } from "./api";
import { AskScreen } from "./components/AskScreen";
import { FindingScreen } from "./components/FindingScreen";
import { ReportScreen } from "./components/ReportScreen";
import { RunsScreen } from "./components/RunsScreen";
import { SettingsScreen } from "./components/SettingsScreen";
import { Shell } from "./components/Shell";
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
    <ActivityProvider enabled={!!health && !health.sample_mode}>
      <div className="min-h-dvh">
        <SyntheticBanner mode={mode} replay={!!health?.sample_mode} />
        <Shell screen={screen ?? ""} health={health} healthFailed={healthFailed}>
          <main>
            {screen === "finding" && arg ? <FindingScreen id={arg} health={health} /> :
             screen === "trace" && arg ? <TraceScreen runId={arg} health={health} /> :
             screen === "ask" ? <AskScreen health={health} /> :
             screen === "runs" ? <RunsScreen /> :
             screen === "settings" ? <SettingsScreen /> :
             <ReportScreen health={health} />}
          </main>
          <PoweredBy health={health} failed={healthFailed} />
        </Shell>
      </div>
    </ActivityProvider>
  );
}
