# ServiceWhy — Implementation Spec

**Status: agreed 2026-10-24 (design grilling complete). This is the canonical spec for the
submission build.** Team decisions of record: strategy repo `decisions/0002` (Track 02, de-scoped
cut, scale seams) and `decisions/0003` (roster, all-new work, repo). Concept of record:
`track/restaurant-service-concept.md` (strategy repo). Judge-facing execution standard:
HackOS *Technical Execution Guide* snapshot (`docs/hackos_resources/technical-execution-requirements.md`).

> **Superseded in part (2026-10-27).** This is the design as agreed on 2026-10-24 and it is kept as written. Two
> decisions below changed during the build: **D5** (OpenCode Go as the primary model provider) is now the secondary
> provider, because the event requires Meterless Nightshift as the primary AI provider, and **D16** (Cursor) is
> settled: the 2026-10-23 announcement made Cursor optional. Where this file and `README.md` disagree, the README
> describes what the repository does today.

A separate implementation spec with tracked tickets (to-questionnaire → to-spec → to-tickets
pipeline) will be derived from this document after the day-1 gates. When the two disagree on
detail, this document wins until a new decision record says otherwise.

---

## 1. What we are building (scope contract)

A restaurant manager asks *"why did Saturday dinner revenue drop?"* and gets an evidence-backed
answer from POS tickets, table-service events, shift rosters and guest reviews — with a **verifier
that blocks any claim the data does not support**.

**In scope**: seeded discrete-event simulator · 6 data tables across 2 stores behind Zetaris ·
investigation core (Planner → Investigator → Verifier → Writer) · period report + drill-down on one
finding · approval step · ground-truth scorecard · web UI (4 screens) · REST API · Docker Compose ·
SAMPLE_MODE replay · trace JSONL.

**Out of scope**: multi-turn free-form Q&A, incidents I2/I3/D1, floor-plan replay, NVIDIA vision,
real-data adapter, 2.5D rendering, per-employee scoring, audio, cameras. The first four of these
(except rendering/scoring/audio/cams) are **scale seams** (§12): designed-in attachment points,
restored only after the feature freeze (§13) if time allows.

**Hard rule**: the differentiators — blocking verifier, decoy separation, ground-truth scorecard —
are never de-scoped. If time runs out, cut polish, not these.

## 2. Locked decisions register

| # | Decision | Value |
|---|---|---|
| D1 | Track / product | Track 02 · ServiceWhy (`decisions/0002`) |
| D2 | Scope cut | Option a: incidents I1 + I4 + decoy D2 + noise N; report + one drill-down (`decisions/0002`) |
| D3 | Backend | Python 3.11, FastAPI, SimPy, pytest — single backend language |
| D4 | Frontend | React + Vite + TypeScript, built at Docker build time, served by nginx; UI port 5173, API port 8000 |
| D5 | Model provider | Primary: OpenCode Go (`https://opencode.ai/zen/go/v1`, OpenAI-compatible), model `deepseek-v4.1-flash` (id verified live 2026-10-24). Header `x-opencode-session: <uuid>` per investigation run. Backup: DeepInfra (OpenAI-compatible), model chosen at wiring time from its catalog |
| D6 | One model for all four roles | Yes — simpler traces; swap only via env |
| D7 | Meterless role | World Model engine (reference architecture implemented in-repo): `WorldStoreService` + `IngestPipelineService` + `ContextBuilderService` — shared hypothesis/evidence state with provenance. Single role. Never described in observability language |
| D8 | Zetaris role & deployment | Single federated SQL surface for the Investigator **and** the Verifier's independent re-query. Local Docker bundle primary (judge-reproducible); Cloud Gateway dev-only fallback. REST channel primary (`:8888`), JDBC fallback (`:10000`) |
| D9 | Store split | PostgreSQL `{pos_tickets, ticket_items, table_events}` + Parquet-on-MinIO filestore `{shifts, plate_returns, reviews}`. DuckDB/SQLite rejected (undocumented connectors) |
| D10 | SAMPLE_MODE | Two modes only: `FULL` (real compose run) and `SAMPLE` (replay recorded trace; zero network, zero services). No bypass-Zetaris query mode in the judged path |
| D11 | Period semantics | Weekly report; lunch/dinner service segments; comparisons vs previous period and vs 4-week same-weekday baseline |
| D12 | Confidence | 3 levels (high/medium/low) backed by effect sizes; no fabricated percentages |
| D13 | Verifier | Hybrid: deterministic checks (independent re-query ±2%, n ≥ 30/segment, decoy share ≥ 50% → downgrade + split) + model judgment (structured block/pass + reason). Retry cap 2 → "insufficient evidence" |
| D14 | Scale-up order | incident-config → multi-turn Q&A → floor-plan → NVIDIA; only after feature freeze (2026-10-25 EOD) |
| D15 | Repo | `KoangWy/servicewhy` (renamed from `irigo-submission` 2026-10-24), private until submission week, then public |
| D16 | Cursor | `.cursor/rules` committed + README section regardless; team report that judges dropped the Cursor requirement is recorded but UNVERIFIED pending a snapshot of the HackOS chat message |

## 3. System architecture

```text
┌─────────────┐   HTTP    ┌───────────────────────────────────────────┐
│ ui (nginx)  │──────────▶│ api (FastAPI, run.py, :8000)              │
│ :5173       │           │  routes → orchestrator                    │
└─────────────┘           │   ├─ Planner      ─┐                      │
                          │   ├─ Investigator ─┼─▶ adapters/          │
                          │   ├─ Verifier     ─┘   ├─ ModelAdapter    │
                          │   └─ Writer            │   (OpenCode Go ▸ │
                          │                       │    DeepInfra)    │
                          │  worldmodel/ ◀─────────┤                  │
                          │  (WorldStoreService,   └─ DataAccessAdapter
                          │   IngestPipeline,          │ REST (primary)
                          │   ContextBuilder)          ▼ JDBC (fallback)
                          │                     ┌───────────────────┐
                          │  report/ · scorecard/│ Zetaris bundle    │
                          │  sim/ · trace.py     │ api:8888 drv:10000│
                          └─────────────────────┤ ui:3000 pg(meta)   │
                                                └───────┬───────────┘
                                          federation    │
                          ┌──────────────────────┬──────┴──────────┐
                          │ postgres :5432       │ minio :9000/:9001│
                          │ POS · ticket_items · │ parquet: shifts ·│
                          │ table_events         │ plate_returns ·  │
                          │                      │ reviews (bucket) │
                          └──────────────────────┴─────────────────┘
```

Compose services: `ui`, `api`, `postgres`, `minio`, `zetaris` (the vendor bundle — **amd64 images**;
on Apple Silicon it runs emulated, expect slow startup). `scripts/init_zetaris.py` is an idempotent
init job: creates the MinIO bucket, uploads parquet, runs `CREATE DATASOURCE` (Postgres),
`REGISTER DATASOURCE TABLE`, `CREATE LIGHTNING FILESTORE TABLE`, and never runs during a request.

### Backend module tree

```text
app/
  run.py                 # entry point (uvicorn on 0.0.0.0:$PORT)
  config.py              # env parsing, SAMPLE_MODE, seed
  api/routes.py schemas.py
  orchestrator.py loop.py
  agent/planner.py investigator.py verifier.py writer.py
  worldmodel/store.py ingest.py context_builder.py
  adapters/model.py zetaris.py
  report/generator.py templates/
  sim/simulator.py incidents.py reviews.py load.py
  scorecard/questions.yaml harness.py metrics.py
  logging/trace.py
ui/                      # Vite + React + TS (report, finding, evidence, approve)
scripts/init_zetaris.py seed_sample.py
input_examples/ output_examples/ logs/examples/
docker-compose.yml Dockerfile.api Dockerfile.ui Makefile
```

## 4. Data layer

### 4.1 PostgreSQL (transactional store)

```sql
CREATE TABLE pos_tickets (
  ticket_id      TEXT PRIMARY KEY,          -- deterministic from seed+party
  business_date  DATE NOT NULL,
  service        TEXT NOT NULL CHECK (service IN ('lunch','dinner')),
  table_id       TEXT NOT NULL,
  party_id       TEXT NOT NULL,
  server_id      TEXT NOT NULL,
  covers         INT  NOT NULL,
  opened_at      TIMESTAMPTZ NOT NULL,
  closed_at      TIMESTAMPTZ NOT NULL,
  total          NUMERIC(10,2) NOT NULL,
  comp_total     NUMERIC(10,2) NOT NULL DEFAULT 0
);
CREATE TABLE ticket_items (
  line_id     TEXT PRIMARY KEY,
  ticket_id   TEXT NOT NULL REFERENCES pos_tickets,
  item_name   TEXT NOT NULL,
  category    TEXT NOT NULL,                -- food / beverage / dessert
  qty         INT NOT NULL,
  unit_price  NUMERIC(8,2) NOT NULL,
  fired_at    TIMESTAMPTZ NOT NULL,         -- kitchen start
  bumped_at   TIMESTAMPTZ NOT NULL,         -- kitchen done
  delivered_at TIMESTAMPTZ NOT NULL,
  comp_reason TEXT                           -- NULL | 'cold_food' | ...
);
CREATE TABLE table_events (
  event_id     TEXT PRIMARY KEY,
  business_date DATE NOT NULL,
  table_id     TEXT NOT NULL,
  party_id     TEXT,
  event_type   TEXT NOT NULL CHECK (event_type IN
    ('seated','greeted','ordered','fired','bumped','delivered','paid','left','reset')),
  occurred_at  TIMESTAMPTZ NOT NULL,
  server_id    TEXT
);
```

### 4.2 Parquet on MinIO (filestore; second store)

`shifts` (shift_id, staff_id, role server|busser, section_id, business_date, start_time, end_time,
tables_assigned) · `plate_returns` (return_id, business_date, ticket_id, item_name,
leftover_share FLOAT) · `reviews` (review_id, business_date, rating INT 1–5, text TEXT —
template-generated, correlated with the party's actual wait times).

### 4.3 Ground truth (never federated)

`data/ground_truth.json` — one record per injected incident (id, type, params, affected windows)
plus the metric deltas it caused. Loaded **only** by the scorecard harness; a code-level rule bans
its import from `app/agent`, `app/adapters`, `app/worldmodel` (enforced by a test that greps
imports — see §10).

### 4.4 Loader

`sim/load.py` runs the simulator, writes Postgres rows + parquet files, uploads to MinIO, then
calls `scripts/init_zetaris.py`. Deterministic: same `SIM_SEED` → identical data (hash of each
table stored in `run_manifest.json`). Simulator parameter set: 1 venue, 20 tables, 4 sections,
5–6 servers, 2 bussers, 11:00–22:00, lunch+dinner peaks, ~30 days, ~1,000–1,500 parties, noise CV
0.25 on all durations. Numbers are tuned once on real runs before freeze; never after the scorecard
is published.

### 4.5 Incident configuration (scale seam)

```yaml
# sim/incidents.yaml — the only place incidents are defined
seed: 20261024
noise: {duration_cv: 0.25}
incidents:
  - {id: I1, type: staffing_overload,
     params: {role: server, sections: [B], weekdays: [fri, sat],
              window: "19:00-21:00", tables_per_server: 7}}
  - {id: I4, type: staffing_overload,
     params: {role: busser, weekdays: [thu, fri, sat],
              window: "20:00-22:00", staff_on: 1}}
  - {id: D2, type: arrival_multiplier,
     params: {dates: "auto", walkin_multiplier: 0.6, revenue_share_target: 0.33}}
```

Effect primitives (`staffing_overload`, `duration_shift`, `portion_multiplier`,
`arrival_multiplier`) are generic simulator capabilities; I2/I3/D1 restore later by appending
entries — no simulator code change. D2's strength is tuned so weather explains ≈ 1/3 of the
Saturday drop, service ≈ 2/3.

## 5. Agent core

Loop: `question → Planner (hypotheses + query plan) → Investigator (federated queries, segment
contrasts, evidence) → Verifier (block / pass / retry) → Writer (answer with citations)`. Max 3
hypotheses per question, max 2 verifier retries, hard cap 12 loop steps per run (bounded run rule).

- **Planner** — turns the question into ≤3 hypotheses chosen from a hypothesis library
  (volume, check size, service delay by stage, staffing, external/decoy) and a query plan
  (metric × segment × comparison).
- **Investigator** — executes plans **only** via `DataAccessAdapter`; computes contrasts
  (period vs baseline, section vs section, dose-response across `tables_per_server` buckets);
  writes every result into the World Model as an `EvidenceItem` with provenance (source, query,
  rows, values, n).
- **Verifier** — §7. Can **block**: sends the case back with a machine-readable reason, or
  forces the answer "insufficient evidence".
- **Writer** — produces findings with the §6 field contract; never invents numbers; every
  numeric claim references an `EvidenceItem` id.

### 5.1 World Model (Meterless integration)

Entities in `WorldStoreService`: `Hypothesis` (id, statement, status
proposed|supported|rejected|blocked, provenance), `EvidenceItem` (id, hypothesis_id, source, query,
metric, value, contrast, n, produced_by), `Finding` (§6 contract). Ingest through
`IngestPipelineService` (idempotent, resumable — a crashed run re-ingests safely); all reads by
Planner/Verifier/Writer go through `ContextBuilderService` structured payloads (selection reason +
trace metadata included), never direct store joins. Content-hash stable ids. JSONL append log of
every world mutation ships to `logs/` — this is also the judge-facing evidence of Meterless doing
real work inside the loop.

### 5.2 ModelAdapter

Single seam for all model calls. Config: `MODEL_API_KEY`, `MODEL_BASE_URL`, `MODEL_ID` (primary
OpenCode Go) and `MODEL_BACKUP_*` (DeepInfra). Sends `x-opencode-session: <run uuid>` (=
trace_id) on every call of an investigation; automatic provider failover on repeated transport
errors. Structured outputs via JSON schema where supported. Per-call timeout 60 s; per-run model
budget capped.

## 6. Findings, report, approval

**Finding contract** (API, UI, report and scorecard all consume this shape):

```json
{
  "id": "f-…",
  "cause_hypothesis": "Section B 19:00–21:00 Fri/Sat ran 7 tables per server vs 4 baseline",
  "evidence": [{"evidence_id": "e-…", "source": "table_events+shifts (Zetaris)",
                 "query": "SELECT …", "metric": "seated_to_greet_p90_min",
                 "value": 16.2, "baseline": 3.1, "n": 41}],
  "confidence": "high",
  "effect_size": {"metric": "seated_to_greet_p90_min", "delta": "+13.1 min"},
  "uncertainty": "Cannot separate greeting lag from order lag inside section B",
  "recommended_action": "Add one server to section B 19:00–21:00 Fri/Sat",
  "status": "proposed"
}
```

Framing rule: causes are **staffing/process conditions** (section, shift, window), never named
individuals. The **period report** = 1 summary paragraph + 3–5 findings + data-provenance appendix
(generated as a batch run of the same core). **Approval**: `POST /findings/{id}/approve|reject`
flips status; approved actions are logged with timestamp and user role ("manager").

## 7. Verifier (the differentiator)

Deterministic checks (code, not model — each one is a trace event):

| # | Rule | Threshold | Action |
|---|---|---|---|
| V1 | Every numeric claim recomputed by an independent second query | mismatch > ±2% | block |
| V2 | Minimum sample per segment | n < 30 parties | block or downgrade |
| V3 | Causal claims need a contrast (before/after, dose-response across buckets, or cross-section) | no contrast found | block |
| V4 | Decoy comparison: external explanation share | D2 explains ≥ 50% of effect | downgrade + force share split in the answer |
| V5 | Retry budget | > 2 verifier rejections | answer "insufficient evidence" |

Model check (structured output): given hypothesis + evidence items, return
`{verdict: block|pass, reason}` only — the model never recomputes numbers. V1 re-queries go
through Zetaris (same surface, fresh query — this is the sponsor-tech "unique" slide).
Thresholds are initial values: tuned **once** on simulator output before feature freeze, then
frozen and published in the README with the scorecard.

## 8. API surface (UI and judges use the same API)

| Method & path | Purpose |
|---|---|
| `POST /run` | one investigation; request/response follow the Technical Execution Guide JSON contract (`run_id`, `input.query`, `options.sample_mode` → `status`, `output`, `agents[]`, `trace_id`, `log_file`, `execution_time_seconds`; structured errors on failure) |
| `POST /reports` | generate period report `{period: {start, end}}` → `report_id` |
| `GET /reports/{id}` | report JSON (summary + findings) |
| `GET /findings/{id}` | finding contract above |
| `POST /findings/{id}/drilldown` | run the "why" investigation on one finding (optional `question`) |
| `POST /findings/{id}/approve` / `reject` | approval step |
| `GET /traces/{run_id}` | the JSONL trace |
| `GET /health` | `{status, zetaris: up\|down\|sample, model, sample_mode}` |

Three input/output example pairs ship in `input_examples/` / `output_examples/` (tech-guide
requirement). Everything binds `0.0.0.0`; UI and API on separate ports.

## 9. SAMPLE_MODE, traces, examples

- `SAMPLE_MODE=false` (FULL): compose stack real; requires keys.
- `SAMPLE_MODE=true`: the API serves a recorded run — same endpoints, same JSON contracts, trace
  replayed from `logs/examples/*.jsonl`; zero network, no Zetaris/MinIO/Postgres/model needed.
  A judge without credentials sees the full agent behaviour including a verifier block.
- Trace: one JSONL per run `logs/trace-<run_id>.jsonl` (role, action, input/output summary, query,
  rows used, verdict, retry_count, timestamps) + readable stdout lines. Secrets masked. World-model
  mutation log ships as JSONL alongside.

## 10. Scorecard (never de-scoped)

Harness: `make scorecard` — fresh seeded dataset, runs the canned question set, joins the trace
with `data/ground_truth.json`, prints a markdown table for the README.

Questions (10):

1. Demo main: "Why did Saturday dinner revenue drop 18%?"
2. Abstain — no data: "Did the new menu cause the drop?"
3. Decoy trap: "Is the drop just fewer customers?"
4. I1 direct: "Why are greeting times long in section B on Friday nights?"
5. I4 direct: "Why do tables reset so slowly late evening?"
6. Period compare: "How did this week compare to last week?"
7. Abstain — small sample: "Why did tips drop last Tuesday?"
8. Non-cause probe: "Is the kitchen slow on Saturdays?" (data shows normal bump-to-delivery → answer no)
9. Cross-source: "What do guest reviews say about last weekend, and does it match the timings?"
10. Refusal to rank individuals: "Who is our worst server?" (→ staffing-condition reframing)

Metrics: root-cause hit rate vs ground truth · evidence precision (share of cited rows supporting
the claim) · verifier effect (unsupported claims caught / wrongly blocked) · decoy rejection rate ·
abstention correctness · retries per investigation. **Tuning rule**: simulator and thresholds are
never adjusted after the scorecard is published; the README says so. A grep-test enforces that
agent-side code never imports ground truth (§4.3).

## 11. UI (4 screens, English, thin on purpose)

Report (summary + findings list) · Finding detail (evidence, confidence, uncertainty, action,
approve/reject) · Evidence & trace panel (query, rows, verdicts, retry chain — the "agent doing
real work" view) · Drill-down ask box on a finding. Vite + React + TS, no heavy component library;
synthetic-data label visible on every screen.

## 12. Scale seams (post-freeze only, in order)

1. Incidents I2 (runner gap), I3 (over-portioned dish), D1 (promo day) — append to
   `sim/incidents.yaml` + hypothesis library entries; no core change.
2. Multi-turn Q&A — conversational layer over the same `/run` core; the world model already holds
   the state.
3. Floor-plan 2D replay of one evening (optional).
4. NVIDIA Nemotron — only as a ModelAdapter provider comparison or sample-video stretch; never
   load-bearing.

## 13. Build plan, checkpoints, kill rules

| Day | Output | Checkpoint (acceptance criteria) |
|---|---|---|
| 2026-10-24 (today) | **Gates by 12:00 ICT**: Zetaris federated query joining 2 sources (local bundle preferred; Cloud Gateway acceptable — amd64 emulation on M-series is the known risk) + Meterless World Model skeleton with generator roundtrip. Then simulator skeleton + loader → Postgres/MinIO | Gate green; else `decisions/0002` fallback to direction A |
| 2026-10-25 | Planner + Investigator end-to-end on the demo question; report v0; parquet/MinIO registration in compose | **EOD: one full why-answer via `POST /run` with trace — else kill rule below. FEATURE FREEZE.** |
| 2026-10-26 | Verifier block + retry visible; drill-down; scorecard harness; approval; UI wired; README; clean-machine run; record demo | Fresh clone → `docker compose up` → judge checklist passes; video ≤ 4 min with verifier block in first 90 s |
| 2026-10-27 | Fixes only; make repo public; submit early | Submitted well before 23:45 UTC |

Kill rule (refines `decisions/0002`): if EOD 10-25 has no end-to-end why-answer, cut report polish
and UI extras — keep exactly one question flow + verifier + scorecard. Sponsor gates failing at
noon 10-24 still means direction A per `decisions/0002`.

Roles (amended 2026-10-24 evening, per strategy-repo `decisions/0004`): **Khoa (Lemoris2)
implements the whole system** — backend, agent core, UI, compose, scripts, README — working
keyless (tests, SAMPLE_MODE, model cassettes) from the specs and tickets. **Huy (KoangWy)** owns
specs/architecture, holds the only FULL-mode environment (Zetaris + Meterless + API keys) and runs
the QA gate: 10-25 evening FULL smoke, then 10-26 tuning + scorecard publish (= freeze). Demo
production is deferred until after QA passes, still before the deadline. Khoa keeps the HackOS
placeholder (`decisions/0003`).

## 14. Security, privacy, compliance

Secrets via env only; `.env` gitignored; `.env.example` placeholders; keys never in code, logs,
examples, video or slides (mask `…redacted`). All data synthetic and labelled. No individual staff
ranking; findings name conditions, not people. No faces, audio, or real personal data anywhere.
Vietnamese law (Decree 13/2023) noted in the README's limitations for any future real deployment.

## 15. Open items (owner · due)

- Snapshot of the HackOS chat message dropping the Cursor requirement (needs login — team to copy
  text/screenshot into `docs/` with provenance) · Huy or Khoa · before submission write-up.
- DeepInfra backup model id picked at wiring (from its live catalog; keyless to list) · Khoa ·
  10-25, verified in Huy's QA run.
- MinIO filestore registration spike inside the Zetaris bundle (the "reachable storage" PATH
  question) — part of today's gate · Huy · today.
- Zetaris local startup time on Apple Silicon — measured during today's gate; if unusable, decide
  cloud-dev + recorded-demo posture explicitly · Huy · today.
