import { useEffect, useState, type ReactNode } from "react";
import type { Health } from "../types";
import { useActivity } from "../activity";
import { ActivityControl } from "./Activity";
import { Wordmark } from "./Brand";
import { Badge } from "./common";

type NavId = "dashboard" | "ask" | "runs" | "settings";

const ITEMS: { id: NavId; label: string; href: string }[] = [
  { id: "dashboard", label: "Dashboard", href: "#/" },
  { id: "ask", label: "Ask", href: "#/ask" },
  { id: "runs", label: "Runs", href: "#/runs" },
  { id: "settings", label: "Settings", href: "#/settings" },
];

/** Findings belong to the report and traces to runs, so those detail screens keep their parent item active. */
export function activeItem(screen: string): NavId {
  if (screen === "ask" || screen === "runs" || screen === "settings") return screen;
  return screen === "trace" ? "runs" : "dashboard";
}

function ModeBadge({ health, failed }: { health: Health | null; failed: boolean }) {
  const [tone, text] = health
    ? health.sample_mode ? (["warn", "Mode: SAMPLE"] as const) : (["neutral", "Mode: FULL"] as const)
    : failed ? (["bad", "Mode unknown"] as const) : (["neutral", "Checking mode…"] as const);
  return <span data-testid="shell-mode"><Badge tone={tone}>{text}</Badge></span>;
}

export function Shell({ screen, health, healthFailed, children }: { screen: string; health: Health | null; healthFailed: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const pill = useActivity().status === "on";
  const active = activeItem(screen);
  useEffect(() => setOpen(false), [screen]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col md:flex-row">
      <aside className="sticky top-0 z-10 border-b border-line bg-bg md:h-dvh md:max-h-dvh md:w-60 md:shrink-0 md:overflow-y-auto md:border-b-0 md:border-r">
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 px-4 py-3 md:block md:px-5 md:py-8">
          <div className="order-1 md:order-none">
            <h1>
              <a href="#/" className="inline-block rounded-sm" aria-label="ServiceWhy, home"><Wordmark /></a>
            </h1>
            <p className="mt-2 hidden text-[11px] font-semibold uppercase tracking-[0.14em] text-faint md:block">No receipt, no claim.</p>
            <p className="mt-1 hidden text-sm text-muted md:block">Explains why service or revenue changed; a verifier blocks what the data does not support.</p>
          </div>
          {/* With the activity pill the badges take their own row on a phone; without it everything stays on one row. */}
          <div className={`flex min-w-0 flex-wrap items-center gap-2 md:order-none md:mt-4 md:w-auto ${pill ? "order-3 w-full" : "order-2"}`}>
            <ModeBadge health={health} failed={healthFailed} />
            <ActivityControl />
          </div>
          <button
            type="button"
            aria-expanded={open}
            aria-controls="main-nav"
            onClick={() => setOpen(!open)}
            className={`inline-flex min-h-10 items-center rounded-control border border-line-strong bg-surface px-3 text-sm font-medium text-ink hover:bg-surface-2 md:hidden ${pill ? "order-2" : "order-3"}`}
          >
            {open ? "Close menu" : "Menu"}
          </button>
        </div>
        <nav id="main-nav" aria-label="Main" className={`${open ? "block" : "hidden"} px-3 pb-3 md:block md:px-3 md:pb-6`}>
          <ul className="flex flex-col gap-1">
            {ITEMS.map((it) => (
              <li key={it.id}>
                <a
                  href={it.href}
                  aria-current={it.id === active ? "page" : undefined}
                  className={`flex min-h-10 items-center rounded-control px-3 text-sm transition-colors duration-150 ${
                    it.id === active ? "bg-accent-soft font-semibold text-accent-ink" : "font-medium text-muted hover:bg-surface-2 hover:text-ink"
                  }`}
                >
                  {it.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      </aside>
      <div className="min-w-0 flex-1 px-4 pb-4 pt-8 sm:px-6 md:pt-10">{children}</div>
    </div>
  );
}
