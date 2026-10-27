import React from "react";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "./App";
import { formatElapsed } from "./activity";
import { stepStates } from "./components/Activity";
import type { Activity, ActiveRun, ActivityEvent } from "./types";

const live = { status: "ok", zetaris: "local", model: "live", sample_mode: false, sample_questions: ["Why was Saturday slow?"] };
const sample = { ...live, zetaris: "sample", model: "sample-replay", sample_mode: true };

const ev = (over: Partial<ActivityEvent> = {}): ActivityEvent => ({ event: "query", agent: "Investigator", action: "run_query", summary: "ok", status: "success", at: "2026-10-27T19:58:03Z", ...over });
const run = (over: Partial<ActiveRun> = {}): ActiveRun => ({
  run_id: "r1", kind: "ask", question: "Why was Saturday slow?", started_at: "2026-10-27T19:57:00Z", elapsed_s: 41.2, stage: "Verifier",
  counts: { events: 9, queries: 4, model_calls: 3, blocks: 1, retries: 1 }, model: "cloud/model-x", recent_events: [ev()], ...over,
});
const activity = (over: Partial<Activity> = {}): Activity => ({ now: "2026-10-27T19:58:03Z", active: [], recent: [], report_job: null, ...over });

class Failure {
  constructor(public status: number, public body: unknown) {}
}
// A route value may be a function of the request so a test can change the answer over time or hold a request open.
type Route = unknown | ((init?: RequestInit) => unknown);
let routes: Record<string, Route>;
let fetchMock: ReturnType<typeof vi.fn>;
const calls = (key: string) => fetchMock.mock.calls.filter(([url, init]) => `${init?.method ?? "GET"} ${url}` === key);

const useApi = (over: Record<string, Route> = {}) => {
  routes = { "/api/health": live, "/api/activity": activity(), "/api/reports": [{ report_id: "rep-1" }],
    "/api/reports/rep-1": { report_id: "rep-1", period: { start: "2026-09-28", end: "2026-10-04" }, summary: "Week summary.",
      findings: [], revenue_split: null, not_causes: [], insufficient: [], provenance: { data: "synthetic", channel: "c", model: "m", runs: [] } },
    ...over };
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    let r = routes[`${init?.method ?? "GET"} ${url}`] ?? routes[url];
    if (typeof r === "function") r = await (r as (i?: RequestInit) => unknown)(init);
    return r instanceof Failure
      ? { ok: false, status: r.status, statusText: "error", json: async () => r.body }
      : { ok: true, status: 200, json: async () => r };
  });
  vi.stubGlobal("fetch", fetchMock);
};

const flush = (ms = 0) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
const settle = async () => { for (let i = 0; i < 4; i++) await flush(); };
const pill = () => screen.getByTestId("activity-pill");
const openPanel = async () => { fireEvent.click(pill()); await settle(); return screen.getByRole("dialog", { name: "Activity" }); };

// A request that stays open until the test lets it finish.
const hold = () => {
  let release!: (v: unknown) => void;
  const promise = new Promise((r) => (release = r));
  return { route: () => promise, release };
};

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
  window.location.hash = "";
  useApi();
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

test("the pill is idle with a muted dot when nothing runs", async () => {
  render(<App />);
  await settle();
  expect(pill().textContent).toMatch(/Idle/);
  expect(pill().getAttribute("aria-expanded")).toBe("false");
  expect(pill().querySelector("svg")).toBeNull();
});

test("a running pill shows the spinner, the stage and an elapsed time that ticks each second", async () => {
  const t0 = Date.now();
  useApi({ "/api/activity": () => activity({ active: [run({ elapsed_s: 41 + (Date.now() - t0) / 1000 })] }) });
  render(<App />);
  await settle();
  expect(pill().textContent).toMatch(/Verifier/);
  expect(pill().querySelector("svg")).toBeTruthy();
  expect(screen.getByTestId("pill-elapsed").textContent).toBe("0:41");
  await flush(1000);
  expect(screen.getByTestId("pill-elapsed").textContent).toBe("0:42");
  await flush(3000);
  expect(screen.getByTestId("pill-elapsed").textContent).toBe("0:45");
  expect(pill().textContent).not.toMatch(/running\)/);
});

test("the elapsed time keeps ticking between polls", async () => {
  // Slow polling is not used while running, so make the server answer once and then fall silent for a moment.
  let n = 0;
  const gate = hold();
  useApi({ "/api/activity": () => (++n === 1 ? activity({ active: [run({ elapsed_s: 10 })] }) : gate.route()) });
  render(<App />);
  await settle();
  expect(screen.getByTestId("pill-elapsed").textContent).toBe("0:10");
  await flush(1000);
  await flush(1000);
  expect(screen.getByTestId("pill-elapsed").textContent).toBe("0:12");
});

test("several runs are counted next to the newest run's stage", async () => {
  useApi({ "/api/activity": activity({ active: [
    run({ run_id: "a", stage: "Writer", started_at: "2026-10-27T19:50:00Z" }),
    run({ run_id: "b", stage: "Planner", started_at: "2026-10-27T19:57:00Z" }),
    run({ run_id: "c", stage: "Investigator", started_at: "2026-10-27T19:56:00Z" }),
  ] }) });
  render(<App />);
  await settle();
  expect(pill().textContent).toMatch(/Planner/);
  expect(pill().textContent).toMatch(/\(3 running\)/);
});

test("a report job with no run in flight still shows as running", async () => {
  useApi({ "/api/activity": activity({ report_job: { started_at: "2026-10-27T19:50:00Z", elapsed_s: 125 } }) });
  render(<App />);
  await settle();
  expect(pill().textContent).toMatch(/Weekly report/);
  expect(screen.getByTestId("pill-elapsed").textContent).toBe("2:05");
});

test("the panel opens from the pill, closes with Escape and returns focus to the pill", async () => {
  render(<App />);
  await settle();
  const dialog = await openPanel();
  expect(pill().getAttribute("aria-expanded")).toBe("true");
  expect(document.activeElement).toBe(dialog);
  expect(within(dialog).getByText("Nothing is running.")).toBeTruthy();
  fireEvent.keyDown(window, { key: "Escape" });
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(document.activeElement).toBe(pill());
  expect(pill().getAttribute("aria-expanded")).toBe("false");
});

test("the Close button and the backdrop close the panel", async () => {
  render(<App />);
  await settle();
  const dialog = await openPanel();
  fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(document.activeElement).toBe(pill());
  await openPanel();
  fireEvent.click(screen.getByTestId("activity-backdrop"));
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("an open panel polls every second even when nothing is running", async () => {
  render(<App />);
  await settle();
  await flush(4000);
  const idle = calls("GET /api/activity").length;
  await openPanel();
  const afterOpen = calls("GET /api/activity").length;
  expect(afterOpen).toBe(idle + 1);
  await flush(3000);
  expect(calls("GET /api/activity").length).toBe(afterOpen + 3);
});

test("idle polling is slow and stops while the tab is hidden", async () => {
  render(<App />);
  await settle();
  const n = calls("GET /api/activity").length;
  await flush(4000);
  expect(calls("GET /api/activity").length).toBe(n + 1);
  Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
  await flush(12000);
  expect(calls("GET /api/activity").length).toBe(n + 1);
  Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
  fireEvent(document, new Event("visibilitychange"));
  await settle();
  expect(calls("GET /api/activity").length).toBe(n + 2);
});

test.each([
  [null, ["pending", "pending", "pending", "pending"]],
  ["Planner", ["active", "pending", "pending", "pending"]],
  ["Investigator", ["done", "active", "pending", "pending"]],
  ["Verifier", ["done", "done", "active", "pending"]],
  ["Writer", ["done", "done", "done", "active"]],
] as const)("the stepper for stage %s is %j", async (stage, expected) => {
  expect(stepStates(stage)).toEqual(expected);
  useApi({ "/api/activity": activity({ active: [run({ stage })] }) });
  render(<App />);
  await settle();
  const dialog = await openPanel();
  const steps = within(within(dialog).getByRole("list", { name: "Progress" })).getAllByRole("listitem");
  expect(steps.map((s) => s.getAttribute("data-state"))).toEqual(expected);
  expect(steps.map((s) => s.getAttribute("aria-current"))).toEqual(expected.map((s) => (s === "active" ? "step" : null)));
  // The state is also in the text, not only in the colour.
  expect(steps[0].textContent).toMatch(expected[0] === "done" ? /done/ : expected[0] === "active" ? /in progress/ : /pending/);
});

test("a retry back to an earlier stage keeps the earlier steps done and re-opens the current one", async () => {
  const q = { v: run({ stage: "Verifier" }) };
  useApi({ "/api/activity": () => activity({ active: [q.v] }) });
  render(<App />);
  await settle();
  const dialog = await openPanel();
  const states = () => within(dialog).getAllByRole("listitem").filter((li) => li.hasAttribute("data-state")).map((li) => li.getAttribute("data-state"));
  expect(states()).toEqual(["done", "done", "active", "pending"]);
  q.v = run({ stage: "Investigator" });
  await flush(1000);
  expect(states()).toEqual(["done", "active", "pending", "pending"]);
});

test("the panel shows kind, question, counters, model, and a link to the full trace per run", async () => {
  useApi({ "/api/activity": activity({ active: [run({ kind: "report", question: "Weekly: why did dinner revenue drop?" })] }) });
  render(<App />);
  await settle();
  const dialog = await openPanel();
  expect(within(dialog).getByText("Report")).toBeTruthy();
  expect(within(dialog).getByText("Weekly: why did dinner revenue drop?")).toBeTruthy();
  const counts = Object.fromEntries(Array.from(dialog.querySelectorAll("dl > div")).map((d) => [d.querySelector("dt")!.textContent, d.querySelector("dd")!.textContent]));
  expect(counts).toEqual({ Queries: "4", "Model calls": "3", Blocks: "1", Retries: "1" });
  expect(within(dialog).getByText("cloud/model-x")).toBeTruthy();
  expect(within(dialog).getByText(/Open full trace/).closest("a")?.getAttribute("href")).toBe("#/trace/r1");
  expect(screen.getByTestId("run-elapsed").textContent).toBe("0:41");
});

test("the panel lists the last finished runs with status, time and a trace link", async () => {
  const recent = Array.from({ length: 12 }, (_, i) => ({ run_id: `f${i}`, kind: "ask", question: `Finished question ${i}`, status: (i === 1 ? "error" : "success") as "error" | "success", elapsed_s: 85 + i, finished_at: "2026-10-27T19:50:00Z" }));
  useApi({ "/api/activity": activity({ recent }) });
  render(<App />);
  await settle();
  const dialog = await openPanel();
  const items = within(dialog).getAllByText(/Finished question/);
  expect(items).toHaveLength(10);
  expect(items[0].closest("a")?.getAttribute("href")).toBe("#/trace/f0");
  expect(items[1].closest("li")!.textContent).toMatch(/error/);
  expect(items[0].closest("li")!.textContent).toMatch(/1:25/);
});

test("the feed prints agent, action and summary, marks block and retry, and keeps the newest 12 lines", async () => {
  const events = Array.from({ length: 15 }, (_, i) => ev({ agent: "Verifier", action: "check_evidence", summary: `step ${i}` }));
  events[14] = ev({ event: "block", agent: "Verifier", action: "block_claim", summary: "V2: n=6 < 15" });
  events[13] = ev({ event: "retry", agent: "Orchestrator", action: "widen_and_retry", summary: "retry 1" });
  useApi({ "/api/activity": activity({ active: [run({ recent_events: events })] }) });
  render(<App />);
  await settle();
  const dialog = await openPanel();
  const feed = within(dialog).getByRole("region", { name: "Recent steps" });
  const lines = within(feed).getAllByRole("listitem");
  expect(lines).toHaveLength(12);
  expect(lines[0].textContent).toBe("Verifier  check_evidence  step 3");
  expect(lines[10].textContent).toBe("[retry]Orchestrator  widen_and_retry  retry 1");
  expect(lines[11].textContent).toBe("[block]Verifier  block_claim  V2: n=6 < 15");
  expect(lines[11].getAttribute("data-event")).toBe("block");
  expect(feed.closest("[aria-live]")).toBeNull();
});

test("the feed follows the newest line unless the reader scrolled up", async () => {
  const q = { events: [ev({ summary: "first" })] };
  useApi({ "/api/activity": () => activity({ active: [run({ recent_events: q.events })] }) });
  render(<App />);
  await settle();
  const dialog = await openPanel();
  const feed = within(dialog).getByRole("region", { name: "Recent steps" });
  // jsdom has no layout, so give the box a geometry: 1000px of content in a 100px window.
  Object.defineProperty(feed, "scrollHeight", { configurable: true, get: () => 1000 });
  Object.defineProperty(feed, "clientHeight", { configurable: true, get: () => 100 });
  q.events = [...q.events, ev({ summary: "second" })];
  await flush(1000);
  expect(feed.scrollTop).toBe(1000);
  feed.scrollTop = 200;
  fireEvent.scroll(feed);
  q.events = [...q.events, ev({ summary: "third" })];
  await flush(1000);
  expect(feed.scrollTop).toBe(200);
});

test("a 404 from /activity switches the feature off quietly and stops polling", async () => {
  useApi({ "/api/activity": new Failure(404, { detail: "Not Found" }) });
  render(<App />);
  await settle();
  expect(screen.queryByTestId("activity-pill")).toBeNull();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(document.body.textContent).not.toMatch(/Not Found|activity/i);
  await flush(20000);
  expect(calls("GET /api/activity")).toHaveLength(1);
});

test("an unreachable /activity also switches the feature off", async () => {
  useApi({ "/api/activity": () => { throw new TypeError("Failed to fetch"); } });
  render(<App />);
  await settle();
  expect(screen.queryByTestId("activity-pill")).toBeNull();
  expect(screen.queryByRole("alert")).toBeNull();
  await flush(20000);
  expect(calls("GET /api/activity")).toHaveLength(1);
});

test("SAMPLE mode never polls /activity and shows no pill", async () => {
  useApi({ "/api/health": sample });
  render(<App />);
  await settle();
  await flush(20000);
  expect(calls("GET /api/activity")).toHaveLength(0);
  expect(screen.queryByTestId("activity-pill")).toBeNull();
});

test("elapsed times print as m:ss", () => {
  expect([0, 7.9, 59, 60, 61.5, 600, 3725].map(formatElapsed)).toEqual(["0:00", "0:07", "0:59", "1:00", "1:01", "10:00", "62:05"]);
});

// ---- Ask ----

const ask = async (q = "Why was Saturday slow?") => {
  fireEvent.change(screen.getByLabelText("question"), { target: { value: q } });
  fireEvent.click(screen.getByRole("button", { name: "Ask" }));
  await settle();
};
const askRender = async () => { window.location.hash = "/ask"; render(<App />); await settle(); };

test("Ask sends its own ui- run id and binds the inline progress to exactly that run", async () => {
  const gate = hold();
  useApi({ "POST /api/run": gate.route, "/api/activity": () => {
    const id = JSON.parse(calls("POST /api/run")[0]?.[1].body ?? "{}").run_id;
    return activity({ active: [run({ run_id: "someone-else", question: "Other person's question", stage: "Writer" }), run({ run_id: id, stage: "Investigator", recent_events: [ev({ summary: "my own step" })] })] });
  } });
  await askRender();
  await ask();
  const body = JSON.parse(calls("POST /api/run")[0][1].body);
  expect(body.run_id).toMatch(/^ui-[0-9a-f]{8}$/);
  expect(body.input.query).toBe("Why was Saturday slow?");
  await flush(1000);
  const waiting = screen.getByTestId("waiting");
  expect(within(waiting).getByText("Working…")).toBeTruthy();
  expect(within(waiting).getByText("my own step", { exact: false })).toBeTruthy();
  expect(within(waiting).queryByText("Other person's question")).toBeNull();
  const states = within(waiting).getAllByRole("listitem").filter((li) => li.hasAttribute("data-state")).map((li) => li.getAttribute("data-state"));
  expect(states).toEqual(["done", "active", "pending", "pending"]);
  // The submit button is disabled while the request is in flight, and a second submit is ignored.
  expect((screen.getByRole("button", { name: "Investigating…" }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.submit(screen.getByLabelText("question").closest("form")!);
  await settle();
  expect(calls("POST /api/run")).toHaveLength(1);
  gate.release({ run_id: body.run_id, status: "success", question: "q",
    output: { summary: "Saturday was slow because of staffing.", answer_type: "answer", findings: [], not_causes: [], insufficient: [], revenue_split: null } });
  await settle();
  expect(screen.getByText("Saturday was slow because of staffing.")).toBeTruthy();
  expect(screen.queryByTestId("waiting")).toBeNull();
});

test("Ask counts the wait with its own clock and falls back to Working… when /activity is missing", async () => {
  const gate = hold();
  useApi({ "POST /api/run": gate.route, "/api/activity": new Failure(404, { detail: "Not Found" }) });
  await askRender();
  await ask();
  expect(screen.getByRole("status").textContent).toBe("Working…");
  expect(screen.getByTestId("waiting-elapsed").textContent).toBe("0:00");
  await flush(5000);
  expect(screen.getByTestId("waiting-elapsed").textContent).toBe("0:05");
  expect(screen.queryByRole("list", { name: "Progress" })).toBeNull();
  expect(screen.queryByRole("alert")).toBeNull();
});

test("Ask in SAMPLE mode still shows a plain Working… with elapsed time while it waits", async () => {
  const gate = hold();
  useApi({ "/api/health": sample, "POST /api/run": gate.route });
  await askRender();
  await ask();
  expect(screen.getByTestId("waiting").textContent).toMatch(/Working…/);
  expect(calls("GET /api/activity")).toHaveLength(0);
});

// ---- Dashboard ----

const generateBtn = () => screen.getByRole("button", { name: "Generate weekly report" });

test("an empty dashboard shows the empty state and does not create a report on mount, also under StrictMode", async () => {
  useApi({ "/api/reports": [] });
  render(<React.StrictMode><App /></React.StrictMode>);
  await settle();
  await flush(10000);
  expect(screen.getByText("No weekly report yet")).toBeTruthy();
  expect(generateBtn()).toBeTruthy();
  expect(calls("POST /api/reports")).toHaveLength(0);
});

test("the Generate button posts exactly once on a double click, shows progress, then the report", async () => {
  const gate = hold();
  let list: unknown[] = [];
  useApi({ "/api/reports": () => list, "POST /api/reports": gate.route });
  render(<React.StrictMode><App /></React.StrictMode>);
  await settle();
  const btn = generateBtn();
  fireEvent.click(btn);
  fireEvent.click(btn);
  await settle();
  expect(calls("POST /api/reports")).toHaveLength(1);
  expect(screen.queryByRole("button", { name: "Generate weekly report" })).toBeNull();
  expect(screen.getByText("Generating the weekly report…")).toBeTruthy();
  expect(screen.getByText(/takes several minutes/)).toBeTruthy();
  list = [{ report_id: "rep-1" }];
  await flush(3000);
  expect(screen.getByText("Week summary.")).toBeTruthy();
  expect(calls("POST /api/reports")).toHaveLength(1);
  gate.release({ report_id: "rep-1" });
  await settle();
  expect(screen.getByText("Week summary.")).toBeTruthy();
});

test("a 409 ReportInProgress is not an error: it switches to progress and loads the report when it appears", async () => {
  let list: unknown[] = [];
  const job = { started_at: "2026-10-27T19:50:00Z", elapsed_s: 30 };
  const q = { act: activity() };
  useApi({
    "/api/reports": () => list,
    "POST /api/reports": new Failure(409, { status: "error", error: { type: "ReportInProgress", message: "a report is already being generated", recoverable: true }, report_job: job }),
    "/api/activity": () => q.act,
  });
  render(<App />);
  await settle();
  fireEvent.click(generateBtn());
  // The other generation shows up in /activity from the next poll on.
  q.act = activity({ report_job: job, active: [run({ kind: "report", question: "Weekly: dinner revenue", stage: "Investigator" })] });
  await flush(1000);
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.getByText("Generating the weekly report…")).toBeTruthy();
  expect(screen.getByText("Weekly: dinner revenue")).toBeTruthy();
  expect(screen.getByTestId("waiting-elapsed").textContent).toBe("0:30");
  list = [{ report_id: "rep-1" }];
  await flush(3000);
  expect(screen.getByText("Week summary.")).toBeTruthy();
  expect(calls("POST /api/reports")).toHaveLength(1);
});

test("after a reload mid-generation the dashboard shows the running job without posting anything", async () => {
  let list: unknown[] = [];
  useApi({ "/api/reports": () => list, "/api/activity": activity({ report_job: { started_at: "2026-10-27T19:50:00Z", elapsed_s: 95 } }) });
  render(<React.StrictMode><App /></React.StrictMode>);
  await settle();
  expect(screen.getByText("Generating the weekly report…")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Generate weekly report" })).toBeNull();
  expect(screen.getByTestId("waiting-elapsed").textContent).toBe("1:35");
  list = [{ report_id: "rep-1" }];
  await flush(3000);
  expect(screen.getByText("Week summary.")).toBeTruthy();
  expect(calls("POST /api/reports")).toHaveLength(0);
});

test("a 409 ends the wait when the other generation vanishes without a report", async () => {
  const q = { act: activity() };
  useApi({
    "/api/reports": [],
    "POST /api/reports": new Failure(409, { status: "error", error: { type: "ReportInProgress", message: "m", recoverable: true } }),
    "/api/activity": () => q.act,
  });
  render(<App />);
  await settle();
  fireEvent.click(generateBtn());
  q.act = activity({ report_job: { started_at: "2026-10-27T19:50:00Z", elapsed_s: 5 } });
  await flush(1000);
  expect(screen.getByText("Generating the weekly report…")).toBeTruthy();
  q.act = activity();
  await flush(5000);
  expect(generateBtn()).toBeTruthy();
});

test("a failed generation shows the error and the button again", async () => {
  useApi({ "/api/reports": [], "POST /api/reports": new Failure(500, { status: "error", error: { type: "ReportFailed", message: "model unreachable", recoverable: true } }) });
  render(<App />);
  await settle();
  fireEvent.click(generateBtn());
  await settle();
  expect(screen.getByRole("alert").textContent).toMatch(/ReportFailed: model unreachable/);
  expect(generateBtn()).toBeTruthy();
});

test("in SAMPLE mode an existing report is shown as before", async () => {
  useApi({ "/api/health": sample });
  render(<App />);
  await settle();
  expect(screen.getByText("Week summary.")).toBeTruthy();
  expect(calls("POST /api/reports")).toHaveLength(0);
});
