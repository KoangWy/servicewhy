import { render, screen, waitFor, fireEvent, cleanup, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "./App";
import type { ConnectionTest, Settings } from "./types";

const health = { status: "ok", zetaris: "sample", model: "sample-replay", sample_mode: true, sample_questions: ["Why was Saturday slow?", "Who is our worst server?"] };
const liveHealth = { status: "ok", zetaris: "local", model: "live", sample_mode: false, sample_questions: null };

const providers: Settings["providers"] = [
  { id: "meterless", label: "Meterless Nightshift", primary: true, default_base_url: "http://127.0.0.1:8088/v1", default_model_id: "meterless/auto" },
  { id: "opencode", label: "OpenCode Go", primary: false, default_base_url: "https://opencode.ai/zen/go/v1", default_model_id: "deepseek-v4.1-flash" },
];
const settings = (over: Partial<Settings> = {}): Settings => ({
  mode: { sample_mode: false, data_backend: "local", model_mode: "live" },
  model: { provider: "meterless", base_url: "http://127.0.0.1:8088/v1", model_id: "meterless/auto", token_set: false, source: "env" },
  providers,
  ...over,
});

const answer = { run_id: "r9", status: "success", question: "Why was Saturday slow?",
  output: { summary: "Saturday was slow because of staffing.", answer_type: "answer", findings: [], not_causes: [], insufficient: [], revenue_split: null } };

class Failure {
  constructor(public status: number, public body: unknown) {}
}

// Routes are keyed by "METHOD /api/path"; a bare path means GET. Every call is recorded for assertions.
let routes: Record<string, unknown>;
let fetchMock: ReturnType<typeof vi.fn>;
const calls = (key: string) => fetchMock.mock.calls.filter(([url, init]) => `${init?.method ?? "GET"} ${url}` === key);

const useApi = (over: Record<string, unknown> = {}) => {
  routes = {
    "/api/health": health,
    "/api/reports": [{ report_id: "rep-1" }],
    "/api/reports/rep-1": { report_id: "rep-1", period: { start: "2026-09-28", end: "2026-10-04" }, summary: "Week summary.",
      findings: [], revenue_split: null, not_causes: [], insufficient: [], provenance: { data: "synthetic", channel: "c", model: "m", runs: [] } },
    "/api/runs": [],
    "/api/settings": settings(),
    ...over,
  };
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const r = routes[`${init?.method ?? "GET"} ${url}`] ?? routes[url];
    return r instanceof Failure
      ? { ok: false, status: r.status, statusText: "error", json: async () => r.body }
      : { ok: true, status: 200, json: async () => r };
  });
  vi.stubGlobal("fetch", fetchMock);
};

beforeEach(() => { window.location.hash = ""; useApi(); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const nav = () => screen.getByRole("navigation", { name: "Main" });
const current = () => within(nav()).getAllByRole("link").filter((a) => a.getAttribute("aria-current") === "page").map((a) => a.textContent);

test("the nav lists the four screens and marks the active one", async () => {
  render(<App />);
  expect(within(nav()).getAllByRole("link").map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
    ["Dashboard", "#/"], ["Ask", "#/ask"], ["Runs", "#/runs"], ["Settings", "#/settings"],
  ]);
  expect(current()).toEqual(["Dashboard"]);
});

test.each([
  ["/ask", "Ask"], ["/runs", "Runs"], ["/settings", "Settings"], ["/trace/r1", "Runs"], ["/finding/fnd_1", "Dashboard"],
])("on %s the active nav item is %s", async (hash, label) => {
  window.location.hash = hash;
  render(<App />);
  expect(current()).toEqual([label]);
});

test("the menu button toggles the nav and reports its state", () => {
  render(<App />);
  const menu = screen.getByRole("button", { name: "Menu" });
  expect(menu.getAttribute("aria-expanded")).toBe("false");
  fireEvent.click(menu);
  expect(screen.getByRole("button", { name: "Close menu" }).getAttribute("aria-expanded")).toBe("true");
  expect(screen.getByRole("button", { name: "Close menu" }).getAttribute("aria-controls")).toBe(nav().id);
  fireEvent.keyDown(window, { key: "Escape" });
  expect(screen.getByRole("button", { name: "Menu" }).getAttribute("aria-expanded")).toBe("false");
});

test("the shell badge shows SAMPLE or FULL from /health", async () => {
  render(<App />);
  await waitFor(() => expect(screen.getByTestId("shell-mode").textContent).toBe("Mode: SAMPLE"));
  cleanup();
  useApi({ "/api/health": liveHealth });
  render(<App />);
  await waitFor(() => expect(screen.getByTestId("shell-mode").textContent).toBe("Mode: FULL"));
});

test("the dashboard links to Ask and no longer holds the ask form", async () => {
  render(<App />);
  expect(screen.getByRole("link", { name: "Ask a question" }).getAttribute("href")).toBe("#/ask");
  expect(screen.queryByLabelText("question")).toBeNull();
});

test("Ask shows the sample questions as chips and renders the answer with its trace link", async () => {
  window.location.hash = "/ask";
  useApi({ "POST /api/run": answer, "/api/traces/r9": { run_id: "r9", events: [] } });
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Why was Saturday slow?" }));
  expect(await screen.findByText("Saturday was slow because of staffing.")).toBeTruthy();
  expect(screen.getByText(/Evidence & trace/).closest("a")?.getAttribute("href")).toBe("#/trace/r9");
  expect((screen.getByLabelText("question") as HTMLInputElement).value).toBe("Why was Saturday slow?");
  expect(JSON.parse(calls("POST /api/run")[0][1].body)).toEqual({ input: { query: "Why was Saturday slow?" } });
});

test("Ask explains a SampleModeMiss and lists the recorded questions", async () => {
  window.location.hash = "/ask";
  useApi({ "POST /api/run": new Failure(404, { status: "error", error: { type: "SampleModeMiss", message: "no", recoverable: true,
    available_questions: ["Why was Saturday slow?", "Who is our worst server?"] } }) });
  render(<App />);
  fireEvent.change(await screen.findByLabelText("question"), { target: { value: "What is the weather?" } });
  fireEvent.click(screen.getByRole("button", { name: "Ask" }));
  expect(await screen.findByText("That question was not recorded.")).toBeTruthy();
  expect(screen.getByText(/SAMPLE mode replays recorded runs/)).toBeTruthy();
  const alert = screen.getByRole("alert");
  expect(within(alert).getAllByRole("button").map((b) => b.textContent)).toEqual(["Why was Saturday slow?", "Who is our worst server?"]);
});

test("Runs lists runs newest first, each linking to its trace", async () => {
  window.location.hash = "/runs";
  useApi({ "/api/runs": [{ run_id: "r1", question: "First question", status: "success" }, { run_id: "r2", question: "Second question", status: "error" }] });
  render(<App />);
  const links = (await screen.findAllByText(/question$/)).map((e) => e.closest("a")!.getAttribute("href"));
  expect(links).toEqual(["#/trace/r2", "#/trace/r1"]);
});

test("Runs has an empty state and an error state", async () => {
  window.location.hash = "/runs";
  render(<App />);
  expect(await screen.findByText("No runs yet.")).toBeTruthy();
  cleanup();
  useApi({ "/api/runs": new Failure(500, { detail: "boom" }) });
  render(<App />);
  expect(await screen.findByText("Could not load runs: Error: boom")).toBeTruthy();
});

test("Settings in SAMPLE mode shows the notice and disables the form", async () => {
  window.location.hash = "/settings";
  useApi({ "/api/settings": settings({ mode: { sample_mode: true, data_backend: "local", model_mode: "replay" } }) });
  render(<App />);
  expect(await screen.findByText("SAMPLE replays recorded runs. Model settings are not used here. To run the agent for real, follow path B in the README.")).toBeTruthy();
  for (const el of [screen.getByLabelText("Base URL"), screen.getByLabelText("Runtime token"), screen.getByLabelText("Model / routing id"),
                    screen.getByRole("button", { name: "Save" }), screen.getByRole("button", { name: "Test connection" })]) {
    expect(el.matches(":disabled")).toBe(true);
  }
});

test("Settings preselects Meterless, never prefills the token and fills a provider's defaults on switch", async () => {
  window.location.hash = "/settings";
  render(<App />);
  expect(((await screen.findByRole("radio", { name: /Meterless Nightshift/ })) as HTMLInputElement).checked).toBe(true);
  expect((screen.getByLabelText("Runtime token") as HTMLInputElement).value).toBe("");
  expect(screen.getByText("no token set")).toBeTruthy();
  fireEvent.click(screen.getByRole("radio", { name: /OpenCode Go/ }));
  expect((screen.getByLabelText("Base URL") as HTMLInputElement).value).toBe("https://opencode.ai/zen/go/v1");
  expect((screen.getByLabelText("Model / routing id") as HTMLInputElement).value).toBe("deepseek-v4.1-flash");
});

test("Settings save sends the form, clears the token field and never persists the token", async () => {
  window.location.hash = "/settings";
  const saved = settings({ model: { provider: "meterless", base_url: "http://127.0.0.1:8088/v1", model_id: "meterless/auto", token_set: true, source: "runtime" } });
  useApi({ "PUT /api/settings/model": saved });
  render(<App />);
  fireEvent.change(await screen.findByLabelText("Runtime token"), { target: { value: "secret-token-1" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByText(/^Saved\./)).toBeTruthy();
  const [url, init] = calls("PUT /api/settings/model")[0];
  expect(url).toBe("/api/settings/model");
  expect(JSON.parse(init.body)).toEqual({ provider: "meterless", base_url: "http://127.0.0.1:8088/v1", model_id: "meterless/auto", token: "secret-token-1" });
  expect(screen.getByText("token set")).toBeTruthy();
  expect((screen.getByLabelText("Runtime token") as HTMLInputElement).value).toBe("");
  expect(document.body.innerHTML).not.toContain("secret-token-1");
  for (const store of [window.localStorage, window.sessionStorage]) expect(JSON.stringify({ ...store })).not.toContain("secret-token-1");
  expect(window.location.href).not.toContain("secret-token-1");
});

test("Settings omits the token field when none was typed", async () => {
  window.location.hash = "/settings";
  useApi({ "PUT /api/settings/model": settings() });
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Save" }));
  await screen.findByText(/^Saved\./);
  expect(JSON.parse(calls("PUT /api/settings/model")[0][1].body)).not.toHaveProperty("token");
});

test("Settings explains TokenRequiredForNewBaseUrl", async () => {
  window.location.hash = "/settings";
  useApi({ "PUT /api/settings/model": new Failure(422, { status: "error", error: { type: "TokenRequiredForNewBaseUrl", message: "m", recoverable: true } }) });
  render(<App />);
  fireEvent.change(await screen.findByLabelText("Base URL"), { target: { value: "http://example.test/v1" } });
  expect(screen.getByText("A different base URL needs the token entered again.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByText(/Enter the runtime token again to use a different base URL\. A stored token is never sent to a new host/)).toBeTruthy();
  expect((screen.getByLabelText("Base URL") as HTMLInputElement).value).toBe("http://example.test/v1");
});

test("Settings shows other save errors with their type", async () => {
  window.location.hash = "/settings";
  useApi({ "PUT /api/settings/model": new Failure(409, { status: "error", error: { type: "SampleModeNoModel", message: "SAMPLE mode replays recorded runs", recoverable: true } }) });
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Save" }));
  expect(await screen.findByText("SampleModeNoModel: SAMPLE mode replays recorded runs")).toBeTruthy();
});

const okTest: ConnectionTest = { ok: true, provider: "meterless", base_url: "http://127.0.0.1:8088/v1", latency_ms: 412, models: ["gpt-a", "gpt-b"],
  selected_model: "meterless/auto", selected_model_available: true, error: null };

test("Test connection shows each check, the latency and fills the model list, without saving", async () => {
  window.location.hash = "/settings";
  useApi({ "POST /api/settings/test": okTest });
  render(<App />);
  fireEvent.change(await screen.findByLabelText("Runtime token"), { target: { value: "try-token" } });
  fireEvent.click(screen.getByRole("button", { name: "Test connection" }));
  const result = await screen.findByTestId("test-result");
  expect(result.textContent).toMatch(/Connection works\.\s*412 ms/);
  for (const label of ["Reachable", "Authenticated", "Models found", "Selected model available", "Test reply received"]) {
    const row = within(result).getByText(label).closest("li")!;
    expect(row.textContent).toMatch(/^Yes/);
  }
  expect(Array.from(document.querySelectorAll("#model-options option")).map((o) => o.getAttribute("value"))).toEqual(["gpt-a", "gpt-b"]);
  expect(JSON.parse(calls("POST /api/settings/test")[0][1].body)).toMatchObject({ provider: "meterless", token: "try-token" });
  expect(calls("PUT /api/settings/model")).toHaveLength(0);
});

test("Test connection shows the model that answered and warns when it is an on-device model", async () => {
  window.location.hash = "/settings";
  useApi({ "POST /api/settings/test": { ...okTest, routed_model: "webllm/Llama-3.2-1B-Instruct-q4f16_1-MLC",
    note: "meterless/auto was routed to the on-device model webllm/Llama-3.2-1B-Instruct-q4f16_1-MLC. Pick a cloud model." } });
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Test connection" }));
  const result = await screen.findByTestId("test-result");
  expect(result.textContent).toMatch(/Answered by\s*webllm\/Llama-3\.2-1B/);
  expect((await screen.findByTestId("test-note")).textContent).toMatch(/on-device model/);
});

test("Test connection failure shows the error type, message and hint, and marks later checks as not run", async () => {
  window.location.hash = "/settings";
  useApi({ "POST /api/settings/test": { ...okTest, ok: false, latency_ms: 0, models: [], selected_model_available: false,
    error: { type: "Unreachable", message: "Connection refused", hint: "Start Meterless Nightshift and check the Runtime URL." } } });
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Test connection" }));
  const result = await screen.findByTestId("test-result");
  expect(result.getAttribute("role")).toBe("alert");
  expect(result.textContent).toMatch(/Connection test failed\./);
  expect(result.textContent).toMatch(/Unreachable: Connection refused/);
  expect(result.textContent).toMatch(/Start Meterless Nightshift and check the Runtime URL\./);
  expect(within(result).getByText("Reachable").closest("li")!.textContent).toMatch(/^No/);
  expect(within(result).getByText("Authenticated").closest("li")!.textContent).toMatch(/^Not checked/);
});

test("Test connection distinguishes an unavailable model from a failed chat", async () => {
  window.location.hash = "/settings";
  useApi({ "POST /api/settings/test": { ...okTest, ok: false, selected_model_available: false,
    error: { type: "ModelUnavailable", message: "meterless/auto is not listed", hint: "Connect a provider in Nightshift." } } });
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Test connection" }));
  const result = await screen.findByTestId("test-result");
  expect(within(result).getByText("Authenticated").closest("li")!.textContent).toMatch(/^Yes/);
  expect(within(result).getByText("Selected model available").closest("li")!.textContent).toMatch(/^No/);
  expect(within(result).getByText("Test reply received").closest("li")!.textContent).toMatch(/^Not checked/);
});

test("Settings degrades to a clear message when the API has no /settings", async () => {
  window.location.hash = "/settings";
  useApi({ "/api/settings": new Failure(404, { detail: "Not Found" }) });
  render(<App />);
  expect(await screen.findByText("This API does not offer settings.")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  expect(nav()).toBeTruthy();
});

test("Settings reports other load failures and can retry", async () => {
  window.location.hash = "/settings";
  useApi({ "/api/settings": new Failure(500, { detail: "boom" }) });
  render(<App />);
  expect(await screen.findByText("Could not load settings: boom")).toBeTruthy();
  routes["/api/settings"] = settings();
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByRole("button", { name: "Save" })).toBeTruthy();
});
