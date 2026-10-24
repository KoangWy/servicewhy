import { useEffect, useState } from "react";
import { api } from "./api";
import { FindingScreen } from "./components/FindingScreen";
import { ReportScreen } from "./components/ReportScreen";
import { TraceScreen } from "./components/TraceScreen";
import { SyntheticBanner } from "./components/common";
import type { Health } from "./types";

function useHashRoute(): [string, (p: string) => void] {
  const read = () => window.location.hash.replace(/^#/, "") || "/";
  const [path, setPath] = useState(read);
  useEffect(() => {
    const on = () => setPath(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return [path, (p: string) => { window.location.hash = p; }];
}

export default function App() {
  const [path, go] = useHashRoute();
  const [health, setHealth] = useState<Health | null>(null);
  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  const mode = health ? (health.sample_mode ? "sample mode: recorded run, no services" : `data: ${health.zetaris} · model: ${health.model}`) : undefined;
  const [, screen, arg] = path.split("/");
  return (
    <div className="app">
      <SyntheticBanner mode={mode} />
      <header>
        <h1 onClick={() => go("/")}>ServiceWhy</h1>
        <span className="tag">explains why service or revenue changed; a verifier blocks what the data does not support</span>
      </header>
      <main>
        {screen === "finding" && arg ? <FindingScreen id={arg} go={go} /> :
         screen === "trace" && arg ? <TraceScreen runId={arg} go={go} /> :
         <ReportScreen go={go} health={health} />}
      </main>
    </div>
  );
}
