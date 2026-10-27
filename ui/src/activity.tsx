import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "./api";
import type { Activity } from "./types";

const FAST_MS = 1000;
const SLOW_MS = 4000;

/** "off" until the first good answer, and again for good after a 404 or a network error: the feature is then simply absent. */
type Status = "loading" | "on" | "off";

interface ActivityState {
  status: Status;
  data: Activity | null;
  /** Date.now() when `data` arrived; elapsed times are `elapsed_s` plus the time since, so they tick without the server clock. */
  receivedAt: number;
  open: boolean;
  setOpen: (open: boolean) => void;
  /** Keeps polling at the fast rate while something on screen waits for a run; returns the release function. */
  boost: () => () => void;
}

const OFF: ActivityState = { status: "off", data: null, receivedAt: 0, open: false, setOpen: () => {}, boost: () => () => {} };
const Ctx = createContext<ActivityState>(OFF);

export const useActivity = () => useContext(Ctx);

/** Polls while a run is active (or something waits for one), otherwise slowly; `enabled` is false in SAMPLE mode. */
export function useActivityBoost(on: boolean) {
  const { boost } = useActivity();
  useEffect(() => (on ? boost() : undefined), [on, boost]);
}

const isActivity = (d: unknown): d is Activity =>
  !!d && typeof d === "object" && Array.isArray((d as Activity).active) && Array.isArray((d as Activity).recent);

export function ActivityProvider({ enabled, children }: { enabled: boolean; children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [data, setData] = useState<Activity | null>(null);
  const [receivedAt, setReceivedAt] = useState(0);
  const [open, setOpen] = useState(false);
  const [boosts, setBoosts] = useState(0);
  const busy = !!data && (data.active.length > 0 || !!data.report_job);

  const delay = useRef(SLOW_MS);
  delay.current = busy || open || boosts > 0 ? FAST_MS : SLOW_MS;
  const pollNow = useRef<() => void>(() => {});

  useEffect(() => {
    if (!enabled) {
      setStatus("loading");
      setData(null);
      return;
    }
    let stopped = false;
    let inflight = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const schedule = () => {
      clearTimeout(timer);
      timer = setTimeout(poll, delay.current);
    };
    const poll = async () => {
      clearTimeout(timer);
      if (stopped || inflight) return;
      if (document.hidden) return schedule();
      inflight = true;
      try {
        const d = await api.activity();
        if (stopped) return;
        if (!isActivity(d)) throw new Error("not an activity payload");
        setData(d);
        setReceivedAt(Date.now());
        setStatus("on");
        inflight = false;
        schedule();
      } catch {
        // 404 (older API) or unreachable: switch the feature off quietly and stop polling.
        if (!stopped) {
          stopped = true;
          setStatus("off");
          setData(null);
        }
      }
    };
    pollNow.current = poll;
    const onVisible = () => !document.hidden && poll();
    document.addEventListener("visibilitychange", onVisible);
    poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [enabled]);

  // Opening the panel or starting a wait should not sit out a pending slow timer.
  useEffect(() => {
    if (open || boosts > 0) pollNow.current();
  }, [open, boosts]);

  const boost = useCallback(() => {
    setBoosts((n) => n + 1);
    return () => setBoosts((n) => n - 1);
  }, []);

  const value = useMemo(() => ({ status: enabled ? status : "off", data, receivedAt, open, setOpen, boost }) as ActivityState, [enabled, status, data, receivedAt, open, boost]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** Wall-clock `Date.now()` that re-renders every second while `on`, so elapsed counters tick between polls. */
export function useNow(on: boolean): number {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (!on) return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [on]);
  return now;
}

/** Elapsed seconds of a polled run, advanced by the time since the poll arrived. */
export const liveElapsed = (elapsedS: number, receivedAt: number, now: number) => Math.max(0, elapsedS + Math.max(0, now - receivedAt) / 1000);

export function formatElapsed(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
